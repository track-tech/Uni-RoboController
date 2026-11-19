# 17 跨平台能力设计（客户端分级 · 共享内核 · 平台适配）

> 背景：v1 约束原是“仅 Android”。项目名为 Uni-RoboController 后，跨平台成为明确目标：
> 同一套协议与能力模型支持 **Android / iOS / Windows / macOS / Linux 桌面 / Web（受限）**，
> 机器人端 Agent 保持 Linux 为主。本文定义分级、共享边界、平台矩阵、迁移路径与验收，
> 是 [06-android-app.md](06-android-app.md) 的上位设计（06 变为“Android 首发实现”）。

## 1. 原则：分级跨平台，而不是“一套代码全平台同功能”

| 等级 | 定义 | 平台 | 承诺 |
|---|---|---|---|
| **Tier A 全功能低延迟主控** | 原生媒体解码 + 原生渲染 + 完整手柄 + UDP 直连 | Android（v1）、iOS（v1.x）、Windows/macOS/Linux 桌面（v1.x–v2） | 视频/深度/点云/URDF/手柄/控制全功能，延迟目标与 00-scope 一致 |
| **Tier B 受限客户端** | 浏览器环境：无裸 UDP、Gamepad API 受限、深度大码流不现实 | Web（v2） | 监控、演示、轻控制（速度/动作）、遥测/地图查看；**不承诺**低延迟主控与原始深度流 |
| **Tier C 机器人端 Agent** | Linux 主机 | x86_64 / aarch64 Linux（主力） | 全功能；Windows/macOS 仅 mock/仿真，不承诺实机部署 |

- **能力声明**：每个客户端在 HELLO 中声明 `client_caps`（传输/解码/渲染/手柄/深度），
  Agent 按能力降级（例如 Web 客户端不推送原始深度、不启用高码率视频）。
- **协议与能力模型平台无关**：帧格式、capability schema、命令/遥测/模型状态均不变；
  跨平台只替换传输、解码、渲染、手柄、发现五类适配器。
- **不牺牲热路径**：视频解码、3D 渲染、手柄采集、UDP 收发必须是平台原生/原生绑定，
  不经过跨平台 UI 框架的通用层。

## 2. 总体架构：共享域 / 平台适配域 / UI 域

```
┌──────────────────────────── UI 域 ────────────────────────────┐
│ Android/iOS/Desktop：Compose Multiplatform（共享 UI）           │
│ Web：受限 UI（Compose-Wasm 或独立 TS + three.js/WebGPU）        │
├────────────────────── 共享域（commonMain） ──────────────────┤
│ protocol编解码 · 分片/FEC · 会话/重连 · 能力模型 · 命令映射      │
│ 手柄映射引擎 · 模型状态插值 · 统计/日志 · profile/配置           │
├──────────────────── 平台适配域（expect/actual） ─────────────┤
│ Transport(UDP/WebRTC/WebTransport) · Crypto · VideoDecoder      │
│ Renderer(Filament/three.js) · GamepadSource · Discovery ·       │
│ Storage · Vibration/IMU                                          │
└───────────────────────────────┬───────────────────────────────┘
                                │ 32B 帧协议（平台无关）
                                ▼
                  机器人 Agent（Linux，C++，不变）
```

关键约束：

1. **共享域不引用平台 API**：纯 Kotlin（后续可编译到 Android/JVM/iOS-Native/Wasm）；
   不得出现 `android.*`、`Foundation`、`java.net.*` 等。
2. **热路径不进共享域**：`VideoDecoder`/`Renderer`/`GamepadSource` 只暴露接口，
   实现留在平台层；共享域只处理元数据、状态、映射、协议。
3. **加密与网络接口化**：`CryptoProvider`（AES-GCM/HKDF）各平台用系统库，
   但 nonce/AAD/密钥派生规则由共享测试向量锁定（见 02/03 文档）。
