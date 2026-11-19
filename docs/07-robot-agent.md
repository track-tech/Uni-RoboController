# 07 最小参考 Agent 与协议实现结构（示例，非生产）

> 本文描述**最小参考 Agent** 的模块划分与实现要点，同时作为第三方实现生产 Agent 的结构参考。
> 项目定位（B 方案）见 [ADR-0014](adr/0014-scope-app-protocol-cts.md)：生产 Agent 由厂商/社区按
> [18 实现指南](18-protocol-implementation-guide.md) 实现并通过 CTS；本项目只交付最小参考 Agent。
> 参考 Agent 负责：媒体（单相机）、控制、遥测、基础模型状态、管理接口；不包含多形态适配/
> rl_sar 补丁/完整 SLAM/点云地图（增强档由实现方按协议扩展）。

## 1. 职责边界（参考 Agent）

| 做 | 不做 |
|---|---|
| 单相机采集/编码/分片/发送 | 训练/推理策略（由 rl_sar 等外部部署框架负责） |
| 控制帧解析、校验、仲裁、看门狗 | 生产级多形态机器人适配（由实现方扩展） |
| 基础 MODEL_STATE + 模型包下发 | 完整深度/点云地图（v1.1 增强档） |
| 遥测采集与上报 | 云端账号/多租户 |
| 管理 HTTP、日志、健康检查 | 公网穿透/中继 |

## 2. 技术栈与构建

| 项 | 选择 |
|---|---|
| 语言 | C++20（异常安全、RAII；热路径避免分配） |
| 构建 | CMake ≥ 3.22；Conan/vcpkg 可选；**同一源码双架构**（x86_64 主机原生 + aarch64 交叉编译）；Docker 构建镜像 |
| 媒体 | GStreamer 1.22+（`appsrc`/`v4l2src`/编码器/`rtph264pay` 或自研 payloader） |
| 网络 | 原始 UDP socket + epoll；可选 `webrtcbin`（GStreamer ≥1.16 支持 data channel） |
| 序列化 | Protobuf（遥测/配置）；自定义小端二进制（控制/媒体头） |
| 加密 | OpenSSL 3.x（AES-GCM/HKDF/HMAC） |
| 压缩 | zstd（地图/深度/CAPS） |
| 日志 | spdlog（JSON 行格式，轮转） |
| 配置 | JSON（M0 mock/参考 Agent）；yaml-cpp（M1+ 生产配置可选） |
| HTTP | cpp-httplib（MIT） |
| 可选 | rclcpp（ROS 2 适配器）、rl_sar 补丁桥接 |

依赖许可证要求见 [12-open-source.md](12-open-source.md)；GStreamer 为 LGPL（动态链接）。

## 3. 进程与线程模型

```
main
├── session 线程（UDP 47800 epoll：控制/遥测/反馈/握手）
├── video TX（GStreamer 管线线程；硬编在插件内部）
├── depth TX / mapping 线程（有界队列；地图编码可丢弃旧帧）
├── telemetry 线程（20 Hz）
├── HTTP 线程（47880，独立，不阻塞实时路径）
├── recording 线程（磁盘 IO，独立；可选）
└── watchdog/health 线程（检测各模块心跳）
```

规则：

- 实时路径**不分配大块内存、不写磁盘、不做重计算**；使用预分配缓冲池与有界队列。
- 控制帧保留最近 N 帧（默认 8），过期丢弃；绝不排队重传。
- 媒体管线独立，崩溃可重启，不影响控制/遥测。
- 地图构建允许丢帧（以最新为准），但瓦片数据要完整（请求/响应 + 重传）。
- 所有线程有名字、心跳计数、最近错误码，供健康检查上报。

## 4. 媒体管线

- 由 YAML 描述：源 → 转换/缩放 → 编码 → 打包 → 传输；每段可替换。
- 编码器探测：启动时 `gst-inspect-1.0` 或运行时尝试创建，失败自动回退（硬编→软编）并告警。
- 管线重启：分辨率/帧率/编码器变更时整体重建，状态经 EVENT 上报。
- 低延迟：`queue max-size-buffers=1 leaky=downstream`；`sync=false`；编码器 `zerolatency`；
  MPP 用 `rc-mode=cbr gop=<2s帧数> max-reenc=0 zero-copy-pkt=true`（属性以板端 `gst-inspect` 为准）。
- 多相机：v1 一路 RGB + 一路深度；每路独立 `stream_id`。
- 采集源：V4L2（UVC/RealSense V4L2 节点）、ROS 2 `image_transport`（`appsrc`）、测试图（`videotestsrc`）。

## 5. 控制链

