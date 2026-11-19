// Copyright (c) 2026-2027 zbc
// 协议向量测试：读取 protocol/vectors/*.json，验证 C++ 实现与 Python 参考一致。
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "urc/crypto.h"
#include "urc/frame.h"
#include "urc/messages.h"

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& name, const std::string& detail = "") {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("[FAIL] %s%s%s\n", name.c_str(), detail.empty() ? "" : ": ", detail.c_str());
    }
}

std::vector<uint8_t> unhex(const std::string& text) {
    std::vector<uint8_t> out;
    out.reserve(text.size() / 2);
    for (size_t i = 0; i + 1 < text.size(); i += 2) {
        out.push_back(static_cast<uint8_t>(std::stoul(text.substr(i, 2), nullptr, 16)));
    }
    return out;
}

std::string tohex(std::span<const uint8_t> data) {
    static constexpr char kHex[] = "0123456789abcdef";
    std::string out;
    out.reserve(data.size() * 2);
    for (uint8_t b : data) {
        out.push_back(kHex[b >> 4]);
        out.push_back(kHex[b & 0x0F]);
    }
    return out;
}

template <typename T>
T get(const json& obj, const char* key, T fallback = T{}) {
    return obj.contains(key) ? obj.at(key).get<T>() : fallback;
}

std::vector<float> floats(const json& arr) {
    std::vector<float> out;
    if (arr.is_array()) {
        for (const auto& v : arr) out.push_back(v.get<float>());
    }
    return out;
}

std::optional<urc::CryptoContext> maybe_ctx(const json& given) {
    if (!given.contains("secret_hex")) return std::nullopt;
    auto secret = unhex(given.at("secret_hex").get<std::string>());
    auto an = unhex(given.at("app_nonce_hex").get<std::string>());
    auto rn = unhex(given.at("robot_nonce_hex").get<std::string>());
    if (secret.size() != 32 || an.size() != 16 || rn.size() != 16) return std::nullopt;
    return urc::CryptoContext::derive(
        std::span<const uint8_t, 32>(secret.data(), 32),
        std::span<const uint8_t, 16>(an.data(), 16),
        std::span<const uint8_t, 16>(rn.data(), 16));
}

// ---------- frames ----------

void run_frames(const fs::path& path) {
    std::ifstream in(path);
    auto doc = json::parse(in);
    for (const auto& c : doc.at("cases")) {
        const std::string name = c.at("name").get<std::string>();
        const auto& given = c.at("given");
        const auto& expect = c.at("expect");
        if (c.at("mode") == "encode") {
            urc::Frame frame;
            frame.type = get<uint8_t>(given, "type");
            frame.flags = get<uint8_t>(given, "flags");
            frame.stream = get<uint8_t>(given, "stream");
            frame.session_id = get<uint32_t>(given, "session_id");
            frame.seq = get<uint32_t>(given, "seq");
            frame.ts_us = get<uint64_t>(given, "ts_us");
            frame.payload = unhex(given.at("payload_hex").get<std::string>());
            auto ctx = maybe_ctx(given);
            auto raw = urc::pack_frame(frame, ctx ? &*ctx : nullptr, get<bool>(given, "to_robot", true));
            check(tohex(raw) == expect.at("hex").get<std::string>(), name);
        } else if (c.at("mode") == "decode") {
            auto raw = unhex(given.at("hex").get<std::string>());
            auto ctx = maybe_ctx(given);
            try {
                auto frame = urc::unpack_frame(raw, ctx ? &*ctx : nullptr, get<bool>(given, "from_robot", false));
                bool want_ok = get<bool>(expect, "ok", false);
                check(want_ok, name, "unexpected decode success");
                if (!want_ok) continue;
                check(frame.type == get<uint8_t>(expect, "type"), name + "/type");
                check(frame.stream == get<uint8_t>(expect, "stream"), name + "/stream");
                check(frame.session_id == get<uint32_t>(expect, "session_id"), name + "/session");
                check(frame.seq == get<uint32_t>(expect, "seq"), name + "/seq");
                check(frame.ts_us == get<uint64_t>(expect, "ts_us"), name + "/ts");
                check(tohex(frame.payload) == expect.at("payload_hex").get<std::string>(), name + "/payload");
            } catch (const std::exception&) {
                check(!get<bool>(expect, "ok", false), name, "unexpected decode failure");
            }
        }
    }
}

