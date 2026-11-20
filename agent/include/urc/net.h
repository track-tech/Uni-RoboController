// Copyright (c) 2026-2027 zbc
// POSIX UDP 抽象：绑定、非阻塞收发、select 等待与单调时钟。
#pragma once

#include <cstdint>
#include <initializer_list>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace urc::net {

struct Address {
    uint32_t ip = 0;      // host order
    uint16_t port = 0;

    bool operator==(const Address& other) const = default;
    uint64_t key() const { return (static_cast<uint64_t>(ip) << 16) | port; }
    std::string to_string() const;
};

struct Datagram {
    Address from;
    std::vector<uint8_t> data;
};

class UdpSocket {
public:
    UdpSocket() = default;
    ~UdpSocket();
    UdpSocket(const UdpSocket&) = delete;
    UdpSocket& operator=(const UdpSocket&) = delete;

    bool open(const std::string& bind_addr, uint16_t port);
    void close();
    bool valid() const { return fd_ >= 0; }
    int fd() const { return fd_; }

    std::optional<Datagram> recv();
    bool send(const Address& to, std::span<const uint8_t> data);

private:
    int fd_ = -1;
};

// 返回可读 fd 数量；0 表示超时，<0 表示错误。
int select_readable(std::initializer_list<int> fds, int timeout_ms);

uint64_t now_us();
uint64_t now_ms();

}  // namespace urc::net