```
UDP 47800 → 解析/解密/校验 → 会话/角色检查 → 状态机检查
  → 适配器 apply_command()（仲裁：本地急停 > RC > 网络 > 自主）
  → 机器人侧安全层（限幅/斜率/看门狗）
  → 适配器输出（rl_sar 网络输入 / ROS 2 消息 / 自定义 MCU 帧）
```

- 控制线程 100–200 Hz；控制帧 TTL 200 ms；死手/急停语义见 09 文档。
- 适配器接口见 08 文档；rl_sar 桥接见 13 文档。
- 每个命令都记录：来源、seq、ts、是否被拒绝及原因（限速日志）。

## 6. 遥测

- 统一 `Telemetry` 结构（见协议 §7.5）：FSM/模式、命令回显、关节、IMU、位姿、
  策略/模型、推理耗时、链路、地图 revision、故障。
- 采集方式：适配器回调 / rl_sar 补丁状态帧 / ROS 2 订阅 / 设备 SDK。
- 20 Hz 默认；无数据时发“数据不可用”状态而不是旧值（带时间戳）。
- 关键事件（FSM 切换、急停、故障）用 EVENT 立即上报，不等遥测周期。

## 7. 地图与深度

- 深度：订阅源 → 降采样 → zstd → 分片发送（`stream=depth`）。
- 地图：体素哈希 → 脏块 → 4 m 瓦片编码（Morton + zstd）→ 瓦片缓存；
  仅响应 App 请求，限流（默认 8 个在途、200 KB/s）。
- 位姿来源：适配器提供（odom/外部 SLAM/ROS 2 TF）；无位姿时只做“实时深度点云”，不发地图。
- 地图 revision/map_id 管理；重启后可从磁盘恢复（可选）。

## 8. 配置（示例）

```yaml
robot:
  id: "l4w4-036"
  name: "L4W4"
  adapter: rl_sar            # 见 08 文档；或 ros2_base / custom / mock
  adapter_config: "/etc/urc/l4w4.yaml"
network:
  bind: "0.0.0.0"
  ctrl_port: 47800
  video_port: 0              # v1 单端口多流：0 表示复用 ctrl_port
  depth_port: 0
  map_port: 0
  http_port: 47880
  discovery: {mdns: true, broadcast: true}
  require_pairing: true
  encrypt_media: true
security:
  allowed_clients_file: "/etc/urc/clients.json"
  session_timeout_ms: 5000
  watchdog_ms: 300
media:
  rgb:
    source: v4l2             # v4l2 | ros2 | realsense | test
    device: "/dev/video0"
    width: 1280
    height: 720
    fps: 60
    encoder: auto            # auto | vah264enc | nvh264enc | mpph264enc | nvv4l2h264enc | x264enc
    codec: h264              # h264 | hevc
    bitrate_kbps: 10000
    gop: 120
    fec: {mode: xor, parity: 1, group: 8}
depth:
  enabled: true
  source: realsense
  width: 320
  height: 240
  fps: 12
  encoding: zstd
mapping:
  backend: internal_voxel    # none | internal_voxel | ros2_pointcloud
  voxel_size: 0.05
  tile_size: 4.0
  occupancy: true
  max_tiles_in_memory: 512
telemetry:
  rate_hz: 20
logging:
  level: info
  file: "/var/log/urc/agent.log"
recording:
  enabled: false
  dir: "/var/lib/urc/recordings"
  max_size_gb: 20
```

## 9. 管理 HTTP 与文件

- 端口 47880（仅局域网）；Bearer Token；接口清单见协议 §7.7。
- 文件下载支持 Range（录像/日志）；上传仅限配置/地图/模型等白名单类型与大小限制。
- 配置写入采用“校验 → 备份 → 原子替换 → 重启受影响模块”，失败回滚。
- 日志：JSON 行、轮转、包含模块/线程/错误码；敏感字段脱敏。

## 10. 平台与编码矩阵

| 平台 | 架构 | 编码元素 | 备注 |
|---|---|---|---|
| x86_64 + Intel/AMD | x86_64 | `vah264enc`/`vah265enc` | VAAPI；无头需 Xorg dummy/KMS |
| x86_64 + NVIDIA | x86_64 | `nvh264enc`/`nvh265enc` | NVENC；注意驱动/CUDA 依赖 |
| RK3588 / RK3576 | aarch64 | `mpph264enc`/`mpph265enc` | 无 B 帧；`max-reenc=0`/`zero-copy-pkt=true`/`rc-mode=cbr`（属性以板端为准） |
| RK3566 | aarch64 | `mpph264enc` | 仅 1080p30/60 单路，注意 CPU |
| Jetson | aarch64 | `nvv4l2h264enc`/`nvv4l2h265enc` | 按 JetPack 验证；Jetson 不走 NVENC |
| Raspberry Pi 4 | aarch64 | `v4l2h264enc` | V4L2 M2M；Pi 5 无 H.264 硬编 |
| 无硬编 | 双架构 | `x264enc tune=zerolatency` | 仅 720p30 兜底，必须告警 |

