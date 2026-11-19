// Copyright (c) 2026-2027 zbc
// 会话密钥派生、AUTH 证明与 AES-256-GCM（OpenSSL）。
#include "urc/crypto.h"

#include <algorithm>
#include <cstring>
#include <stdexcept>

#include <openssl/evp.h>
#include <openssl/hmac.h>

#include "urc/wire.h"

namespace urc {
namespace {

using Sha256 = std::array<uint8_t, 32>;

Sha256 hmac_sha256(std::span<const uint8_t> key, std::span<const uint8_t> data) {
    Sha256 out{};
    unsigned int out_len = static_cast<unsigned int>(out.size());
    if (!HMAC(EVP_sha256(), key.data(), static_cast<int>(key.size()), data.data(), data.size(),
              out.data(), &out_len)) {
        throw std::runtime_error("hmac failed");
    }
    return out;
}

std::array<uint8_t, 32> hkdf_expand(std::span<const uint8_t, 32> prk, std::span<const uint8_t> info,
                                    size_t length) {
    std::array<uint8_t, 32> out{};
    Sha256 t{};
    size_t t_len = 0;
    size_t pos = 0;
    uint8_t counter = 1;
    while (pos < length) {
        std::vector<uint8_t> msg;
        msg.insert(msg.end(), t.begin(), t.begin() + static_cast<std::ptrdiff_t>(t_len));
        msg.insert(msg.end(), info.begin(), info.end());
        msg.push_back(counter++);
        t = hmac_sha256(prk, msg);
        t_len = t.size();
        size_t n = std::min(length - pos, t.size());
        std::memcpy(out.data() + pos, t.data(), n);
        pos += n;
    }
    return out;
}

}  // namespace

CryptoContext CryptoContext::derive(std::span<const uint8_t, kSecretLen> secret,
                                    std::span<const uint8_t, kNonceLen> app_nonce,
                                    std::span<const uint8_t, kNonceLen> robot_nonce) {
    std::array<uint8_t, kNonceLen * 2> salt{};
    std::memcpy(salt.data(), app_nonce.data(), kNonceLen);
    std::memcpy(salt.data() + kNonceLen, robot_nonce.data(), kNonceLen);
    auto prk = hmac_sha256(salt, secret);

    CryptoContext ctx;
    std::copy(app_nonce.begin(), app_nonce.end(), ctx.app_nonce.begin());
    std::copy(robot_nonce.begin(), robot_nonce.end(), ctx.robot_nonce.begin());
    static constexpr char kPrefix[] = "urc/session/v1/";
    auto expand = [&](const char* suffix, size_t len) {
        std::string info = std::string(kPrefix) + suffix;
        auto full = hkdf_expand(prk, std::span<const uint8_t>(
                                          reinterpret_cast<const uint8_t*>(info.data()), info.size()),
                                len);
        Bytes out(full.begin(), full.begin() + static_cast<std::ptrdiff_t>(len));
        return out;
    };
    auto app = expand("app2robot", kKeyLen);
    auto robot = expand("robot2app", kKeyLen);
    auto confirm = expand("confirm", 8);
    std::copy(app.begin(), app.end(), ctx.app2robot_key.begin());
    std::copy(robot.begin(), robot.end(), ctx.robot2app_key.begin());
    std::copy(confirm.begin(), confirm.end(), ctx.key_confirm.begin());
    return ctx;
}

std::array<uint8_t, 12> CryptoContext::make_nonce(uint64_t seq, bool to_robot) {
    std::array<uint8_t, 12> nonce{};
    nonce[0] = to_robot ? 0x01 : 0x02;
    for (int i = 0; i < 8; ++i) nonce[4 + i] = static_cast<uint8_t>(seq >> (8 * i));
    return nonce;
}

std::array<uint8_t, 32> auth_proof(std::span<const uint8_t, kSecretLen> secret,
                                   std::span<const uint8_t, kNonceLen> app_nonce,
                                   std::span<const uint8_t, kNonceLen> robot_nonce,
                                   uint32_t session_id) {
    static constexpr char kInfo[] = "urc/auth/v1";
    std::vector<uint8_t> msg;
    msg.insert(msg.end(), kInfo, kInfo + sizeof(kInfo) - 1);
    msg.insert(msg.end(), app_nonce.begin(), app_nonce.end());
    msg.insert(msg.end(), robot_nonce.begin(), robot_nonce.end());
    wire::put_u32(msg, session_id);
    return hmac_sha256(secret, msg);
}

Bytes aes_gcm_encrypt(std::span<const uint8_t, kKeyLen> key, std::span<const uint8_t, 12> nonce,
                      std::span<const uint8_t> aad, std::span<const uint8_t> plaintext) {
    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) throw std::runtime_error("evp ctx");
    Bytes out(plaintext.size() + kTagLen);
    int len = 0;
    try {
        if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) throw std::runtime_error("gcm init");
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, 12, nullptr) != 1) throw std::runtime_error("gcm ivlen");
        if (EVP_EncryptInit_ex(ctx, nullptr, nullptr, key.data(), nonce.data()) != 1) throw std::runtime_error("gcm key");
        if (!aad.empty() && EVP_EncryptUpdate(ctx, nullptr, &len, aad.data(), static_cast<int>(aad.size())) != 1) {
            throw std::runtime_error("gcm aad");
        }
        if (!plaintext.empty() &&
            EVP_EncryptUpdate(ctx, out.data(), &len, plaintext.data(), static_cast<int>(plaintext.size())) != 1) {
            throw std::runtime_error("gcm encrypt");
        }
        if (EVP_EncryptFinal_ex(ctx, out.data() + len, &len) != 1) throw std::runtime_error("gcm final");
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, kTagLen, out.data() + plaintext.size()) != 1) {
            throw std::runtime_error("gcm tag");
        }
    } catch (...) {
        EVP_CIPHER_CTX_free(ctx);
        throw;
    }
    EVP_CIPHER_CTX_free(ctx);
    return out;
}

