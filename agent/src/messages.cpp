// Copyright (c) 2026-2027 zbc
// 消息载荷编解码实现（与 Python 参考实现字节级一致）。
#include "urc/messages.h"

#include <cstring>
#include <stdexcept>

#include "urc/crc32c.h"
#include "urc/frame.h"
#include "urc/wire.h"

namespace urc {
namespace {

void put_varint(wire::Bytes& out, uint64_t value) {
    while (true) {
        uint8_t b = static_cast<uint8_t>(value & 0x7F);
        value >>= 7;
        if (value) b |= 0x80;
        out.push_back(b);
        if (!value) break;
    }
}

void put_tag(wire::Bytes& out, uint32_t field, uint32_t wire_type) {
    put_varint(out, (static_cast<uint64_t>(field) << 3) | wire_type);
}

void put_float_field(wire::Bytes& out, uint32_t field, float value) {
    put_tag(out, field, 5);
    wire::put_f32(out, value);
}

void put_packed_floats(wire::Bytes& out, uint32_t field, const std::vector<float>& values) {
    if (values.empty()) return;
    wire::Bytes data;
    data.reserve(values.size() * 4);
    for (float v : values) wire::put_f32(data, v);
    put_tag(out, field, 2);
    put_varint(out, data.size());
    wire::put_bytes(out, data);
}

void put_string_field(wire::Bytes& out, uint32_t field, const std::string& value) {
    put_tag(out, field, 2);
    put_varint(out, value.size());
    out.insert(out.end(), value.begin(), value.end());
}

}  // namespace

// ---------- HELLO ----------

Bytes pack_hello(const Hello& hello) {
    wire::Bytes out;
    wire::put_u16(out, hello.proto_major);
    wire::put_u16(out, hello.proto_minor);
    wire::put_u8(out, hello.role);
    wire::put_u16(out, hello.flags);
    wire::put_bytes(out, hello.app_id);
    wire::put_bytes(out, hello.app_nonce);
    if (hello.app_version.size() > 255) throw std::runtime_error("version too long");
    wire::put_u8(out, static_cast<uint8_t>(hello.app_version.size()));
    out.insert(out.end(), hello.app_version.begin(), hello.app_version.end());
    return out;
}

Hello unpack_hello(std::span<const uint8_t> payload) {
    wire::Reader r(payload);
    Hello hello;
    hello.proto_major = r.u16();
    hello.proto_minor = r.u16();
    hello.role = r.u8();
    hello.flags = r.u16();
    auto app_id = r.bytes(16);
    auto nonce = r.bytes(16);
    std::copy(app_id.begin(), app_id.end(), hello.app_id.begin());
    std::copy(nonce.begin(), nonce.end(), hello.app_nonce.begin());
    hello.app_version = r.str_u8();
    return hello;
}

// ---------- HELLO_ACK ----------

Bytes pack_hello_ack(const HelloAck& ack) {
    wire::Bytes out;
    wire::put_u16(out, ack.proto_major);
    wire::put_u16(out, ack.proto_minor);
    wire::put_u32(out, ack.session_id);
    for (const auto* s : {&ack.robot_id, &ack.robot_name, &ack.form}) {
        if (s->size() > 255) throw std::runtime_error("string too long");
        wire::put_u8(out, static_cast<uint8_t>(s->size()));
        out.insert(out.end(), s->begin(), s->end());
    }
    wire::put_bytes(out, ack.robot_nonce);
    wire::put_u32(out, ack.caps_hash);
    wire::put_u16(out, ack.ctrl_port);
    wire::put_u16(out, ack.video_port);
    wire::put_u16(out, ack.depth_port);
    wire::put_u16(out, ack.map_port);
    wire::put_u16(out, ack.web_port);
    wire::put_u8(out, ack.auth_required);
    return out;
}

HelloAck unpack_hello_ack(std::span<const uint8_t> payload) {
    wire::Reader r(payload);
    HelloAck ack;
    ack.proto_major = r.u16();
    ack.proto_minor = r.u16();
    ack.session_id = r.u32();
    ack.robot_id = r.str_u8();
    ack.robot_name = r.str_u8();
    ack.form = r.str_u8();
    auto nonce = r.bytes(16);
    std::copy(nonce.begin(), nonce.end(), ack.robot_nonce.begin());
    ack.caps_hash = r.u32();
    ack.ctrl_port = r.u16();
    ack.video_port = r.u16();
    ack.depth_port = r.u16();
    ack.map_port = r.u16();
    ack.web_port = r.u16();
    ack.auth_required = r.u8();
    return ack;
}

// ---------- AUTH ----------

Bytes pack_auth(const Auth& auth) {
    wire::Bytes out;
    wire::put_bytes(out, auth.proof);
    wire::put_bytes(out, auth.client_id);
    if (auth.client_name.size() > 255) throw std::runtime_error("name too long");
    wire::put_u8(out, static_cast<uint8_t>(auth.client_name.size()));
    out.insert(out.end(), auth.client_name.begin(), auth.client_name.end());
    return out;
}

Auth unpack_auth(std::span<const uint8_t> payload) {
    wire::Reader r(payload);
    Auth auth;
    auto proof = r.bytes(32);
    auto id = r.bytes(16);
    std::copy(proof.begin(), proof.end(), auth.proof.begin());
    std::copy(id.begin(), id.end(), auth.client_id.begin());
    auth.client_name = r.str_u8();
    return auth;
}

Bytes pack_auth_ok(uint8_t role, std::span<const uint8_t, 8> key_confirm, uint64_t server_ts_us) {
    wire::Bytes out;
    wire::put_u8(out, role);
    wire::put_bytes(out, key_confirm);
    wire::put_u64(out, server_ts_us);
    return out;
}

// ---------- CAPS ----------

Bytes pack_caps_raw(std::span<const uint8_t> capability_json) {
    wire::Bytes out;
    wire::put_u32(out, static_cast<uint32_t>(capability_json.size()));
    wire::put_u32(out, crc32c(capability_json));
    wire::put_u8(out, kCapsRaw);
    wire::put_bytes(out, capability_json);
    return out;
}

// ---------- CTRL ----------

Bytes pack_ctrl(const Ctrl& ctrl) {
    if (ctrl.axes.size() > 16 || (ctrl.buttons.size() != 1 && ctrl.buttons.size() != 2)) {
        throw std::runtime_error("bad ctrl fields");
    }
    wire::Bytes out;
    wire::put_u8(out, ctrl.mode);
    wire::put_u8(out, static_cast<uint8_t>(ctrl.axes.size()));
    wire::put_u8(out, static_cast<uint8_t>(ctrl.buttons.size()));
    wire::put_u8(out, ctrl.flags);
    for (int16_t v : ctrl.axes) wire::put_u16(out, static_cast<uint16_t>(v));
    for (uint32_t v : ctrl.buttons) wire::put_u32(out, v);
    return out;
}

Ctrl unpack_ctrl(std::span<const uint8_t> payload) {
    wire::Reader r(payload);
    Ctrl ctrl;
    ctrl.mode = r.u8();
    auto axis_count = r.u8();
    auto button_words = r.u8();
    ctrl.flags = r.u8();
    ctrl.axes.resize(axis_count);
    for (auto& v : ctrl.axes) v = static_cast<int16_t>(r.u16());
    ctrl.buttons.resize(button_words);
    for (auto& v : ctrl.buttons) v = r.u32();
    return ctrl;
}

// ---------- TELEM ----------

Bytes pack_telem(const Telemetry& t) {
    wire::Bytes out;
    for (const auto& [field, value] : std::initializer_list<std::pair<uint32_t, uint64_t>>{
             {1, t.seq}, {2, t.ts_us}, {3, t.fsm_state}, {4, t.fault_flags}, {5, t.battery_pct}}) {
        put_tag(out, field, 0);
        put_varint(out, value);
    }
    put_float_field(out, 6, t.x);
    put_float_field(out, 7, t.y);
    put_float_field(out, 8, t.yaw);
    put_packed_floats(out, 9, t.joint_q);
    put_packed_floats(out, 10, t.joint_dq);
    put_packed_floats(out, 11, t.joint_tau);
    put_packed_floats(out, 12, t.imu_quat);
    put_packed_floats(out, 13, t.imu_gyro);
    if (!t.policy_name.empty()) put_string_field(out, 14, t.policy_name);
    for (const auto& [field, value] : std::initializer_list<std::pair<uint32_t, uint64_t>>{
             {15, t.inference_us}, {16, t.episode_len}, {17, t.queue_depth}, {18, t.link_rtt_us},
             {19, t.link_loss_pct}, {20, t.remote_age_ms}, {21, t.map_revision}}) {
        put_tag(out, field, 0);
        put_varint(out, value);
    }
    return out;
}

// ---------- MODEL_STATE ----------

Bytes pack_model_state(const ModelState& state) {
    if (state.joint_pos.size() != state.joint_count) throw std::runtime_error("joint count mismatch");
    wire::Bytes out;
    wire::put_u32(out, state.seq);
    wire::put_u64(out, state.ts_us);
    wire::put_u32(out, state.joint_order_hash);
    wire::put_u16(out, state.joint_count);
    wire::put_u8(out, state.flags);
    wire::put_u8(out, state.frame_id);
    for (float v : state.root_pos) wire::put_f32(out, v);
    for (float v : state.root_quat) wire::put_f32(out, v);
    for (float v : state.joint_pos) wire::put_f32(out, v);
    if (state.flags & 0x01) {
        for (float v : state.joint_vel) wire::put_f32(out, v);
    }
    if (state.flags & 0x02) {
        for (float v : state.joint_eff) wire::put_f32(out, v);
    }
    return out;
}

// ---------- 发现 ----------

Bytes pack_discover(std::span<const uint8_t, 16> app_nonce, std::span<const uint8_t, 16> app_id) {
    wire::Bytes out;
    wire::put_u32(out, kMagic);
    wire::put_u8(out, 1);
    wire::put_u8(out, kDiscover);
    wire::put_u8(out, 0);
    wire::put_u8(out, 0);
    wire::put_bytes(out, app_nonce);
    wire::put_bytes(out, app_id);
    wire::put_u32(out, crc32c(out));
    return out;
}

Bytes pack_announce(const Announce& announce) {
    wire::Bytes out;
    wire::put_u32(out, kMagic);
    wire::put_u8(out, 1);
    wire::put_u8(out, kAnnounce);
    wire::put_u8(out, 0);
    wire::put_u8(out, 0);
    wire::put_u8(out, 0);
    for (const auto* s : {&announce.robot_id, &announce.robot_name, &announce.form}) {
        if (s->size() > 255) throw std::runtime_error("string too long");
        wire::put_u8(out, static_cast<uint8_t>(s->size()));
        out.insert(out.end(), s->begin(), s->end());
    }
    wire::put_u16(out, announce.ctrl_port);
    wire::put_u16(out, announce.video_port);
    wire::put_u16(out, announce.depth_port);
    wire::put_u16(out, announce.map_port);
    wire::put_u16(out, announce.web_port);
    wire::put_u32(out, announce.caps_hash);
    wire::put_u8(out, announce.pair_state);
    wire::put_u16(out, announce.proto_major);
    wire::put_u16(out, announce.proto_minor);
    wire::put_u32(out, crc32c(out));
    return out;
}

Announce unpack_announce(std::span<const uint8_t> data) {
    if (data.size() < 4 + 1 + 1 + 1 + 1 + 1 + 4) throw std::runtime_error("short announce");
    wire::Reader r(data);
    if (r.u32() != kMagic) throw std::runtime_error("bad announce magic");
    if (r.u8() != 1) throw std::runtime_error("bad announce version");
    if (r.u8() != kAnnounce) throw std::runtime_error("bad announce type");
    r.u8();
    r.u8();
    r.u8();
    Announce a;
    a.robot_id = r.str_u8();
    a.robot_name = r.str_u8();
    a.form = r.str_u8();
    a.ctrl_port = r.u16();
    a.video_port = r.u16();
    a.depth_port = r.u16();
    a.map_port = r.u16();
    a.web_port = r.u16();
    a.caps_hash = r.u32();
    a.pair_state = r.u8();
    a.proto_major = r.u16();
    a.proto_minor = r.u16();
    uint32_t crc = r.u32();
    if (crc32c(data.first(data.size() - 4)) != crc) throw std::runtime_error("bad announce crc");
    return a;
}

}  // namespace urc