> 目标架构：**x86_64 与 aarch64（ARM64）双架构**，同一份 C++ 源码、同一套协议/向量；
> 均为小端；不支持 32 位 armv7（如需要另立 ADR）。CI 必须同时构建两种架构。

### 10.1 双架构构建与验证

> **M0 范围**：C++ mock/参考 Agent 仅做 POSIX（Linux）原生构建；aarch64 由 CI QEMU 容器验证；
> Windows 开发用 WSL/容器或 Python 参考服务端。完整交叉编译/发布物在 M2 引入；本节的交叉工具链
> 与双架构发布是 M2+ 目标，不是 M0 验收项。

- **工具链**：x86_64 用宿主原生构建；aarch64 用交叉工具链或 `--platform linux/arm64` 容器构建；
  CMake `CMAKE_TOOLCHAIN_FILE` + 依赖（OpenSSL/protobuf/GStreamer/zstd）交叉编译或使用目标板 sysroot。
- **CI**：`agent-x86_64` 原生构建 + ctest；`agent-aarch64` 在 QEMU arm64 容器构建并跑协议向量；
  媒体/GStreamer 相关用例在目标板（M2 起）跑。
- **运行时差异**：ARM 板卡注意页大小（4K/16K）、DMA-BUF 零拷贝、RGA 色彩转换、
  USB3 相机带宽与供电；x86 注意核显/独显驱动与 VAAPI 权限。
- **性能基线**：x86 与 ARM64 分别记录 720p30/1080p30 编码 CPU、延迟与内存；
  ARM 侧以 RK3588/Jetson 为基准平台，RK3566/Pi 标注为轻量档。
- **发布物**：`urc-agent` 提供 `amd64` 与 `arm64` 两种包（deb/rpm/容器镜像），同一版本号、同一配置格式。

## 11. 权限与运行环境

- systemd 单元（示例）：

```ini
[Unit]
Description=Uni-RoboController Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/urc/bin/urc-agent --config /etc/urc/agent.yaml
Restart=on-failure
RestartSec=2
User=urc
Group=urc
# 硬编/相机/视频设备
SupplementaryGroups=video render input
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/log/urc /var/lib/urc /run/urc

[Install]
WantedBy=multi-user.target
```

- 虚拟手柄模式需要 `/dev/uinput` 权限（`input` 组/udev 规则）；仅 L1 兼容模式需要。
- 网络端口绑定、防火墙规则；禁止暴露公网。
- Windows 开发：C++ mock/参考 Agent 仅 POSIX；推荐 WSL2 或容器构建运行；不使用 MSYS2 原生编译；
  仅做协议/CTS 联调时可直接用 `tools/codec_ref/ref_server.py`。
- 无头模式：Xorg dummy/Xvfb 或 KMS；仅媒体/地图不需要显示时可纯 headless（KMS 采集除外）。

## 12. 健康检查与故障恢复

- `/health` 返回：各模块心跳、队列深度、编码器/管线状态、最后错误、磁盘/内存/温度、
  会话数、看门狗状态、rl_sar 桥接状态。
- 故障恢复：
  - 媒体管线崩溃 → 重启管线（指数退避），控制不受影响；
  - 适配器/桥接断开 → 安全态 + 重连；
  - 配置错误 → 拒绝启动并保持安全态；
  - OOM/磁盘满 → 降级录制/日志，禁止影响控制。
- 启动顺序：配置校验 → 适配器初始化 → 安全态 → 传输就绪 → 媒体启动 → 接受会话。
- 升级/重启不得自动进入运动态（需显式 arm）。

## 13. 测试与故障注入钩子

- M0 mock/参考 Agent 的故障注入为**运行期 CLI 参数**（`--drop/--hold-next-ms/--corrupt-aead/--stale-state`）；
  编译期 `URC_FAULT_INJECT` 仅用于生产 Agent 测试构建（M2+），不替代运行期开关。
- `mock` 适配器 + `videotestsrc`/`fakesink` 可无硬件跑通全链路。
- 单元测试：协议编解码、FEC、重组、仲裁、看门狗、地图量化、配置校验。
- CI：x86 构建 + 单测；aarch64 交叉构建；容器内 `test-mode` 端到端。