4. **协议层与传输无关**：UDP、WebRTC、WebTransport 都是 `ITransport` 实现（02 文档已有抽象）。

## 3. 技术选型

### 3.1 共享层：Kotlin Multiplatform（推荐）

| 方案 | 评价 |
|---|---|
| **KMP + Compose Multiplatform**（推荐） | 现有 Android Kotlin 代码可直接复用；协议/会话/映射/模型逻辑天然共享；Compose UI 可共享到 iOS/Desktop；平台层用原生（MediaCodec/VideoToolbox/FFmpeg/Filament/手柄 API）。Compose Multiplatform 1.11（2026）、Kotlin 2.1+；KMP Web(Kotlin/Wasm) 官方 Beta，适合 Tier B。 |
| Flutter | UI 快，但低延迟媒体/手柄/3D 需大量平台插件，热路径穿层多；Dart 重写现有 Kotlin 依赖；不推荐主控。 |
| Rust core + UniFFI/wasm-bindgen | 长期最理想（一份协议/会话/加密/URDF 逻辑，Android/iOS/Desktop/WASM 全共享，内存安全），但要重写现有规划并引入 FFI；作为 **ADR-0013 备选**，团队 Rust 强时可切换。 |
| Qt/QML | 桌面强、移动端生态弱；不推荐。 |
| Tauri + Web 技术 | 桌面 UI 轻，但移动端/低延迟媒体支持有限；不推荐主控。 |

**决定**：v1 保持 Android 原生；M0 起把共享边界按 KMP-ready 设计；v1.x 迁移为 KMP 共享模块；
Web 端用 Kotlin/Wasm（共享域）+ 受限 UI；若 Web 体验/生态受限，允许 Web 端独立 TS 实现（仍以
测试向量保证协议一致）。长期是否切 Rust core 由 ADR-0013 记录为备选。

### 3.2 平台媒体/渲染/手柄

| 平台 | 视频解码 | 3D 渲染 | 手柄 | 发现/传输 |
|---|---|---|---|---|
| Android | MediaCodec（KEY_LOW_LATENCY，API 30+） | Filament（GLES/Vulkan） | InputDevice | UDP / mDNS(NsdManager) / 广播 / QR |
| iOS | VideoToolbox | Filament（Metal，iOS 11+） | GameController（MFi/蓝牙） | UDP（NWConnection，需本地网络权限）/ NWBrowser / QR |
| Windows | Media Foundation / D3D11VA / FFmpeg | Filament（D3D12/Vulkan） | SDL3 / XInput | UDP / mDNS(JmDNS) / QR |
| macOS | VideoToolbox | Filament（Metal） | SDL3 / GameController | UDP / NWBrowser / QR |
| Linux | VAAPI/NVENC/FFmpeg | Filament（Vulkan/GL） | SDL3 | UDP / Avahi/JmDNS / QR |
| Web | WebCodecs（浏览器支持不一）或 WebRTC 内建解码 | three.js / WebGPU（受限） | Gamepad API（Safari/iOS 支持差） | WebTransport（HTTP/3）或 WebRTC；无裸 UDP |

- Filament 原生支持 Android/iOS/macOS/Windows/Linux（含 OpenGL ES、Metal、Vulkan、WebGL 2.0），
  与 15 文档的 URDF/GLB 资产同源；Web 端用 three.js/WebGPU 加载同一 glb。
- H.264 作为最低共同标准；HEVC/AV1 按平台能力探测；桌面 FFmpeg 软解兜底。
- 手柄映射引擎在共享域（profile JSON 同格式），各平台只做“原始输入 → 统一 GamepadState”。

## 4. 传输跨平台

### 4.1 原生客户端（Android/iOS/桌面）

