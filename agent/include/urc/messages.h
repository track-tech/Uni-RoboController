// Copyright (c) 2026-2027 zbc
// 消息载荷编解码（HELLO/AUTH/CAPS/CTRL/TELEM/MODEL_STATE/发现等）。
#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace urc {

using Bytes = std::vector<uint8_t>;

// ---------- HELLO / HELLO_ACK ----------

struct Hello {
    uint16_t proto_major = 1;
    uint16_t proto_minor = 0;
    uint8_t role = 0;
    uint16_t flags = 0;
    std::array<uint8_t, 16> app_id{};
    std::array<uint8_t, 16> app_nonce{};
    std::string app_version;
};

Bytes pack_hello(const Hello& hello);
Hello unpack_hello(std::span<const uint8_t> payload);

struct HelloAck {
    uint16_t proto_major = 1;
    uint16_t proto_minor = 0;
    uint32_t session_id = 0;
    std::string robot_id;
    std::string robot_name;
    std::string form;
    std::array<uint8_t, 16> robot_nonce{};
    uint32_t caps_hash = 0;
    uint16_t ctrl_port = 47800;
    uint16_t video_port = 47801;
    uint16_t depth_port = 47802;
    uint16_t map_port = 47803;
    uint16_t web_port = 47880;
    uint8_t auth_required = 1;
};

Bytes pack_hello_ack(const HelloAck& ack);
HelloAck unpack_hello_ack(std::span<const uint8_t> payload);

// ---------- AUTH ----------

struct Auth {
    std::array<uint8_t, 32> proof{};
    std::array<uint8_t, 16> client_id{};
    std::string client_name;
};

Bytes pack_auth(const Auth& auth);
Auth unpack_auth(std::span<const uint8_t> payload);
Bytes pack_auth_ok(uint8_t role, std::span<const uint8_t, 8> key_confirm, uint64_t server_ts_us);

// ---------- CAPS ----------

constexpr uint8_t kCapsRaw = 0;
constexpr uint8_t kCapsZstd = 1;
Bytes pack_caps_raw(std::span<const uint8_t> capability_json);

// ---------- CTRL ----------

struct Ctrl {
    uint8_t mode = 0;
    uint8_t flags = 0;
    std::vector<int16_t> axes;
    std::vector<uint32_t> buttons;
};

Bytes pack_ctrl(const Ctrl& ctrl);
Ctrl unpack_ctrl(std::span<const uint8_t> payload);

// ---------- TELEM ----------

struct Telemetry {
    uint32_t seq = 0;
    uint64_t ts_us = 0;
    uint32_t fsm_state = 0;
    uint32_t fault_flags = 0;
    uint8_t battery_pct = 0;
    float x = 0, y = 0, yaw = 0;
    std::vector<float> joint_q, joint_dq, joint_tau;
    std::vector<float> imu_quat, imu_gyro;
    std::string policy_name;
    uint32_t inference_us = 0, episode_len = 0, queue_depth = 0;
    uint32_t link_rtt_us = 0, link_loss_pct = 0, remote_age_ms = 0, map_revision = 0;
};

Bytes pack_telem(const Telemetry& t);

// ---------- MODEL_STATE ----------

struct ModelState {
    uint32_t seq = 0;
    uint64_t ts_us = 0;
    uint32_t joint_order_hash = 0;
    uint16_t joint_count = 0;
    uint8_t flags = 0;
    uint8_t frame_id = 0;
    std::array<float, 3> root_pos{};
    std::array<float, 4> root_quat{1, 0, 0, 0};
    std::vector<float> joint_pos;
    std::vector<float> joint_vel;
    std::vector<float> joint_eff;
};

Bytes pack_model_state(const ModelState& state);

// ---------- 发现 / 广播 ----------

Bytes pack_discover(std::span<const uint8_t, 16> app_nonce, std::span<const uint8_t, 16> app_id);

struct Announce {
    std::string robot_id;
    std::string robot_name;
    std::string form;
    uint16_t ctrl_port = 47800;
    uint16_t video_port = 47801;
    uint16_t depth_port = 47802;
    uint16_t map_port = 47803;
    uint16_t web_port = 47880;
    uint32_t caps_hash = 0;
    uint8_t pair_state = 0;
    uint16_t proto_major = 1;
    uint16_t proto_minor = 0;
};

Bytes pack_announce(const Announce& announce);
Announce unpack_announce(std::span<const uint8_t> data);

}  // namespace urc