// ---------- crypto ----------

void run_crypto(const fs::path& path) {
    std::ifstream in(path);
    auto doc = json::parse(in);
    for (const auto& c : doc.at("cases")) {
        const std::string name = c.at("name").get<std::string>();
        const auto& g = c.at("given");
        const auto& e = c.at("expect");
        const std::string kind = c.at("kind").get<std::string>();
        if (kind == "derive") {
            auto secret = unhex(g.at("secret_hex").get<std::string>());
            auto an = unhex(g.at("app_nonce_hex").get<std::string>());
            auto rn = unhex(g.at("robot_nonce_hex").get<std::string>());
            auto ctx = urc::CryptoContext::derive(
                std::span<const uint8_t, 32>(secret.data(), 32),
                std::span<const uint8_t, 16>(an.data(), 16),
                std::span<const uint8_t, 16>(rn.data(), 16));
            check(tohex(ctx.app2robot_key) == e.at("app2robot_hex").get<std::string>(), name + "/app2robot");
            check(tohex(ctx.robot2app_key) == e.at("robot2app_hex").get<std::string>(), name + "/robot2app");
            check(tohex(ctx.key_confirm) == e.at("confirm_hex").get<std::string>(), name + "/confirm");
        } else if (kind == "auth") {
            auto secret = unhex(g.at("secret_hex").get<std::string>());
            auto an = unhex(g.at("app_nonce_hex").get<std::string>());
            auto rn = unhex(g.at("robot_nonce_hex").get<std::string>());
            auto proof = urc::auth_proof(
                std::span<const uint8_t, 32>(secret.data(), 32),
                std::span<const uint8_t, 16>(an.data(), 16),
                std::span<const uint8_t, 16>(rn.data(), 16),
                get<uint32_t>(g, "session_id"));
            check(tohex(proof) == e.at("proof_hex").get<std::string>(), name);
        } else if (kind == "aead") {
            auto key = unhex(g.at("key_hex").get<std::string>());
            auto nonce = unhex(g.at("nonce_hex").get<std::string>());
            auto aad = unhex(g.at("aad_hex").get<std::string>());
            auto plain = unhex(g.at("plaintext_hex").get<std::string>());
            auto cipher = urc::aes_gcm_encrypt(
                std::span<const uint8_t, 32>(key.data(), 32),
                std::span<const uint8_t, 12>(nonce.data(), 12), aad, plain);
            check(tohex(cipher) == e.at("ciphertext_hex").get<std::string>(), name);
            auto back = urc::aes_gcm_decrypt(
                std::span<const uint8_t, 32>(key.data(), 32),
                std::span<const uint8_t, 12>(nonce.data(), 12), aad, cipher);
            check(back == plain, name + "/decrypt");
        } else if (kind == "replay") {
            urc::ReplayWindow window(get<uint32_t>(g, "window", 2048));
            for (auto seq : g.at("previous")) window.accept(seq.get<uint32_t>());
            bool accepted = window.accept(get<uint32_t>(g, "incoming"));
            check(accepted == e.at("accept").get<bool>(), name);
        }
    }
}

// ---------- frag ----------

