# 01 总体架构

## 1. 设计原则

1. **控制与媒体分离**：控制/遥测走小包低延迟通道；视频/深度/地图走大流量通道；互不阻塞。
2. **能力描述驱动**：机器人自描述能力，App 动态生成控制界面；新增机器人不需要改 App。
3. **热路径自己掌控**：控制帧与视频分片用自定义二进制协议；配置/遥测用可演进的结构化格式。
4. **每一层可替换**：传输（UDP/WebRTC）、媒体源、编码器、渲染器、地图后端、适配器均为插件式接口。
5. **安全优先**：机器人侧独立看门狗与急停；App 只是“建议者”，不是安全边界。
6. **可测试**：mock 服务端 + CTS + 可回放抓包，保证无硬件也能开发与验收。

### 1.1 交付边界（B 方案）

- 本项目交付：**Android App + 协议 + CTS + mock + 最小参考 Agent + 工具**。
- 机器人端生产实现由厂商/社区按 [18 实现指南](18-protocol-implementation-guide.md) 完成；
  本项目不维护生产级多形态 Agent、rl_sar 补丁与完整 SLAM/点云实现。
- 参考 Agent 只做“基础档最小闭环”，用于联调与示范；CTS 是第三方实现的验收门槛。
- App 不是安全边界：看门狗/急停/限位/仲裁由机器人端实现，CTS P0 安全组把关。

## 2. 组件总览

### 2.1 Android App

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `core-protocol` | 帧编解码、消息模型、版本协商、加密 | `ProtocolCodec`、`Message` |
| `core-transport` | UDP 实时通道、发现、配对、会话管理；预留 WebRTC | `Transport`、`Session`、`Discovery` |
| `core-media` | 视频/深度接收、抖动缓冲、MediaCodec 解码、Surface 输出 | `MediaReceiver`、`VideoDecoder`、`DepthReceiver` |
| `core-map` | 地图元数据、瓦片请求/缓存、点云/栅格渲染（GLES/Filament） | `MapRepository`、`CloudRenderer` |
| `core-model` | URDF 模型包下载/缓存/解析、关节树、根位姿/关节插值、机器人 3D 渲染 | `ModelBundle`、`RobotModel`、`ModelState` |
| `core-gamepad` | 手柄发现、多手柄槽位、映射引擎、虚拟手柄、震动 | `GamepadManager`、`MappingEngine` |
| `core-robot` | 能力模型、命令构建、遥测状态、状态机镜像 | `Capability`、`CommandBuilder`、`RobotState` |
| `feature-connect` | 发现列表、扫码、手动连接、配对 | Compose |
| `feature-control` | 全屏视频、摇杆/按钮、HUD、急停 | Compose |
| `feature-map` | 点云/栅格视图、图层、测量、保存 | Compose + GLES |
| `feature-settings` | 视频/深度/地图/手柄/网络设置、日志 | Compose |
| `app` | 单 Activity、导航、前台服务、权限 | `RobotControlService` |

### 2.2 服务端：mock + 最小参考 Agent（示例）

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `session` | 发现、握手、认证、能力下发、会话生命周期 | `SessionManager` |
| `transport` | UDP 收发、分片/重组、FEC、拥塞反馈、加密 | `ITransport`、`PacketWriter/Reader` |
| `media` | GStreamer 管线：采集→转换→编码→打包→发送 | `MediaPipeline`、`IEncoderBackend` |
| `control` | 控制帧解析、校验、看门狗、死手、状态机 | `ControlPipeline` |
| `telemetry` | 机器人状态采集、聚合、限频发送 | `TelemetryCollector` |
| `mapping` | 深度→点云、体素地图、占据栅格、瓦片编码 | `VoxelMap`、`MapTileEncoder` |
| `model` | URDF 模型包存储/下发、URDF 解析（限位/树）、状态映射 | `ModelStore`、`ModelState` |
| `adapters` | 机器人适配器注册表与插件：rl_sar 桥接、ROS 2、自定义 MCU、Mock | `IRobotAdapter` |
| `http` | 管理接口：配置、日志、文件、录像、健康检查 | REST `/api/v1/*` |
| `recording` | 视频/遥测/深度/命令录制与导出 | `Recorder` |
| `util` | 日志、配置、时钟、缓冲区池、统计 | — |

