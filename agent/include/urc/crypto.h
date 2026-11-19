// Copyright (c) 2026-2027 zbc
// 会话密钥派生与 AES-256-GCM（OpenSSL 3）。
#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace urc {

constexpr size_t kSecretLen = 32;
constexpr size_t kNonceLen = 16;
constexpr size_t kKeyLen = 32;
constexpr size_t kTagLen = 16;

using Bytes = std::vector<uint8_t>;
using Key = std::array<uint8_t, kKeyLen>;

struct CryptoContext {
    std::array<uint8_t, kNonceLen> app_nonce{};
    std::array<uint8_t, kNonceLen> robot_nonce{};
    Key app2robot_key{};
    Key robot2app_key{};
    std::array<uint8_t, 8> key_confirm{};

    static CryptoContext derive(std::span<const uint8_t, kSecretLen> secret,
                                std::span<const uint8_t, kNonceLen> app_nonce,
                                std::span<const uint8_t, kNonceLen> robot_nonce);
    static std::array<uint8_t, 12> make_nonce(uint64_t seq, bool to_robot);
};

std::array<uint8_t, 32> auth_proof(std::span<const uint8_t, kSecretLen> secret,
                                   std::span<const uint8_t, kNonceLen> app_nonce,
                                   std::span<const uint8_t, kNonceLen> robot_nonce,
                                   uint32_t session_id);

Bytes aes_gcm_encrypt(std::span<const uint8_t, kKeyLen> key, std::span<const uint8_t, 12> nonce,
                      std::span<const uint8_t> aad, std::span<const uint8_t> plaintext);
Bytes aes_gcm_decrypt(std::span<const uint8_t, kKeyLen> key, std::span<const uint8_t, 12> nonce,
                      std::span<const uint8_t> aad, std::span<const uint8_t> ciphertext_and_tag);

// 滑动窗口重放检测（u32 序号回绕按 RFC 1982 比较）。
class ReplayWindow {
public:
    explicit ReplayWindow(uint32_t window = 2048) : window_(window) {}
    bool accept(uint32_t seq);

private:
    uint32_t window_;
    bool initialized_ = false;
    uint32_t last_ = 0;
    std::vector<uint8_t> bits_;
};

}  // namespace urc