void run_frag(const fs::path& path) {
    std::ifstream in(path);
    auto doc = json::parse(in);
    for (const auto& c : doc.at("cases")) {
        const std::string name = c.at("name").get<std::string>();
        const auto& g = c.at("given");
        const auto& e = c.at("expect");
        if (c.at("mode") == "fragment") {
            auto payload = unhex(g.at("payload_hex").get<std::string>());
            auto parts = urc::fragment_payload(payload, get<size_t>(g, "mtu", 1200), get<uint32_t>(g, "msg_id"));
            std::vector<std::string> got;
            for (const auto& p : parts) got.push_back(tohex(p));
            std::vector<std::string> want;
            for (const auto& v : e.at("fragments")) want.push_back(v.get<std::string>());
            check(got == want, name);
        } else if (c.at("mode") == "reassemble") {
            urc::Reassembler reassembler;
            std::optional<std::vector<uint8_t>> delivered;
            for (const auto& frag_hex : g.at("fragments")) {
                auto out = reassembler.add(unhex(frag_hex.get<std::string>()));
                if (out) delivered = out;
            }
            if (e.at("payload_hex").is_null()) {
                check(!delivered.has_value(), name, "expected no delivery");
            } else {
                check(delivered.has_value() && tohex(*delivered) == e.at("payload_hex").get<std::string>(), name);
            }
        }
    }
}

// ---------- session/messages ----------

