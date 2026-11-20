// Copyright (c) 2026-2027 zbc
// C++ mock 服务端：协议/安全语义与 Python 参考实现一致，供 App/CTS 开发。
#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "urc/crypto.h"
#include "urc/frame.h"
#include "urc/messages.h"
#include "urc/net.h"

namespace urc {

struct MockConfig {
    std::string bind = "0.0.0.0";
    uint16_t ctrl_port = 47800;
    uint16_t discovery_port = 47810;
    uint16_t web_port = 47880;
    std::string capability = "protocol/examples/capability.mock_quadruped.json";
    std::string secret_file;
    std::string stats_file;
    bool no_camera = false;
    bool stale_state = false;
    bool verbose = false;
    double drop = 0.0;
    double corrupt_aead = 0.0;
    int hold_next_ms = 0;
    uint32_t seed = 0;
    int watchdog_ms = 300;
    int ctrl_ttl_ms = 200;
    int session_timeout_ms = 5000;
};

struct Channel {
    std::string id;
    float lo = 0;
    float hi = 0;
    float scale = 0;
};

struct Capability {
    std::string robot_id;
    std::string name;
    std::string form;
    std::string canonical_json;
    uint32_t caps_hash = 0;
    uint32_t joint_hash = 0;
    std::vector<std::string> joint_order;
    std::vector<Channel> channels;
    std::vector<uint8_t> mode_ids;
    int video_w = 160;
    int video_h = 120;
    int video_fps = 10;
};

struct MockStats {
    uint64_t rx_frames = 0, tx_frames = 0, rx_drop = 0, gate_drop = 0, auth_fail = 0;
    uint64_t lockout = 0, replay_drop = 0, aead_fail = 0, ttl_dropped = 0;
    uint64_t invalid_ctrl = 0, watchdog = 0, estop = 0, sessions_expired = 0;
    uint64_t dropped_tx = 0, corrupt_tx = 0;
};

class MockServer {
public:
    explicit MockServer(MockConfig config);
    ~MockServer();
    MockServer(const MockServer&) = delete;
    MockServer& operator=(const MockServer&) = delete;

    int run();

private:
    // ---------- setup ----------
    bool load_capability(std::string& error);
    bool load_secret();

    // ---------- send ----------
    void send(uint8_t type, std::span<const uint8_t> payload, uint8_t flags = 0,
              uint8_t stream = kStreamCtrl, std::optional<net::Address> to = std::nullopt,
              bool encrypt = true);
    void send_error(uint16_t code, const std::string& message,
                    std::optional<net::Address> to = std::nullopt, bool rate_limit = true);
    void send_event(uint16_t code, uint8_t level, const std::string& message);
    void send_caps();
    void send_telem();
    void send_model();
    void send_video();

    // ---------- receive ----------
    void handle_datagram(const net::Datagram& datagram);
    void handle_discovery(const net::Datagram& datagram);
    void handle_plain(const Frame& frame, const net::Address& from);
    void handle_encrypted(const Frame& frame, const net::Address& from);
    void on_hello(const Frame& frame, const net::Address& from);
    void on_auth(const Frame& frame, const net::Address& from);
    void on_session_ctrl(const Frame& frame);
    void on_ctrl(const Frame& frame);
    void on_estop(const Frame& frame);
    void on_ping(const Frame& frame);

    // ---------- state ----------
    void reset_session(bool keep_estop);
    bool is_controller(const net::Address& from) const;
    void tick();

    // ---------- stats ----------
    void write_stats();
    bool drop_or_corrupt(std::vector<uint8_t>& raw);

    MockConfig config_;
    Capability cap_;
    net::UdpSocket ctrl_;
    net::UdpSocket discovery_;
    std::array<uint8_t, kSecretLen> secret_{};
    CryptoContext ctx_{};
    bool has_ctx_ = false;

    net::Address peer_{};
    bool has_peer_ = false;
    bool pending_ = false;
    bool authenticated_ = false;
    bool claimed_ = false;
    bool armed_ = false;
    bool estop_latched_ = false;
    uint32_t session_id_ = 0;
    std::array<uint8_t, kNonceLen> app_nonce_{};
    std::array<uint8_t, kNonceLen> robot_nonce_{};
    uint64_t pending_since_ms_ = 0;
    uint64_t last_rx_ms_ = 0;
    uint64_t last_ctrl_ms_ = 0;
    ReplayWindow client_replay_{2048};
    bool replay_initialized_ = false;
    uint32_t tx_seq_ = 0;

    std::map<uint64_t, uint32_t> auth_failures_;
    std::map<uint64_t, uint64_t> lock_until_ms_;
    std::map<uint64_t, std::vector<uint64_t>> error_times_;
    std::map<uint64_t, std::vector<uint64_t>> hello_times_;
    std::vector<uint64_t> announce_times_;

    std::vector<float> axes_;
    std::array<uint16_t, 2> buttons_{};
    bool watchdog_fired_ = false;
    uint32_t telem_seq_ = 0;
    uint32_t model_seq_ = 0;
    uint32_t video_frame_id_ = 0;
    uint64_t next_telem_ms_ = 0;
    uint64_t next_model_ms_ = 0;
    uint64_t next_video_ms_ = 0;
    uint64_t next_stats_ms_ = 0;
    int hold_next_ms_ = 0;
    MockStats stats_;
    uint32_t rng_state_ = 0;
    std::atomic<bool>* stop_ = nullptr;

public:
    void set_stop_flag(std::atomic<bool>* flag) { stop_ = flag; }
    const Capability& capability() const { return cap_; }
    uint32_t next_random();
};

}  // namespace urc