Bytes aes_gcm_decrypt(std::span<const uint8_t, kKeyLen> key, std::span<const uint8_t, 12> nonce,
                      std::span<const uint8_t> aad, std::span<const uint8_t> ciphertext_and_tag) {
    if (ciphertext_and_tag.size() < kTagLen) throw std::runtime_error("short ciphertext");
    size_t plain_len = ciphertext_and_tag.size() - kTagLen;
    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) throw std::runtime_error("evp ctx");
    Bytes out(plain_len);
    int len = 0;
    try {
        if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), nullptr, nullptr, nullptr) != 1) throw std::runtime_error("gcm init");
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, 12, nullptr) != 1) throw std::runtime_error("gcm ivlen");
        if (EVP_DecryptInit_ex(ctx, nullptr, nullptr, key.data(), nonce.data()) != 1) throw std::runtime_error("gcm key");
        if (!aad.empty() && EVP_DecryptUpdate(ctx, nullptr, &len, aad.data(), static_cast<int>(aad.size())) != 1) {
            throw std::runtime_error("gcm aad");
        }
        if (plain_len > 0 &&
            EVP_DecryptUpdate(ctx, out.data(), &len, ciphertext_and_tag.data(), static_cast<int>(plain_len)) != 1) {
            throw std::runtime_error("gcm decrypt");
        }
        std::array<uint8_t, kTagLen> tag{};
        std::memcpy(tag.data(), ciphertext_and_tag.data() + plain_len, kTagLen);
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, kTagLen, tag.data()) != 1) throw std::runtime_error("gcm tag");
        if (EVP_DecryptFinal_ex(ctx, out.data() + len, &len) != 1) throw std::runtime_error("gcm auth failed");
    } catch (...) {
        EVP_CIPHER_CTX_free(ctx);
        throw;
    }
    EVP_CIPHER_CTX_free(ctx);
    return out;
}

bool ReplayWindow::accept(uint32_t seq) {
    if (!initialized_) {
        initialized_ = true;
        last_ = seq;
        bits_.assign(window_, 0);
        bits_[0] = 1;
        return true;
    }
    int32_t diff = static_cast<int32_t>(seq - last_);
    if (diff > 0) {
        uint32_t shift = static_cast<uint32_t>(diff);
        if (shift >= window_) {
            std::fill(bits_.begin(), bits_.end(), 0);
        } else {
            for (size_t i = bits_.size(); i-- > shift;) bits_[i] = bits_[i - shift];
            std::fill(bits_.begin(), bits_.begin() + shift, 0);
        }
        last_ = seq;
        bits_[0] = 1;
        return true;
    }
    uint32_t back = static_cast<uint32_t>(-diff);
    if (back >= window_ || bits_[back]) return false;
    bits_[back] = 1;
    return true;
}

}  // namespace urc
