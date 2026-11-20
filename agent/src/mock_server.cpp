// Copyright (c) 2026-2027 zbc
// C++ mock 服务端实现：发现/认证/会话/控制/遥测/模型/视频/看门狗/急停/注入。
#include "urc/mock_server.h"

#include <openssl/evp.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <thread>

#include "nlohmann/json.hpp"
#include "urc/crc32c.h"
#include "urc/wire.h"

namespace urc {

namespace {

constexpr uint16_t kEvtEstopAcked = 0x0001;
constexpr uint16_t kEvtWatchdog = 0x0002;
constexpr uint16_t kEvtArmed = 0x0003;
constexpr uint16_t kEvtSessionExpired = 0x0004;
constexpr uint16_t kEvtEstopReleased = 0x0005;
constexpr uint16_t kErrAuth = 0x0101;
constexpr uint16_t kErrSession = 0x0102;
constexpr uint16_t kErrRole = 0x0103;
constexpr uint16_t kErrRange = 0x0301;
constexpr uint16_t kErrEstop = 0x0302;
constexpr uint16_t kErrLocked = 0x0602;

std::array<uint8_t, 32> sha256(std::span<const uint8_t> data) {
    std::array<uint8_t, 32> out{};
    unsigned int len = 0;
    EVP_Digest(data.data(), data.size(), out.data(), &len, EVP_sha256(), nullptr);
    return out;
}

std::vector<uint8_t> random_bytes(size_t n, std::mt19937& rng) {
    std::vector<uint8_t> out(n);
    for (auto& b : out) b = static_cast<uint8_t>(rng() & 0xFF);
    return out;
}

std::string base64(std::span<const uint8_t> data) {
    std::string out;
    out.resize(4 * ((data.size() + 2) / 3) + 1);
    int n = EVP_EncodeBlock(reinterpret_cast<unsigned char*>(out.data()), data.data(),
                            static_cast<int>(data.size()));
    out.resize(static_cast<size_t>(n));
    return out;
}

uint64_t monotonic_ms() { return net::now_ms(); }

}  // namespace

MockServer::MockServer(MockConfig config) : config_(std::move(config)) {
    std::string error;
    if (!load_capability(error)) throw std::runtime_error(error);
    if (!load_secret()) throw std::runtime_error("secret init failed");
    if (!ctrl_.open(config_.bind, config_.ctrl_port)) throw std::runtime_error("bind ctrl failed");
    if (!discovery_.open(config_.bind, config_.discovery_port)) throw std::runtime_error("bind discovery failed");
    axes_.assign(cap_.channels.size(), 0.0f);
    hold_next_ms_ = config_.hold_next_ms;
    std::mt19937 seed_rng(config_.seed ? config_.seed : 0xC0FFEEu);
    rng_state_ = seed_rng();
    if (rng_state_ == 0) rng_state_ = 1;
}

MockServer::~MockServer() {
    write_stats();
    ctrl_.close();
    discovery_.close();
}

uint32_t MockServer::next_random() {
    rng_state_ ^= rng_state_ << 13;
    rng_state_ ^= rng_state_ >> 17;
    rng_state_ ^= rng_state_ << 5;
    return rng_state_;
}

bool MockServer::load_capability(std::string& error) {
    std::ifstream in(config_.capability);
    if (!in) {
        error = "cannot open capability: " + config_.capability;
        return false;
    }
    nlohmann::json j;
    try {
        in >> j;
    } catch (const std::exception& exc) {
        error = std::string("bad capability json: ") + exc.what();
        return false;
    }
    cap_.robot_id = j.value("robot_id", "mock-quadruped");
    cap_.name = j.value("name", "Mock Robot");
    cap_.form = j.value("form", "quadruped");
    cap_.canonical_json = j.dump();
    auto digest = sha256(std::span<const uint8_t>(
        reinterpret_cast<const uint8_t*>(cap_.canonical_json.data()), cap_.canonical_json.size()));
    cap_.caps_hash = static_cast<uint32_t>(digest[0]) | static_cast<uint32_t>(digest[1]) << 8 |
                     static_cast<uint32_t>(digest[2]) << 16 | static_cast<uint32_t>(digest[3]) << 24;
    cap_.joint_order.clear();
    if (j.contains("model") && j["model"].contains("joint_order")) {
        for (const auto& name : j["model"]["joint_order"]) cap_.joint_order.push_back(name.get<std::string>());
    }
    std::string joined;
    for (size_t i = 0; i < cap_.joint_order.size(); ++i) {
        if (i) joined.push_back('\n');
        joined += cap_.joint_order[i];
    }
    cap_.joint_hash = crc32c(std::span<const uint8_t>(
        reinterpret_cast<const uint8_t*>(joined.data()), joined.size()));
    cap_.channels.clear();
    const auto& mode = j["control"]["modes"][0];
    for (const auto& ch : mode["channels"]) {
        Channel c;
        c.id = ch.value("id", "");
        c.lo = ch["range"][0].get<float>();
        c.hi = ch["range"][1].get<float>();
        c.scale = ch.contains("scale") ? ch["scale"].get<float>() : std::max(std::abs(c.lo), std::abs(c.hi));
        cap_.channels.push_back(c);
    }
    return true;
}

bool MockServer::load_secret() {
    std::mt19937 rng(static_cast<uint32_t>(std::random_device{}()));
    auto bytes = random_bytes(32, rng);
    std::memcpy(secret_.data(), bytes.data(), secret_.size());
    if (config_.secret_file.empty()) {
        std::cout << "URCPAIR:" << base64(secret_) << std::endl;
        return true;
    }
    std::ifstream in(config_.secret_file, std::ios::binary);
    if (in) {
        std::vector<char> buf((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
        if (buf.size() != 32) return false;
        std::memcpy(secret_.data(), buf.data(), 32);
        std::cout << "[mock] loaded secret from " << config_.secret_file << std::endl;
        return true;
    }
    std::ofstream out(config_.secret_file, std::ios::binary);
    if (!out) return false;
    out.write(reinterpret_cast<const char*>(secret_.data()), secret_.size());
    out.close();
    std::cout << "URCPAIR:" << base64(secret_) << std::endl;
    return true;
}

// ---------- send ----------

bool MockServer::drop_or_corrupt(std::vector<uint8_t>& raw) {
    if (config_.drop > 0 && (next_random() % 10000) < config_.drop * 100) {
        ++stats_.dropped_tx;
        return false;
    }
    if (config_.corrupt_aead > 0 && has_ctx_ &&
        (next_random() % 10000) < config_.corrupt_aead * 100) {
        if (raw.size() > 48) {
            size_t idx = 32 + (next_random() % (raw.size() - 48));
            raw[idx] ^= 0xFF;
            std::vector<uint8_t> crc_input(raw.begin(), raw.begin() + 28);
            crc_input.insert(crc_input.end(), raw.begin() + 32, raw.end());
            auto crc = crc32c(crc_input);
            raw[28] = static_cast<uint8_t>(crc);
            raw[29] = static_cast<uint8_t>(crc >> 8);
            raw[30] = static_cast<uint8_t>(crc >> 16);
            raw[31] = static_cast<uint8_t>(crc >> 24);
            ++stats_.corrupt_tx;
        }
    }
    return true;
}

void MockServer::send(uint8_t type, std::span<const uint8_t> payload, uint8_t flags, uint8_t stream,
                      std::optional<net::Address> to, bool encrypt) {
    net::Address target = to.value_or(peer_);
    if (!to.has_value() && !has_peer_) return;
    Frame frame;
    frame.type = type;
    frame.flags = flags;
    frame.stream = stream;
    frame.session_id = session_id_;
    frame.seq = ++tx_seq_;
    frame.ts_us = net::now_us();
    frame.payload.assign(payload.begin(), payload.end());
    auto raw = pack_frame(frame, (encrypt && has_ctx_) ? &ctx_ : nullptr, false);
    if (!drop_or_corrupt(raw)) return;
    if (ctrl_.send(target, raw)) ++stats_.tx_frames;
}

void MockServer::send_error(uint16_t code, const std::string& message,
                            std::optional<net::Address> to, bool rate_limit) {
    net::Address target = to.value_or(peer_);
    if (!to.has_value() && !has_peer_) return;
    if (rate_limit) {
        uint64_t now = monotonic_ms();
        auto& times = error_times_[target.key()];
        times.erase(std::remove_if(times.begin(), times.end(),
                                   [now](uint64_t t) { return now - t > 1000; }),
                    times.end());
        if (times.size() >= 2) return;
        times.push_back(now);
    }
    ErrorMsg err{code, message};
    bool encrypt = has_peer_ && target == peer_ && authenticated_ && has_ctx_;
    auto payload = pack_error(err);
    send(kError, payload, 0, kStreamCtrl, target, encrypt);
}

void MockServer::send_event(uint16_t code, uint8_t level, const std::string& message) {
    if (!authenticated_) return;
    Event ev{code, level, message};
    send(kEvent, pack_event(ev));
}

void MockServer::send_caps() {
    auto payload = pack_caps_raw(std::span<const uint8_t>(
        reinterpret_cast<const uint8_t*>(cap_.canonical_json.data()), cap_.canonical_json.size()));
    auto parts = fragment_payload(payload, 1190, 0x1000);
    for (size_t i = 0; i < parts.size(); ++i) {
        send(kCaps, parts[i], i + 1 == parts.size() ? kFlagLastFrag : 0, kStreamConfig);
    }
}

void MockServer::send_telem() {
    Telemetry t;
    t.seq = ++telem_seq_;
    t.ts_us = net::now_us();
    t.fsm_state = estop_latched_ ? 2 : (armed_ ? 1 : 0);
    t.fault_flags = (watchdog_fired_ ? 1u : 0u) | (estop_latched_ ? 2u : 0u);
    t.battery_pct = 88;
    t.x = axes_.size() > 0 ? axes_[0] : 0.0f;
    t.y = axes_.size() > 1 ? axes_[1] : 0.0f;
    t.yaw = axes_.size() > 2 ? axes_[2] : 0.0f;
    t.policy_name = "mock";
    t.remote_age_ms = last_ctrl_ms_ ? static_cast<uint32_t>(monotonic_ms() - last_ctrl_ms_) : 9999;
    send(kTelem, pack_telem(t), 0, kStreamTelemetry);
}

void MockServer::send_model() {
    if (cap_.joint_order.empty()) return;
    ModelState s;
    s.seq = ++model_seq_;
    s.ts_us = net::now_us();
    s.joint_order_hash = cap_.joint_hash;
    s.joint_count = static_cast<uint16_t>(cap_.joint_order.size());
    s.flags = 0x04;
    s.root_pos = {0.0f, 0.0f, 0.3f};
    s.root_quat = {1.0f, 0.0f, 0.0f, 0.0f};
    double t = static_cast<double>(net::now_us()) / 1e6;
    s.joint_pos.resize(cap_.joint_order.size());
    for (size_t i = 0; i < s.joint_pos.size(); ++i) {
        s.joint_pos[i] = static_cast<float>(0.2 * std::sin(t * 2.0 + static_cast<double>(i)));
    }
    send(kModelState, pack_model_state(s), 0, kStreamTelemetry);
}

void MockServer::send_video() {
    constexpr int w = 160, h = 120;
    std::vector<uint8_t> data(static_cast<size_t>(w) * h * 3);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            size_t o = (static_cast<size_t>(y) * w + x) * 3;
            data[o] = static_cast<uint8_t>(x * 255 / w);
            data[o + 1] = static_cast<uint8_t>(y * 255 / h);
            data[o + 2] = 128;
        }
    }
    const size_t chunk = 1190 - 23;
    size_t count = (data.size() + chunk - 1) / chunk;
    ++video_frame_id_;
    for (size_t i = 0; i < count; ++i) {
        size_t off = i * chunk;
        size_t n = std::min(chunk, data.size() - off);
        VideoHeader vh;
        vh.frame_id = video_frame_id_;
        vh.frame_ts_us = net::now_us();
        vh.frame_bytes = static_cast<uint32_t>(data.size());
        vh.pkt_idx = static_cast<uint16_t>(i);
        vh.pkt_cnt = static_cast<uint16_t>(count);
        vh.media_flags = 0x01 | (i + 1 == count ? 0x04 : 0);
        auto payload = pack_video(vh, std::span<const uint8_t>(data.data() + off, n));
        send(kVideo, payload, kFlagKeyframe, kStreamVideo);
    }
}

// ---------- receive ----------

void MockServer::handle_discovery(const net::Datagram& datagram) {
    const auto& data = datagram.data;
    if (data.size() < 41) return;
    if (data[0] != 0x55 || data[1] != 0x52 || data[2] != 0x43 || data[3] != 0x31) return;
    if (data[5] != kDiscover) return;
    uint32_t crc = static_cast<uint32_t>(data[data.size() - 4]) |
                   static_cast<uint32_t>(data[data.size() - 3]) << 8 |
                   static_cast<uint32_t>(data[data.size() - 2]) << 16 |
                   static_cast<uint32_t>(data[data.size() - 1]) << 24;
    if (crc32c(std::span<const uint8_t>(data.data(), data.size() - 4)) != crc) return;
    Announce ann;
    ann.robot_id = cap_.robot_id;
    ann.robot_name = cap_.name;
    ann.form = cap_.form;
    ann.ctrl_port = config_.ctrl_port;
    ann.video_port = 0;
    ann.depth_port = 0;
    ann.map_port = 0;
    ann.web_port = config_.web_port;
    ann.caps_hash = cap_.caps_hash;
    ann.pair_state = authenticated_ ? 1 : 0;
    auto raw = pack_announce(ann);
    discovery_.send(datagram.from, raw);
}

void MockServer::handle_datagram(const net::Datagram& datagram) {
    ++stats_.rx_frames;
    const auto& data = datagram.data;
    if (data.size() < kHeaderSize || data[0] != 0x55 || data[1] != 0x52 || data[2] != 0x43 || data[3] != 0x31) {
        ++stats_.rx_drop;
        return;
    }
    bool encrypted = (data[6] & kFlagEncrypted) != 0;
    try {
        if (!encrypted) {
            auto frame = unpack_frame(data);
            if (frame.type == kHello || frame.type == kAuth) {
                handle_plain(frame, datagram.from);
            } else {
                ++stats_.gate_drop;
            }
            return;
        }
        if (!authenticated_ || !has_ctx_ || datagram.from != peer_) {
            ++stats_.gate_drop;
            return;
        }
        auto frame = unpack_frame(data, &ctx_, false);
        if (!client_replay_.accept(frame.seq)) {
            ++stats_.replay_drop;
            return;
        }
        last_rx_ms_ = monotonic_ms();
        if (frame.type == kCtrl && hold_next_ms_ > 0) {
            uint64_t recv_ms = monotonic_ms();
            std::this_thread::sleep_for(std::chrono::milliseconds(hold_next_ms_));
            hold_next_ms_ = 0;
            if (static_cast<int>(monotonic_ms() - recv_ms) > config_.ctrl_ttl_ms) {
                ++stats_.ttl_dropped;
                return;
            }
        }
        handle_encrypted(frame, datagram.from);
    } catch (const std::exception&) {
        if (encrypted) {
            ++stats_.aead_fail;
        } else {
            ++stats_.rx_drop;
        }
    }
}

void MockServer::handle_plain(const Frame& frame, const net::Address& from) {
    if (frame.type == kHello) {
        on_hello(frame, from);
    } else if (frame.type == kAuth) {
        on_auth(frame, from);
    }
}

void MockServer::on_hello(const Frame& frame, const net::Address& from) {
    if (claimed_ && (!has_peer_ || !(peer_ == from))) {
        send_error(kErrRole, "controller occupied", from, false);
        return;
    }
    Hello hello;
    try {
        hello = unpack_hello(frame.payload);
    } catch (const std::exception&) {
        return;
    }
    reset_session(true);
    has_peer_ = true;
    peer_ = from;
    pending_ = true;
    pending_since_ms_ = monotonic_ms();
    session_id_ = next_random();
    app_nonce_ = hello.app_nonce;
    auto rng = std::mt19937(next_random());
    auto rn = random_bytes(16, rng);
    std::memcpy(robot_nonce_.data(), rn.data(), robot_nonce_.size());
    ctx_ = CryptoContext::derive(secret_, app_nonce_, robot_nonce_);
    has_ctx_ = true;
    HelloAck ack;
    ack.session_id = session_id_;
    ack.robot_id = cap_.robot_id;
    ack.robot_name = cap_.name;
    ack.form = cap_.form;
    ack.robot_nonce = robot_nonce_;
    ack.caps_hash = cap_.caps_hash;
    ack.ctrl_port = config_.ctrl_port;
    ack.video_port = 0;
    ack.depth_port = 0;
    ack.map_port = 0;
    ack.web_port = config_.web_port;
    ack.auth_required = 1;
    send(kHelloAck, pack_hello_ack(ack), 0, kStreamCtrl, from, false);
}

void MockServer::on_auth(const Frame& frame, const net::Address& from) {
    uint64_t now = monotonic_ms();
    auto locked = lock_until_ms_.find(from.key());
    if (locked != lock_until_ms_.end() && now < locked->second) {
        send_error(kErrLocked, "auth locked", from, false);
        return;
    }
    if (!pending_ || !has_peer_ || !(peer_ == from) || frame.session_id != session_id_) {
        send_error(kErrSession, "no pending session", from, false);
        return;
    }
    Auth auth;
    try {
        auth = unpack_auth(frame.payload);
    } catch (const std::exception&) {
        return;
    }
    auto want = auth_proof(secret_, app_nonce_, robot_nonce_, session_id_);
    if (std::memcmp(auth.proof.data(), want.data(), want.size()) != 0) {
        ++stats_.auth_fail;
        uint32_t& count = auth_failures_[from.key()];
        ++count;
        if (count >= 5) {
            lock_until_ms_[from.key()] = now + 30000;
            ++stats_.lockout;
        }
        send_error(kErrAuth, "auth failed", from, false);
        return;
    }
    authenticated_ = true;
    pending_ = false;
    auth_failures_.erase(from.key());
    last_rx_ms_ = now;
    send(kAuthOk, pack_auth_ok(0, ctx_.key_confirm, net::now_us()), 0, kStreamCtrl, from, false);
}

void MockServer::handle_encrypted(const Frame& frame, const net::Address& from) {
    if (!(from == peer_)) {
        ++stats_.gate_drop;
        return;
    }
    switch (frame.type) {
        case kSessionCtrl: on_session_ctrl(frame); break;
        case kCtrl: on_ctrl(frame); break;
        case kEstop: on_estop(frame); break;
        case kPing: on_ping(frame); break;
        case kFeedback: break;
        default: ++stats_.invalid_ctrl; break;
    }
}

bool MockServer::is_controller(const net::Address& from) const {
    return claimed_ && has_peer_ && peer_ == from;
}

void MockServer::on_session_ctrl(const Frame& frame) {
    uint8_t action = 0;
    try {
        action = unpack_session_ctrl(frame.payload);
    } catch (const std::exception&) {
        return;
    }
    switch (action) {
        case kActClaim:
            if (claimed_) {
                send_error(kErrRole, "controller occupied");
                return;
            }
            claimed_ = true;
            armed_ = false;
            send_caps();
            break;
        case kActRelease:
            if (!is_controller(peer_)) return;
            claimed_ = false;
            armed_ = false;
            std::fill(axes_.begin(), axes_.end(), 0.0f);
            break;
        case kActViewer:
            send_error(kErrRole, "viewer not implemented");
            break;
        case kActArm:
            if (!claimed_) {
                send_error(kErrRole, "claim required");
                return;
            }
            if (estop_latched_) {
                send_error(kErrEstop, "estop latched");
                return;
            }
            armed_ = true;
            watchdog_fired_ = false;
            last_ctrl_ms_ = monotonic_ms();
            send_event(kEvtArmed, 0, "armed");
            break;
        case kActReleaseEstop:
            estop_latched_ = false;
            armed_ = false;
            watchdog_fired_ = false;
            std::fill(axes_.begin(), axes_.end(), 0.0f);
            send_event(kEvtEstopReleased, 0, "estop released");
            break;
        default:
            send_error(kErrRange, "bad session action");
            break;
    }
}

void MockServer::on_ctrl(const Frame& frame) {
    if (!claimed_ || !armed_ || estop_latched_) {
        ++stats_.invalid_ctrl;
        std::fill(axes_.begin(), axes_.end(), 0.0f);
        return;
    }
    Ctrl ctrl;
    try {
        ctrl = unpack_ctrl(frame.payload);
    } catch (const std::exception&) {
        ++stats_.invalid_ctrl;
        return;
    }
    if (ctrl.axes.size() != cap_.channels.size()) {
        ++stats_.invalid_ctrl;
        send_error(kErrRange, "bad axis count");
        return;
    }
    if ((ctrl.flags & 0x01) == 0) {
        std::fill(axes_.begin(), axes_.end(), 0.0f);
        last_ctrl_ms_ = monotonic_ms();
        return;
    }
    std::vector<float> values(ctrl.axes.size());
    for (size_t i = 0; i < ctrl.axes.size(); ++i) {
        const auto& ch = cap_.channels[i];
        float physical = static_cast<float>(ctrl.axes[i]) / 32767.0f * ch.scale;
        if (physical < ch.lo - 1e-3f || physical > ch.hi + 1e-3f) {
            ++stats_.invalid_ctrl;
            send_error(kErrRange, "axis " + ch.id + " out of range");
            return;
        }
        values[i] = physical;
    }
    axes_ = values;
    buttons_[0] = static_cast<uint16_t>(ctrl.buttons.size() > 0 ? ctrl.buttons[0] & 0xFFFF : 0);
    last_ctrl_ms_ = monotonic_ms();
    watchdog_fired_ = false;
}

void MockServer::on_estop(const Frame& frame) {
    Estop estop;
    try {
        estop = unpack_estop(frame.payload);
    } catch (const std::exception&) {
        return;
    }
    if (estop.reason == 0) return;
    estop_latched_ = true;
    ++stats_.estop;
    armed_ = false;
    watchdog_fired_ = false;
    std::fill(axes_.begin(), axes_.end(), 0.0f);
    send_event(kEvtEstopAcked, 0, "estop acked");
}

void MockServer::on_ping(const Frame& frame) {
    uint64_t echo = 0;
    try {
        echo = unpack_ping(frame.payload);
    } catch (const std::exception&) {
        return;
    }
    send(kPong, pack_pong(echo));
}

// ---------- state/timers ----------

void MockServer::reset_session(bool keep_estop) {
    has_peer_ = false;
    pending_ = false;
    authenticated_ = false;
    claimed_ = false;
    armed_ = false;
    session_id_ = 0;
    has_ctx_ = false;
    client_replay_ = ReplayWindow(2048);
    std::fill(axes_.begin(), axes_.end(), 0.0f);
    if (!keep_estop) estop_latched_ = false;
    watchdog_fired_ = false;
}

void MockServer::tick() {
    uint64_t now = monotonic_ms();
    if (pending_ && now - pending_since_ms_ > static_cast<uint64_t>(config_.session_timeout_ms)) {
        pending_ = false;
        has_peer_ = false;
        session_id_ = 0;
        has_ctx_ = false;
    }
    if (authenticated_ && now - last_rx_ms_ > static_cast<uint64_t>(config_.session_timeout_ms)) {
        send_event(kEvtSessionExpired, 1, "session expired");
        ++stats_.sessions_expired;
        reset_session(true);
    }
    if (armed_ && now - last_ctrl_ms_ > static_cast<uint64_t>(config_.watchdog_ms)) {
        armed_ = false;
        watchdog_fired_ = true;
        ++stats_.watchdog;
        std::fill(axes_.begin(), axes_.end(), 0.0f);
        send_event(kEvtWatchdog, 1, "watchdog: zero speed");
    }
    if (authenticated_) {
        if (now >= next_telem_ms_) {
            next_telem_ms_ = now + 50;
            send_telem();
        }
        if (now >= next_model_ms_ && !config_.stale_state) {
            next_model_ms_ = now + 33;
            send_model();
        }
        if (now >= next_video_ms_ && !config_.no_camera) {
            next_video_ms_ = now + 100;
            send_video();
        }
    }
    if (!config_.stats_file.empty() && now >= next_stats_ms_) {
        next_stats_ms_ = now + 500;
        write_stats();
    }
}

// ---------- stats ----------

void MockServer::write_stats() {
    if (config_.stats_file.empty()) return;
    nlohmann::json j = {
        {"rx_frames", stats_.rx_frames}, {"tx_frames", stats_.tx_frames},
        {"rx_drop", stats_.rx_drop}, {"gate_drop", stats_.gate_drop},
        {"auth_fail", stats_.auth_fail}, {"lockout", stats_.lockout},
        {"replay_drop", stats_.replay_drop}, {"aead_fail", stats_.aead_fail},
        {"ttl_dropped", stats_.ttl_dropped}, {"invalid_ctrl", stats_.invalid_ctrl},
        {"watchdog", stats_.watchdog}, {"estop", stats_.estop},
        {"sessions_expired", stats_.sessions_expired}, {"dropped_tx", stats_.dropped_tx},
        {"corrupt_tx", stats_.corrupt_tx},
        {"session", {{"authenticated", authenticated_}, {"claimed", claimed_}, {"armed", armed_},
                     {"estop_latched", estop_latched_}, {"pending", pending_}}},
    };
    std::string tmp = config_.stats_file + ".tmp";
    std::ofstream out(tmp);
    if (!out) return;
    out << j.dump();
    out.close();
    std::rename(tmp.c_str(), config_.stats_file.c_str());
}

// ---------- main loop ----------

int MockServer::run() {
    std::cout << "[mock] ctrl=" << config_.bind << ":" << config_.ctrl_port
              << " discovery=" << config_.discovery_port << " caps_hash=0x" << std::hex
              << cap_.caps_hash << std::dec << " joints=" << cap_.joint_order.size() << std::endl;
    write_stats();
    next_telem_ms_ = next_model_ms_ = next_video_ms_ = next_stats_ms_ = monotonic_ms();
    while (!stop_ || !stop_->load()) {
        int rc = net::select_readable({ctrl_.fd(), discovery_.fd()}, 2);
        if (rc > 0) {
            while (auto datagram = ctrl_.recv()) handle_datagram(*datagram);
            while (auto datagram = discovery_.recv()) handle_discovery(*datagram);
        }
        tick();
    }
    write_stats();
    std::cout << "[mock] bye" << std::endl;
    return 0;
}

}  // namespace urc
