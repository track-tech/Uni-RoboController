// Copyright (c) 2026-2027 zbc
// 小端字节读写工具（协议内部使用）。
#pragma once

#include <cstdint>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

namespace urc::wire {

using Bytes = std::vector<uint8_t>;

inline void put_u8(Bytes& out, uint8_t v) { out.push_back(v); }
inline void put_u16(Bytes& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v));
    out.push_back(static_cast<uint8_t>(v >> 8));
}
inline void put_u32(Bytes& out, uint32_t v) {
    for (int i = 0; i < 4; ++i) out.push_back(static_cast<uint8_t>(v >> (8 * i)));
}
inline void put_u64(Bytes& out, uint64_t v) {
    for (int i = 0; i < 8; ++i) out.push_back(static_cast<uint8_t>(v >> (8 * i)));
}
inline void put_f32(Bytes& out, float v) {
    uint32_t bits;
    static_assert(sizeof(bits) == sizeof(v));
    __builtin_memcpy(&bits, &v, sizeof(bits));
    put_u32(out, bits);
}
inline void put_bytes(Bytes& out, std::span<const uint8_t> data) {
    out.insert(out.end(), data.begin(), data.end());
}

class Reader {
public:
    explicit Reader(std::span<const uint8_t> data) : data_(data) {}

    size_t remaining() const { return data_.size() - off_; }
    uint8_t u8() {
        need(1);
        return data_[off_++];
    }
    uint16_t u16() {
        need(2);
        uint16_t v = static_cast<uint16_t>(data_[off_]) | static_cast<uint16_t>(data_[off_ + 1]) << 8;
        off_ += 2;
        return v;
    }
    uint32_t u32() {
        need(4);
        uint32_t v = 0;
        for (int i = 0; i < 4; ++i) v |= static_cast<uint32_t>(data_[off_ + i]) << (8 * i);
        off_ += 4;
        return v;
    }
    uint64_t u64() {
        need(8);
        uint64_t v = 0;
        for (int i = 0; i < 8; ++i) v |= static_cast<uint64_t>(data_[off_ + i]) << (8 * i);
        off_ += 8;
        return v;
    }
    float f32() {
        uint32_t bits = u32();
        float v;
        __builtin_memcpy(&v, &bits, sizeof(v));
        return v;
    }
    std::span<const uint8_t> bytes(size_t n) {
        need(n);
        auto out = data_.subspan(off_, n);
        off_ += n;
        return out;
    }
    std::string str_u8() {
        auto n = u8();
        auto b = bytes(n);
        return std::string(reinterpret_cast<const char*>(b.data()), b.size());
    }

private:
    void need(size_t n) const {
        if (off_ + n > data_.size()) throw std::runtime_error("short buffer");
    }
    std::span<const uint8_t> data_;
    size_t off_ = 0;
};

}  // namespace urc::wire
