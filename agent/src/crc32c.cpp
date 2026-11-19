// Copyright (c) 2026-2027 zbc
// CRC-32/ISCSI（Castagnoli）实现。
#include "urc/crc32c.h"

#include <array>

namespace urc {
namespace {
constexpr uint32_t kPoly = 0x82F63B78;

const std::array<uint32_t, 256>& table() {
    static const std::array<uint32_t, 256> t = [] {
        std::array<uint32_t, 256> out{};
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t crc = i;
            for (int j = 0; j < 8; ++j) crc = (crc & 1) ? (crc >> 1) ^ kPoly : crc >> 1;
            out[i] = crc;
        }
        return out;
    }();
    return t;
}
}  // namespace

uint32_t crc32c_update(uint32_t crc, std::span<const uint8_t> data) {
    for (uint8_t b : data) crc = table()[(crc ^ b) & 0xFF] ^ (crc >> 8);
    return crc;
}

uint32_t crc32c(std::span<const uint8_t> data) { return crc32c_update(0xFFFFFFFFu, data) ^ 0xFFFFFFFFu; }

}  // namespace urc
