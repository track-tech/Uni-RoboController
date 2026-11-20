// Copyright (c) 2026-2027 zbc
// mock_robot 命令行入口：解析参数、安装信号处理并运行 C++ mock 服务端。
#include <atomic>
#include <csignal>
#include <iostream>
#include <string>

#include "urc/mock_server.h"

namespace {

std::atomic<bool> g_stop{false};

void on_signal(int) { g_stop.store(true); }

void usage() {
    std::cout << "Usage: mock_robot [options]\n"
                 "  --bind ADDR              bind address (default 0.0.0.0)\n"
                 "  --ctrl-port PORT         control port (default 47800)\n"
                 "  --discovery-port PORT    discovery port (default 47810)\n"
                 "  --web-port PORT          advertised web port (default 47880)\n"
                 "  --capability PATH        capability JSON\n"
                 "  --secret-file PATH       secret file (32 bytes; generated if absent)\n"
                 "  --stats-file PATH        stats JSON (atomic, every 500ms)\n"
                 "  --no-camera              disable VIDEO test pattern\n"
                 "  --stale-state            stop MODEL_STATE\n"
                 "  --drop PERCENT           drop outbound datagrams\n"
                 "  --hold-next-ms MS        hold next inbound CTRL before TTL check\n"
                 "  --corrupt-aead PERCENT   corrupt outbound ciphertext (CRC fixed)\n"
                 "  --seed N                 deterministic injection seed\n"
                 "  --watchdog-ms MS         watchdog timeout (default 300)\n"
                 "  --ctrl-ttl-ms MS         control TTL (default 200)\n"
                 "  --session-timeout-ms MS  session timeout (default 5000)\n"
                 "  --verbose                verbose logs\n"
                 "  --help                   show this help\n";
}

}  // namespace

int main(int argc, char** argv) {
    urc::MockConfig config;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto next = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "missing value for " << name << std::endl;
                std::exit(2);
            }
            return argv[++i];
        };
        try {
            if (arg == "--bind") config.bind = next("--bind");
            else if (arg == "--ctrl-port") config.ctrl_port = static_cast<uint16_t>(std::stoi(next("--ctrl-port")));
            else if (arg == "--discovery-port") config.discovery_port = static_cast<uint16_t>(std::stoi(next("--discovery-port")));
            else if (arg == "--web-port") config.web_port = static_cast<uint16_t>(std::stoi(next("--web-port")));
            else if (arg == "--capability") config.capability = next("--capability");
            else if (arg == "--secret-file") config.secret_file = next("--secret-file");
            else if (arg == "--stats-file") config.stats_file = next("--stats-file");
            else if (arg == "--no-camera") config.no_camera = true;
            else if (arg == "--stale-state") config.stale_state = true;
            else if (arg == "--drop") config.drop = std::stod(next("--drop"));
            else if (arg == "--hold-next-ms") config.hold_next_ms = std::stoi(next("--hold-next-ms"));
            else if (arg == "--corrupt-aead") config.corrupt_aead = std::stod(next("--corrupt-aead"));
            else if (arg == "--seed") config.seed = static_cast<uint32_t>(std::stoul(next("--seed")));
            else if (arg == "--watchdog-ms") config.watchdog_ms = std::stoi(next("--watchdog-ms"));
            else if (arg == "--ctrl-ttl-ms") config.ctrl_ttl_ms = std::stoi(next("--ctrl-ttl-ms"));
            else if (arg == "--session-timeout-ms") config.session_timeout_ms = std::stoi(next("--session-timeout-ms"));
            else if (arg == "--verbose") config.verbose = true;
            else if (arg == "--help" || arg == "-h") {
                usage();
                return 0;
            } else {
                std::cerr << "unknown option: " << arg << std::endl;
                usage();
                return 2;
            }
        } catch (const std::exception& exc) {
            std::cerr << "bad argument " << arg << ": " << exc.what() << std::endl;
            return 2;
        }
    }
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);
    try {
        urc::MockServer server(config);
        server.set_stop_flag(&g_stop);
        return server.run();
    } catch (const std::exception& exc) {
        std::cerr << "mock_robot failed: " << exc.what() << std::endl;
        return 1;
    }
}
