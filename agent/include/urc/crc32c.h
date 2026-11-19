// Copyright (c) 2026-2027 zbc
// CRC-32/ISCSI（Castagnoli）：反射多项式 0x82F63B78，init/xorout=0xFFFFFFFF。
#pragma once

#include <cstddef>
#include <cstdint>
#include <span>

namespace urc {

uint32_t crc32c(std::span<const uint8_t> data);
uint32_t crc32c_update(uint32_t crc, std::span<const uint8_t> data);

}  // namespace urc