> 上表是**最小参考 Agent/mock** 的模块划分，也是第三方实现的参考结构；
> 生产 Agent 可裁剪/扩展（多形态、ROS 2、rl_sar 等由实现方自行添加）。
> `conformance/`（CTS）与 `tools/codec_ref` 是独立测试组件，见 [18](18-protocol-implementation-guide.md)。

### 2.3 一致性测试（CTS）

| 模块 | 职责 |
|---|---|
| `conformance/cts` | 以“客户端”身份连接被测服务端，验证发现/配对/会话/控制/遥测/视频/模型/安全 |
| `conformance/static` | capability Schema、测试向量、文档/协议一致性 |
| `tools/codec_ref` | Python 参考编解码，生成向量并做差分测试 |

## 3. 进程与线程模型

### 3.1 服务端（单进程，多线程；mock/参考 Agent）

```
main
├── session/control RX 线程（UDP 47800/epoll，非阻塞）
├── video TX 线程（GStreamer 管线线程，硬编在 GStreamer 内部）
├── depth/map TX 线程（地图构建 + 瓦片编码，有界队列）
├── telemetry 线程（20 Hz 定时）
├── HTTP 线程（独立监听，避免阻塞实时路径）
└── recording 线程（可选，独立磁盘 IO）
```

原则：

- 实时路径**不分配大内存、不写磁盘、不做重计算**；全部使用预分配缓冲池。
- 地图构建可丢弃旧帧；控制帧绝不允许排队过深（保留最近 N 帧，过期丢弃）。
- 加密/校验在独立小核上做也行；先保证正确性，后续用 `SO_REUSEPORT`/绑核优化。

### 3.2 App（单 Activity + 前台服务）

```
RobotControlService（前台服务，持有 Session）
├── transport 线程：收包/分包/解密
├── video 解码：MediaCodec 异步回调 + 渲染 Surface
├── depth 解码线程
├── map 下载/重组线程
├── gamepad/mapping（主线程事件 + 独立采样定时器）
└── UI（Compose）：只消费 StateFlow，不阻塞网络线程
```

- 渲染：视频 `SurfaceView` 由 MediaCodec 直接输出；点云用独立 `GLSurfaceView`/EGL 线程，叠放在视频层之上。
- 会话生命周期由前台服务持有，Activity 旋转/切后台不打断流。

## 4. 数据流

### 4.1 控制（App → Robot，100 Hz）

```
手柄事件/虚拟摇杆 → GamepadManager → 统一 GamepadState → MappingEngine
  → 通道映射（Capability 的 control_layout）→ ControlFrame → AES-GCM → UDP 47800
  → Agent 控制解析 → 校验/限幅 → 看门狗刷新 → Adapter.apply_command()
  → rl_sar 桥接（x/y/yaw + FSM 按键）/ ROS 2 cmd_vel / 自定义 MCU 协议
```

> 注意：v1 不链接任何厂商 SDK。rl_sar 机型（如 L4W4）通过“网络遥控注入补丁 + 状态回传”
> 接入，详见 [13-rl-sar-bridge.md](13-rl-sar-bridge.md)；其内部仍由 rl_sar 负责与机器人 MCU/SDK 通信。

控制帧 24–64 字节；每帧重复发送 2 次（2–3 ms 间隔）提高抗丢包；不做重传排队。

### 4.2 视频（Robot → App）

```
相机 → GStreamer 采集/转换 NV12 → 硬件编码 H.264（CBR/无 B 帧/低延迟）
  → 分片（MTU 1200）→ XOR FEC → UDP 47801
  → App 抖动缓冲 → MediaCodec 硬解 → SurfaceView
App 每 50 ms 回传 Feedback（丢包/码率建议/关键帧请求）→ Agent 自适应码率
```

### 4.3 深度（Robot → App）

