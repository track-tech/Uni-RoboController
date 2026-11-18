# ADR-0007 Agent 用 C++20 + GStreamer

- 状态：Accepted
- 日期：2026-11-18

## 背景

机器人端需硬件编码、相机采集、低开销网络、与 rl_sar/ROS 2 共存；平台覆盖 x86/RK/Jetson。

## 决定

- Agent 主进程 C++20 + CMake；媒体用 GStreamer（VAAPI/NVENC/MPP/NVMPI/V4L2 编码元素）。
- 协议/控制/遥测/地图为自研 C++ 模块；HTTP 用 cpp-httplib；日志 spdlog；配置 yaml-cpp。
- rl_sar 桥接作为补丁 + 本地回环 UDP；ROS 2 适配器可选（rclcpp）。

## 理由

- GStreamer 是 Linux 硬编/采集最成熟的方案，覆盖目标平台；C++ 满足实时与内存控制。
- 不链接厂商 SDK，保持适配器可插拔与许可证干净。

## 后果

- 需要 C++/GStreamer 维护能力；跨平台构建（aarch64 交叉编译/容器）需要 CI 投入。
- GStreamer 插件许可证需逐一核对（LGPL/第三方）。

## 备选

- Rust + gstreamer-rs（安全但生态/ROS 绑定较弱）。
- Python + GStreamer（开发快但实时/部署重）。