void run_session(const fs::path& path) {
    std::ifstream in(path);
    auto doc = json::parse(in);
    for (const auto& c : doc.at("cases")) {
        const std::string name = c.at("name").get<std::string>();
        const auto& g = c.at("given");
        const std::string kind = c.at("kind").get<std::string>();
        std::vector<uint8_t> got;
        if (kind == "hello") {
            urc::Hello hello;
            hello.proto_major = get<uint16_t>(g, "proto_major", 1);
            hello.proto_minor = get<uint16_t>(g, "proto_minor", 0);
            hello.role = get<uint8_t>(g, "role");
            hello.flags = get<uint16_t>(g, "flags");
            auto app_id = unhex(g.at("app_id_hex").get<std::string>());
            auto an = unhex(g.at("app_nonce_hex").get<std::string>());
            std::copy(app_id.begin(), app_id.end(), hello.app_id.begin());
            std::copy(an.begin(), an.end(), hello.app_nonce.begin());
            hello.app_version = g.at("app_version").get<std::string>();
            got = urc::pack_hello(hello);
        } else if (kind == "hello_ack") {
            urc::HelloAck ack;
            ack.proto_major = get<uint16_t>(g, "proto_major", 1);
            ack.proto_minor = get<uint16_t>(g, "proto_minor", 0);
            ack.session_id = get<uint32_t>(g, "session_id");
            ack.robot_id = g.at("robot_id").get<std::string>();
            ack.robot_name = g.at("robot_name").get<std::string>();
            ack.form = g.at("form").get<std::string>();
            auto rn = unhex(g.at("robot_nonce_hex").get<std::string>());
            std::copy(rn.begin(), rn.end(), ack.robot_nonce.begin());
            ack.caps_hash = get<uint32_t>(g, "caps_hash");
            ack.ctrl_port = get<uint16_t>(g, "ctrl_port");
            ack.video_port = get<uint16_t>(g, "video_port");
            ack.depth_port = get<uint16_t>(g, "depth_port");
            ack.map_port = get<uint16_t>(g, "map_port");
            ack.web_port = get<uint16_t>(g, "web_port");
            ack.auth_required = get<uint8_t>(g, "auth_required");
            got = urc::pack_hello_ack(ack);
        } else if (kind == "auth") {
            urc::Auth auth;
            auto proof = unhex(g.at("proof_hex").get<std::string>());
            auto id = unhex(g.at("client_id_hex").get<std::string>());
            std::copy(proof.begin(), proof.end(), auth.proof.begin());
            std::copy(id.begin(), id.end(), auth.client_id.begin());
            auth.client_name = g.at("client_name").get<std::string>();
            got = urc::pack_auth(auth);
        } else if (kind == "auth_ok") {
            auto confirm = unhex(g.at("key_confirm_hex").get<std::string>());
            got = urc::pack_auth_ok(get<uint8_t>(g, "role"),
                                    std::span<const uint8_t, 8>(confirm.data(), 8),
                                    get<uint64_t>(g, "server_ts_us"));
        } else if (kind == "caps") {
            auto data = unhex(g.at("json_hex").get<std::string>());
            got = urc::pack_caps_raw(data);
        } else if (kind == "telem") {
            urc::Telemetry t;
            t.seq = get<uint32_t>(g, "seq");
            t.ts_us = get<uint64_t>(g, "ts_us");
            t.fsm_state = get<uint32_t>(g, "fsm_state");
            t.fault_flags = get<uint32_t>(g, "fault_flags");
            t.battery_pct = get<uint8_t>(g, "battery_pct");
            t.x = get<float>(g, "x");
            t.y = get<float>(g, "y");
            t.yaw = get<float>(g, "yaw");
            if (g.contains("joint_q")) t.joint_q = floats(g.at("joint_q"));
            if (g.contains("joint_dq")) t.joint_dq = floats(g.at("joint_dq"));
            if (g.contains("joint_tau")) t.joint_tau = floats(g.at("joint_tau"));
            if (g.contains("imu_quat")) t.imu_quat = floats(g.at("imu_quat"));
            if (g.contains("imu_gyro")) t.imu_gyro = floats(g.at("imu_gyro"));
            if (g.contains("policy_name")) t.policy_name = g.at("policy_name").get<std::string>();
            t.inference_us = get<uint32_t>(g, "inference_us");
            t.episode_len = get<uint32_t>(g, "episode_len");
            t.queue_depth = get<uint32_t>(g, "queue_depth");
            t.link_rtt_us = get<uint32_t>(g, "link_rtt_us");
            t.link_loss_pct = get<uint32_t>(g, "link_loss_pct");
            t.remote_age_ms = get<uint32_t>(g, "remote_age_ms");
            t.map_revision = get<uint32_t>(g, "map_revision");
            got = urc::pack_telem(t);
        } else if (kind == "model_state") {
            urc::ModelState s;
            s.seq = get<uint32_t>(g, "seq");
            s.ts_us = get<uint64_t>(g, "ts_us");
            s.joint_order_hash = get<uint32_t>(g, "joint_order_hash");
            s.joint_count = get<uint16_t>(g, "joint_count");
            s.flags = get<uint8_t>(g, "flags");
            s.frame_id = get<uint8_t>(g, "frame_id");
            auto pos = floats(g.at("root_pos"));
            auto quat = floats(g.at("root_quat"));
            for (size_t i = 0; i < 3; ++i) s.root_pos[i] = pos[i];
            for (size_t i = 0; i < 4; ++i) s.root_quat[i] = quat[i];
            s.joint_pos = floats(g.at("joint_pos"));
            got = urc::pack_model_state(s);
        } else if (kind == "discover") {
            auto an = unhex(g.at("app_nonce_hex").get<std::string>());
            auto id = unhex(g.at("app_id_hex").get<std::string>());
            got = urc::pack_discover(std::span<const uint8_t, 16>(an.data(), 16),
                                     std::span<const uint8_t, 16>(id.data(), 16));
        } else if (kind == "announce") {
            urc::Announce a;
            a.robot_id = g.at("robot_id").get<std::string>();
            a.robot_name = g.at("robot_name").get<std::string>();
            a.form = g.at("form").get<std::string>();
            a.ctrl_port = get<uint16_t>(g, "ctrl_port");
            a.video_port = get<uint16_t>(g, "video_port");
            a.depth_port = get<uint16_t>(g, "depth_port");
            a.map_port = get<uint16_t>(g, "map_port");
            a.web_port = get<uint16_t>(g, "web_port");
            a.caps_hash = get<uint32_t>(g, "caps_hash");
            a.pair_state = get<uint8_t>(g, "pair_state");
            got = urc::pack_announce(a);
        } else {
            continue;
        }
        check(tohex(got) == c.at("expect").at("hex").get<std::string>(), name);
    }
}

}  // namespace

int main(int argc, char** argv) {
    fs::path dir = argc > 1 ? fs::path(argv[1]) : fs::path(URC_VECTORS_DIR);
    try {
        run_frames(dir / "frames.json");
        run_crypto(dir / "crypto.json");
        run_frag(dir / "frag.json");
        run_session(dir / "session.json");
    } catch (const std::exception& exc) {
        std::printf("[FAIL] exception: %s\n", exc.what());
        return 2;
    }
    std::printf("checks=%d failures=%d\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