```
深度相机/ROS 2 深度话题 → 降采样/量化 → Zstd 压缩 → UDP 47802
  → App 深度伪彩显示；同时用内参在 GPU 反投影生成实时点云
```

### 4.4 点云地图（Robot → App，按需拉取）

```
深度 + 位姿（里程计/SLAM）→ 体素哈希（默认 5 cm）→ 脏块 → 4 m 瓦片
  → 量化 + 排序 + Zstd → 瓦片缓冲（Agent）
App 按视锥/区域请求瓦片 → UDP 47803 → 缓存/渲染；2D 占据栅格同步下发
```

### 4.5 管理（App ↔ Agent，HTTP 47880）

```
GET  /api/v1/info|caps|config|logs|files|health
GET  /api/v1/model/<hash>.zip            # 下载 URDF 模型包
POST /api/v1/model                       # 管理员上传模型包（校验哈希/格式）
PUT  /api/v1/config
POST /api/v1/record/start|stop ; /api/v1/map/save|load ; /api/v1/reboot
```

### 4.6 模型状态同步（Robot → App，30–50 Hz）

```
适配器/SDK 状态 → ModelState(根位姿 + 关节角/速度/力矩) → MODEL_STATE(0x19) → UDP 47800
  → App core-model：按 capability.joint_order 映射 → 插值 → URDF 关节树 → 3D 渲染
```

模型包（URDF→glb+json）走 HTTP 下载，按哈希缓存；模型渲染与视频/点云在同一 3D 场景或独立视图，
模型缺失/不匹配时控制不受影响。

## 5. 协议分层

```
应用层：控制 / 遥测 / 视频 / 深度 / 地图 / 模型状态 / 配置
消息层：32 字节统一帧头（magic/ver/type/flags/stream/seq/ts/len/crc）+ 载荷
安全层：AES-256-GCM（可选关闭视频加密）；密钥由配对秘密派生
传输层：UDP（v1 默认，分片/FEC/拥塞反馈）；WebRTC（插件，后续）
发现层：mDNS + UDP 广播 + 二维码（配对秘密）
```

详见 [02-transport.md](02-transport.md) 与 [03-protocol.md](03-protocol.md)。

## 6. 关键选型与理由

| 选型 | 决定 | 理由 |
|---|---|---|
| 默认传输 | 自定义 UDP（RTP 风格分片 + XOR FEC + 反馈） | 局域网可控、开销小、延迟最低、深度/地图可定制；无需 NAT/ICE |
| 可选传输 | WebRTC 插件 | 需要标准媒体栈/未来公网时启用；接口已抽象 |
| 视频编码 | H.264 默认，HEVC 可选 | 手机硬解最普及；RK/ARM 硬编成熟；专利风险需评估（见 12） |
| App | Kotlin + Compose + 原生 MediaCodec + Filament（3D）：**KMP-ready** | 手柄与低延迟解码需要原生 API；URDF/点云统一渲染；共享协议/会话逻辑可迁移 iOS/桌面/Web（见 17 文档） |
| Agent | C++20 + GStreamer | 硬编/采集生态最完整；ROS 2 兼容性好；实时可控 |
| 地图 | 体素瓦片 + 2D 占据栅格 | 增量传输友好、实现简单、与导航栈兼容 |
| 控制抽象 | 能力描述 + 固定通道表 + 适配器插件 | 新机器人只写适配器与能力 JSON，不改 App |
| 配置/遥测 | protobuf-lite / JSON | 可演进、工具链成熟；热路径不用 |

### 6.1 为什么不用 Sunshine/Moonlight 作为底座

- 它是“屏幕串流”，视频源是桌面而非相机；无深度/点云/遥测通道。
- 控制只有 HID 快照，无能力协商、无安全语义（看门狗/急停/模式），“手柄即游戏手柄”。
- GPLv3 约束，与 Apache-2.0 目标不兼容；内部魔改维护成本高。
- 结论：可借鉴其输入/渲染思路，但**协议与实现自研**。相关评估见 ADR-0001。

### 6.2 与 rl_sar 的关系