- UDP 直连为默认（与 02 文档一致）；iOS 注意：
  - iOS 14+ 发送 UDP 单播/组播/广播都需要 **本地网络权限**（`NSLocalNetworkUsageDescription`，
    系统弹窗；无直接查询 API，需 NWBrowser 触发流程）；
  - 使用 Bonjour/mDNS 需在 Info.plist 声明服务类型；组播 entitlement 视用法而定；
  - 被拒绝时降级为二维码/手动 IP（且仍可能被系统拦截，需明确提示用户去设置开启）。
- 桌面：UDP 直连；Windows 防火墙首次提示；支持 mDNS（JmDNS/Avahi）。
- 传输与 M0 的 `ITransport` 抽象一致，协议帧不变。

### 4.2 Web 客户端（Tier B）

- 浏览器不能发裸 UDP，二选一：
  - **WebTransport（HTTP/3/QUIC）**：datagrams（不可靠）承载控制/遥测/视频分片，streams 承载地图/配置；
    Safari 26.4/iOS 26.4 起支持（2026），Chrome 97+/Firefox 114+，已进入 Baseline；
  - **WebRTC**：兼容性最广，DataChannel + 视频轨；但需要信令与更重的服务端栈。
- 推荐：**WebTransport 为主、WebRTC 为兼容备选**；Agent 侧新增 WebTransport 监听（QUIC 库 + TLS 证书）。
- 证书与安全：WebTransport 自带 TLS 1.3，但局域网自签证书是最大工程坑：
  - 方案 A：Agent 生成自签证书 + 本地 CA（用户一次性安装信任）——体验差但可控；
  - 方案 B：使用 `https://` 域名 + Let's Encrypt（需公网/内网 DNS）；
  - 方案 C：WebRTC（DTLS 自带指纹协商，无需浏览器信任证书）作为“零安装”路径。
  - 决策：Web 客户端提供两种模式，文档明确限制；配对秘密仍用于应用层认证。
- 安全边界：无论哪种传输，应用层认证/加密规则不变（02/03 文档）；Tier B 客户端不得获得
  比同等级原生客户端更高的权限。

## 5. 平台能力声明与降级

新增 HELLO 字段 `client_caps`（位掩码 + 版本）：

| 位 | 能力 | 说明 |
|---|---|---|
| 0 | `udp` | 原生 UDP |
| 1 | `webrtc` | WebRTC 传输 |
| 2 | `webtransport` | WebTransport 传输 |
| 3 | `video_h264` | 硬解 H.264 |
| 4 | `video_hevc` | 硬解 HEVC |
| 5 | `depth` | 原始深度流 |
| 6 | `pointcloud` | 点云/地图渲染 |
| 7 | `urdf` | 模型渲染 |
| 8 | `gamepad` | 实体手柄 |
| 9 | `rumble` | 震动 |

- Agent 按位降级：无 `depth` 不推深度；无 `pointcloud` 不推瓦片；无 `gamepad` 提示虚拟手柄；
  无 `video_hevc` 强制 H.264。
- 能力声明只影响“可选功能”，不影响安全逻辑；降级不得关闭认证/看门狗/急停。
- 声明被篡改的防护：能力声明仅用于服务端裁剪；越权请求（如 Web 端申请原始深度）仍按服务端策略拒绝。

## 6. 代码结构与共享边界

```
Uni-RoboController/
├── protocol/                  # 语言无关：schema + vectors（已存在）
├── shared/                    # 规划（KMP，v1.x）
│   ├── core-protocol/         # 帧/分片/加密接口/消息（commonMain）
│   ├── core-session/          # 会话/重连/看门狗观测/认证
│   ├── core-robot/            # capability/命令映射/模型状态插值/profiles
│   └── platform/              # expect 接口（transport/crypto/decoder/renderer/gamepad）
├── android/                   # v1 现有实现；v1.x 迁移到 shared 之上
├── ios/                       # 规划
├── desktop/                   # 规划（Compose Desktop）
├── web/                       # 规划（Tier B）
├── agent/                     # Linux C++ Agent（不变）
└── tools/                     # mock_robot/codec_ref/urdf_bundle（跨平台开发工具）
```

