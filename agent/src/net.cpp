// Copyright (c) 2026-2027 zbc
// POSIX UDP 实现（Linux 为权威平台；Windows 开发用 WSL/容器或 Python ref）。
#include "urc/net.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <stdexcept>

namespace urc::net {

namespace {

sockaddr_in make_sockaddr(const Address& address) {
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(address.port);
    addr.sin_addr.s_addr = htonl(address.ip);
    return addr;
}

}  // namespace

std::string Address::to_string() const {
    in_addr a{};
    a.s_addr = htonl(ip);
    char buf[INET_ADDRSTRLEN] = {};
    inet_ntop(AF_INET, &a, buf, sizeof(buf));
    return std::string(buf) + ":" + std::to_string(port);
}

UdpSocket::~UdpSocket() { close(); }

bool UdpSocket::open(const std::string& bind_addr, uint16_t port) {
    close();
    fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd_ < 0) return false;
    int yes = 1;
    ::setsockopt(fd_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (inet_pton(AF_INET, bind_addr.c_str(), &addr.sin_addr) != 1) {
        close();
        return false;
    }
    if (::bind(fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        close();
        return false;
    }
    int flags = ::fcntl(fd_, F_GETFL, 0);
    if (flags < 0 || ::fcntl(fd_, F_SETFL, flags | O_NONBLOCK) < 0) {
        close();
        return false;
    }
    return true;
}

void UdpSocket::close() {
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

std::optional<Datagram> UdpSocket::recv() {
    if (fd_ < 0) return std::nullopt;
    Datagram out;
    out.data.resize(4096);
    sockaddr_in from{};
    socklen_t len = sizeof(from);
    ssize_t n = ::recvfrom(fd_, out.data.data(), out.data.size(), 0,
                           reinterpret_cast<sockaddr*>(&from), &len);
    if (n < 0) return std::nullopt;
    out.data.resize(static_cast<size_t>(n));
    out.from.ip = ntohl(from.sin_addr.s_addr);
    out.from.port = ntohs(from.sin_port);
    return out;
}

bool UdpSocket::send(const Address& to, std::span<const uint8_t> data) {
    if (fd_ < 0) return false;
    auto addr = make_sockaddr(to);
    return ::sendto(fd_, data.data(), data.size(), 0,
                    reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) ==
           static_cast<ssize_t>(data.size());
}

int select_readable(std::initializer_list<int> fds, int timeout_ms) {
    fd_set set;
    FD_ZERO(&set);
    int max_fd = -1;
    for (int fd : fds) {
        if (fd < 0) continue;
        FD_SET(fd, &set);
        if (fd > max_fd) max_fd = fd;
    }
    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    int rc = ::select(max_fd + 1, &set, nullptr, nullptr, &tv);
    if (rc < 0 && errno == EINTR) return 0;
    return rc;
}

uint64_t now_us() {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
}

uint64_t now_ms() { return now_us() / 1000; }

}  // namespace urc::net