- 机器人控制不自己造：rl_sar 是“观测→策略→PD 力矩→机器人 SDK/MCU”的部署框架，
  本项目在其外面提供**远程遥控输入**与**状态回传**，二者通过小补丁/桥接进程组合；
  不把 rl_sar 的 FSM、观测、推理逻辑搬进本项目。
- 不依赖宇树 SDK：L4W4 这类机型由 rl_sar 的内部 `l4w4_sdk`（自定义 UDP）对接，本项目不感知。
- 远程输入注入方式、补丁范围、FSM 动作映射、遥测字段见
  [13-rl-sar-bridge.md](13-rl-sar-bridge.md)。

### 6.3 客户端跨平台演进（v1.x/v2）

- v1 客户端为 Android 原生，但共享域（协议/会话/能力/命令映射/模型状态）从 M0 起按 **KMP-ready**
  设计：不引用平台 API，crypto/transport 接口化，测试向量语言无关。
- v1.x 将共享域迁到 KMP（Android/JVM），新增桌面与 iOS 客户端；v2 新增 Web 受限客户端
  （WebTransport/WebRTC，Tier B）。详情见 [17-cross-platform.md](17-cross-platform.md)。
- 平台相关能力（解码/渲染/手柄/发现/传输）全部走适配层；热路径不进入跨平台 UI 框架。

## 7. 部署形态

### 7.1 机器人端算力

| 平台 | 视频编码 | 适用 |
|---|---|---|
| x86_64 + Intel/AMD | VAAPI（`vah264enc`/`vah265enc`） | 最省心；可接 RealSense、跑 SLAM/感知 |
| x86_64 + NVIDIA | NVENC（`nvh264enc`/`nvh265enc`） | 本地跑策略模型时首选 |
| RK3588 / RK3576 | Rockchip MPP（`mpph264enc`/`mpph265enc`） | 低功耗；4K60/8K30 编码能力充足 |
| RK3566 | MPP 1080p60 编码 | 仅单相机轻量场景 |
| Jetson | `nvv4l2h264enc`/`nvv4l2h265enc`（Jetson Multimedia API） | 需按 JetPack 版本验证 GStreamer 插件 |
| Raspberry Pi 4 | `v4l2h264enc`（V4L2 M2M） | 1080p30 可用；Pi 5 无 H.264 硬编 |

> 注意：这些是 **GStreamer 管线**的能力；Sunshine 的编码后端是另一回事（无 MPP/NVMPI 支持）。
> Agent 以**同一份源码**构建 x86_64 与 aarch64 两种产物（deb/rpm/容器镜像同版本），
> 双架构共用协议与行为；32 位 armv7 不支持。详见 [07-robot-agent.md](07-robot-agent.md) §10。

### 7.2 网络形态

- 机器人自带 AP（手机直连）或同一 5GHz 路由器；推荐 5GHz/6GHz、关闭省电、固定信道。
- 发现：mDNS 优先，广播兜底，扫码最稳。
- v1 不做公网；若后续需要，启用 WebRTC 插件或 VPN（Tailscale/WireGuard）。
- 客户端跨平台传输：原生端 UDP；iOS 需本地网络权限；Web 端无裸 UDP，走 WebTransport/WebRTC
  （见 17 文档 §4）。

### 7.2.1 客户端平台（v1.x/v2）

| 平台 | 等级 | 传输 | 解码/渲染 | 计划 |
|---|---|---|---|---|
| Android | A | UDP | MediaCodec + Filament | v1 |
| iOS | A | UDP（本地网络权限）/WebRTC | VideoToolbox + Filament | v1.x（M7） |
| Windows/macOS/Linux | A | UDP | FFmpeg/平台硬解 + Filament | v1.x–v2（M7） |
| Web | B | WebTransport/WebRTC | WebCodecs/WebRTC + three.js | v2（M8） |

### 7.3 进程边界

- Agent 单进程 + systemd 守护；硬件编码崩溃只影响媒体线程（GStreamer 管线可重启）。
- App 前台服务持有会话；Activity 可重建。
- 管理 HTTP 与实时 UDP 分离，便于限流与权限控制。

