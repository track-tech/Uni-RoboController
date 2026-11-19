// Copyright (c) 2026-2027 zbc
// 帧打包/解包、加密帧处理与通用分片重组。
#include "urc/frame.h"

#include <algorithm>
#include <cstring>
#include <stdexcept>

#include "urc/crc32c.h"
#include "urc/crypto.h"
#include "urc/wire.h"

namespace urc {
namespace {

wire::Bytes build_header(uint8_t type, uint8_t flags, uint8_t stream, uint32_t session_id,
                         uint32_t seq, uint64_t ts_us, uint16_t payload_len) {
    wire::Bytes out;
    out.reserve(kHeaderSize);
    wire::put_u32(out, kMagic);
    wire::put_u8(out, kVersion);
    wire::put_u8(out, type);
    wire::put_u8(out, flags);
    wire::put_u8(out, stream);
    wire::put_u32(out, session_id);
    wire::put_u32(out, seq);
    wire::put_u64(out, ts_us);
    wire::put_u16(out, payload_len);
    wire::put_u16(out, 0);  // reserved
    wire::put_u32(out, 0);  // crc 占位
    return out;
}

void write_u32_at(wire::Bytes& buf, size_t off, uint32_t v) {
    for (int i = 0; i < 4; ++i) buf[off + i] = static_cast<uint8_t>(v >> (8 * i));
}

uint32_t read_u16(std::span<const uint8_t> data, size_t off) {
    return static_cast<uint32_t>(data[off]) | static_cast<uint32_t>(data[off + 1]) << 8;
}

uint32_t read_u32(std::span<const uint8_t> data, size_t off) {
    uint32_t v = 0;
    for (int i = 0; i < 4; ++i) v |= static_cast<uint32_t>(data[off + i]) << (8 * i);
    return v;
}

}  // namespace

std::vector<uint8_t> pack_frame(const Frame& frame, const CryptoContext* ctx, bool to_robot) {
    if (frame.payload.size() > kMaxPayload) throw std::runtime_error("payload too large");
    uint8_t flags = frame.flags;
    if (ctx) flags |= kFlagEncrypted;
    auto header = build_header(frame.type, flags, frame.stream, frame.session_id, frame.seq,
                               frame.ts_us, static_cast<uint16_t>(frame.payload.size()));
    std::vector<uint8_t> body;
    if (ctx) {
        auto nonce = CryptoContext::make_nonce(frame.seq, to_robot);
        const auto& key = to_robot ? ctx->app2robot_key : ctx->robot2app_key;
        body = aes_gcm_encrypt(key, nonce, header, frame.payload);
    } else {
        body = frame.payload;
    }
    auto crc_input = header;
    crc_input.insert(crc_input.end(), body.begin(), body.end());
    write_u32_at(header, 28, crc32c(crc_input));
    header.insert(header.end(), body.begin(), body.end());
    return header;
}

Frame unpack_frame(std::span<const uint8_t> data, const CryptoContext* ctx, bool from_robot) {
    if (data.size() < kHeaderSize) throw std::runtime_error("short frame");
    if (read_u32(data, 0) != kMagic) throw std::runtime_error("bad magic");
    if (data[4] != kVersion) throw std::runtime_error("bad version");
    Frame frame;
    frame.type = data[5];
    frame.flags = data[6];
    frame.stream = data[7];
    frame.session_id = read_u32(data, 8);
    frame.seq = read_u32(data, 12);
    uint64_t ts = 0;
    for (int i = 0; i < 8; ++i) ts |= static_cast<uint64_t>(data[16 + i]) << (8 * i);
    frame.ts_us = ts;
    uint16_t payload_len = static_cast<uint16_t>(read_u16(data, 24));
    bool encrypted = (frame.flags & kFlagEncrypted) != 0;
    auto body = data.subspan(kHeaderSize);
    if (encrypted) {
        if (body.size() != static_cast<size_t>(payload_len) + kTagLen) throw std::runtime_error("bad encrypted length");
    } else if (body.size() != payload_len) {
        throw std::runtime_error("bad length");
    }
    auto header0 = data.subspan(0, kHeaderSize);
    wire::Bytes zeroed(header0.begin(), header0.end());
    write_u32_at(zeroed, 28, 0);
    auto crc_input = zeroed;
    crc_input.insert(crc_input.end(), body.begin(), body.end());
    if (crc32c(crc_input) != read_u32(data, 28)) throw std::runtime_error("bad crc");
    if (encrypted) {
        if (!ctx) throw std::runtime_error("encrypted frame requires context");
        auto nonce = CryptoContext::make_nonce(frame.seq, !from_robot);
        const auto& key = from_robot ? ctx->robot2app_key : ctx->app2robot_key;
        frame.payload = aes_gcm_decrypt(key, nonce, zeroed, body);
    } else {
        frame.payload.assign(body.begin(), body.end());
    }
    return frame;
}

std::vector<uint8_t> make_fragment(uint32_t msg_id, uint16_t index, uint16_t count,
                                   std::span<const uint8_t> data) {
    std::vector<uint8_t> out;
    out.reserve(kFragHeaderSize + data.size());
    wire::put_u32(out, msg_id);
    wire::put_u16(out, index);
    wire::put_u16(out, count);
    wire::put_bytes(out, data);
    return out;
}

std::vector<std::vector<uint8_t>> fragment_payload(std::span<const uint8_t> payload, size_t mtu,
                                                   uint32_t msg_id) {
    if (mtu <= kFragHeaderSize) throw std::runtime_error("mtu too small");
    size_t chunk = mtu - kFragHeaderSize;
    size_t count = payload.empty() ? 1 : (payload.size() + chunk - 1) / chunk;
    std::vector<std::vector<uint8_t>> out;
    out.reserve(count);
    for (size_t i = 0; i < count; ++i) {
        auto part = payload.subspan(i * chunk, std::min(chunk, payload.size() - i * chunk));
        out.push_back(make_fragment(msg_id, static_cast<uint16_t>(i), static_cast<uint16_t>(count), part));
    }
    return out;
}

std::optional<std::vector<uint8_t>> Reassembler::add(std::span<const uint8_t> fragment) {
    if (fragment.size() < kFragHeaderSize) return std::nullopt;
    uint32_t msg_id = 0;
    for (int i = 0; i < 4; ++i) msg_id |= static_cast<uint32_t>(fragment[i]) << (8 * i);
    uint16_t index = static_cast<uint16_t>(fragment[4] | fragment[5] << 8);
    uint16_t count = static_cast<uint16_t>(fragment[6] | fragment[7] << 8);
    if (count == 0 || index >= count) return std::nullopt;
    auto it = slots_.find(msg_id);
    if (it == slots_.end()) {
        if (slots_.size() >= kMaxConcurrent) return std::nullopt;
        Slot slot;
        slot.count = count;
        slot.parts.resize(count);
        slot.present.assign(count, false);
        it = slots_.emplace(msg_id, std::move(slot)).first;
    }
    auto& slot = it->second;
    if (slot.count != count) {
        slots_.erase(it);
        return std::nullopt;
    }
    if (slot.present[index]) return std::nullopt;
    auto data = fragment.subspan(kFragHeaderSize);
    slot.parts[index].assign(data.begin(), data.end());
    slot.present[index] = true;
    slot.received++;
    slot.total += data.size();
    if (slot.total > kMaxMessage) {
        slots_.erase(it);
        return std::nullopt;
    }
    if (slot.received != slot.count) return std::nullopt;
    std::vector<uint8_t> out;
    out.reserve(slot.total);
    for (auto& part : slot.parts) out.insert(out.end(), part.begin(), part.end());
    slots_.erase(it);
    return out;
}

}  // namespace urc
