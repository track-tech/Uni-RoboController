// Copyright (c) 2026-2027 zbc
// URC 协议帧结构声明：32 B 帧头、消息类型与流定义。
#pragma once

#include <cstdint>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace urc {

constexpr uint32_t kMagic = 0x31435255;  // "URC1" little-endian
constexpr uint8_t kVersion = 1;
constexpr size_t kHeaderSize = 32;
constexpr size_t kMaxPayload = 1200;

enum MsgType : uint8_t {
    kHello = 0x01,
    kHelloAck = 0x02,
    kAuth = 0x03,
    kAuthOk = 0x04,
    kCaps = 0x05,
    kCtrl = 0x06,
    kTelem = 0x07,
    kFeedback = 0x08,
    kPing = 0x09,
    kPong = 0x0A,
    kEstop = 0x0B,
    kConfig = 0x0C,
    kConfigAck = 0x0D,
    kEvent = 0x0E,
    kError = 0x0F,
    kVideo = 0x10,
    kVideoFec = 0x11,
    kDepth = 0x12,
    kMapMeta = 0x13,
    kMapReq = 0x14,
    kMapTile = 0x15,
    kMapAck = 0x16,
    kSessionCtrl = 0x17,
    kTimeSync = 0x18,
    kModelState = 0x19,
    kDiscover = 0x20,
    kAnnounce = 0x21,
};

enum FrameFlags : uint8_t {
    kFlagEncrypted = 0x01,
    kFlagKeyframe = 0x02,
    kFlagFec = 0x04,
    kFlagLastFrag = 0x08,
    kFlagAckReq = 0x10,
    kFlagResend = 0x20,
};

enum Stream : uint8_t {
    kStreamCtrl = 0,
    kStreamTelemetry = 1,
    kStreamVideo = 2,
    kStreamDepth = 3,
    kStreamMap = 4,
    kStreamConfig = 5,
    kStreamFeedback = 6,
};

struct CryptoContext;

struct Frame {
    uint8_t type = 0;
    uint8_t flags = 0;
    uint8_t stream = kStreamCtrl;
    uint32_t session_id = 0;
    uint32_t seq = 0;
    uint64_t ts_us = 0;
    std::vector<uint8_t> payload;
};

// 打包/解包；加密时 to_robot/from_robot 决定方向子密钥与 nonce。
std::vector<uint8_t> pack_frame(const Frame& frame, const CryptoContext* ctx = nullptr, bool to_robot = true);
Frame unpack_frame(std::span<const uint8_t> data, const CryptoContext* ctx = nullptr, bool from_robot = false);

// 通用分片头。
constexpr size_t kFragHeaderSize = 8;

std::vector<std::vector<uint8_t>> fragment_payload(std::span<const uint8_t> payload, size_t mtu, uint32_t msg_id);
std::vector<uint8_t> make_fragment(uint32_t msg_id, uint16_t index, uint16_t count, std::span<const uint8_t> data);

class Reassembler {
public:
    static constexpr size_t kMaxConcurrent = 64;
    static constexpr size_t kMaxMessage = 8 * 1024 * 1024;

    // 返回完整消息时交付；缺片/重复/超限返回 nullopt。
    std::optional<std::vector<uint8_t>> add(std::span<const uint8_t> fragment);
    size_t pending() const { return slots_.size(); }

private:
    struct Slot {
        uint16_t count = 0;
        size_t received = 0;
        size_t total = 0;
        std::vector<std::vector<uint8_t>> parts;
        std::vector<bool> present;
    };
    std::map<uint32_t, Slot> slots_;
};

}  // namespace urc