- **M0 约束（KMP-ready）**：`android/core/protocol` 不引用 `android.*`；crypto/transport 用接口隔离；
  向量三端共用——为后续 KMP 迁移零返工。
- v1.x 迁移顺序：`core-protocol` → KMP（Android + JVM）→ 抽 `core-session/core-robot` →
  Android 切到 shared → 桌面客户端复用 → iOS 复用 → Web 复用（Wasm + 传输插件）。
- 避免“双实现漂移”：C++ Agent 与 Kotlin 共享域都消费同一套 `protocol/vectors`；
  CI 强制多端字节级一致（14 文档跨平台用例）。

## 7. 路线图影响

| 阶段 | 内容 | 估时（2 人并行） |
|---|---|---|
| v1（M0–M6） | Android 全功能；M0 做 KMP-ready 边界；不引入 KMP 插件 | 不变（20–24 周） |
| M7（v1.x） | shared 迁 KMP（Android+JVM）；桌面客户端 MVP（控制/视频/URDF/手柄）；iOS MVP（控制/视频/手柄/URDF） | 3–5 个月 |
| M8（v2） | Web 受限客户端（WebTransport/WebRTC，监控/轻控制/地图查看）；桌面全功能补齐 | 2–4 个月 |

- iOS MVP 先不做原始深度/点云（可后补）；桌面先做“操作台/大屏调试”定位。
- Web 只承诺 Tier B；若需要 Web 低延迟主控，需重新评估 WebTransport 拥塞控制与浏览器解码能力。

## 8. 验收与测试

1. **协议一致性**：`protocol/vectors` 在 C++/JVM(Kotlin)/Kotlin-Native(iOS)/Wasm(Web) 全绿；
   差分测试字节级一致（14 文档）。
2. **平台权限/发现**：iOS 本地网络权限被拒绝时的降级与提示；桌面防火墙；Web 证书/配对流程。
3. **媒体/渲染矩阵**：各平台 720p60/1080p30 延迟与帧率基线；URDF 模型加载与关节同步一致。
4. **手柄矩阵**：Android/iOS/桌面各至少 3 款；Web 端说明 Gamepad API 限制并提供虚拟手柄。
5. **能力降级**：Tier B 客户端不收到深度/点云原始流；关闭可选能力不影响安全逻辑。
6. **安全**：跨平台传输仍满足 09/14 的 I1–I11；Web 端不得绕过认证/急停。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| KMP iOS/Compose 成熟度与调试体验 | v1 不迁移；iOS MVP 先用原生 SwiftUI 壳 + 共享 core，UI 共享再渐进 |
| C++/Kotlin 双实现漂移 | 同一套 vectors + CI 差分；协议变更必须同步三端 |
| iOS 本地网络权限/组播限制 | 二维码/手动 IP 兜底；文档明确设置路径；必要时引导用户开权限 |
| Web 自签证书/浏览器信任 | WebRTC 备选路径；本地 CA 文档；不承诺零配置 |
| Web Gamepad API 受限（Safari/iOS 支持差） | 屏幕虚拟手柄；文档标注 Tier B 限制 |
| 跨平台 UI 与平台原生热路径割裂 | 明确分层；共享只做逻辑/UI，热路径平台实现 |
| 包体积/构建复杂度 | KMP 按需目标；CI 分平台；Web 单列 |
| 许可与依赖碎片 | 新增依赖逐项登记（12 文档）；Flutter/Qt 不引入 |

## 10. 明确不做

- 不承诺 Web 端低延迟主控、原始深度流、点云全量渲染；
- 不在 M0–M6 引入多端构建（只预留 KMP-ready 边界）；
- 不支持 Windows/macOS 实机 Agent（仅 mock/仿真）；
- 不用 Flutter 重写热路径；不引入 Qt 作为主控。