## 8. 扩展点（插件接口）

| 扩展点 | 接口 | 使用者 |
|---|---|---|
| 传输 | `ITransport`（send/recv/feedback/stats） | UDP 默认、WebRTC 插件 |
| 媒体源 | `IMediaSource`（GStreamer 管线片段/自定义源） | V4L2、ROS 2、RealSense、测试图 |
| 编码器 | `IEncoderBackend`（GStreamer element 探测/配置） | VAAPI/NVENC/MPP/NVMPI/V4L2/软件 |
| 地图后端 | `IMapBackend`（体素/外部点云/占据栅格） | 内置体素、ROS 2 点云、SLAM 输出 |
| 机器人适配器 | `IRobotAdapter`（能力/命令/遥测/安全） | rl_sar 桥接、ROS 2、自定义 MCU、Mock |
| App 渲染器 | `IRenderer`（视频/点云/栅格/URDF 模型） | Filament（主）、GLES（备） |
| 手柄映射 | `Profile`（JSON schema） | 内置 profile、用户自定义 |

## 9. 仓库结构与模块归属（规划）

```
Uni-RoboController/
├── protocol/                  # 协议定义、示例 capability、codegen 输入（后续）
├── shared/                    # 规划（v1.x KMP）：core-protocol/session/robot/platform 接口
├── conformance/               # CTS：静态组 + 动态组（Python/pytest）
├── android/                   # App（v1）
│   ├── app/                   # 入口、导航、前台服务
│   ├── core/                  # protocol/transport/media/map/gamepad/robot
│   └── feature/               # connect/control/map/settings/logs
├── ios/ desktop/ web/         # 规划（v1.x/v2，见 17 文档）
├── agent/                     # 协议库 + mock + 最小参考 Agent（示例，非生产）
│   ├── include/urc/ src/      # liburc_protocol（帧/分片/加密/会话/消息）
│   ├── apps/{mock_robot,urc-reference-agent}.cpp
│   └── config/                # 示例 YAML、capability JSON
├── adapters/                  # 机器人适配器（子模块/独立目录）
│   ├── rl_sar_bridge/         # 网络遥控注入 + 状态回传（含 rl_sar 补丁）
│   ├── ros2_base/             # 差速/阿克曼/全向底盘
│   ├── ros2_manipulator/      # 机械臂
│   └── mock/                  # 开发用模拟机器人
├── patches/                   # 向上游提交/维护的补丁（rl_sar 等）
├── tools/                     # mock_robot、packet_viewer、urdf_bundle、bw_calc、latency_test
├── examples/                  # 端到端示例配置
└── docs/
```

模块边界规则：

- `core-protocol` 不依赖 Android UI/网络实现；纯 Kotlin/JVM 可单测；**KMP-ready**（不引用 `android.*`）。
- `core-transport` 只依赖 `core-protocol`；媒体/地图模块不直接碰 socket。
- 平台相关实现（解码/渲染/手柄/发现/crypto）只存在于平台层，通过 expect/actual 或接口注入。
- Agent 的 `adapters` 只依赖 `control` 的接口与 `telemetry` 数据结构，不直接依赖 `transport`。
- 任何跨模块调用必须通过接口，禁止直接访问别的模块的内部实现。

## 10. 失败域与降级

| 失败 | 影响 | 降级策略 |
|---|---|---|
| 手柄断连 | 无输入 | 冻结/零速；提示重连；虚拟手柄可用 |
| 视频解码失败 | 无画面 | 请求关键帧/重启解码器；控制继续 |
| 网络抖动 | 画面卡顿/延迟 | 自适应降码率/降帧率；控制帧重复发送 |
| 断网 | 失联 | 机器人侧看门狗停车；App 自动重连 |
| Agent 崩溃 | 全部中断 | systemd 重启；机器人适配器看门狗停车 |
| 地图过大 | 内存/带宽 | 瓦片 LRU、范围限制、按需请求 |
| 加密密钥失配 | 无法连接 | 重新配对；提示重新扫码 |
