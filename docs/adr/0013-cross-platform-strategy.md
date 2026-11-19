# ADR-0013 跨平台客户端策略（KMP + 平台原生适配，Web 受限）

- 状态：Accepted
- 日期：2026-11-19

## 背景

原 v1 约束为“仅 Android”。项目更名为 Uni-RoboController 后，跨平台成为明确目标：
iOS、Windows/macOS/Linux 桌面、Web 浏览器都需要接入同一机器人，但各平台的媒体解码、
3D 渲染、手柄、发现/传输能力差异很大；Web 端没有裸 UDP，Gamepad API 在 Safari/iOS 受限。

## 决定

1. **分级跨平台**：Tier A 全功能低延迟主控（Android v1、iOS/桌面 v1.x–v2）；
   Tier B Web 受限客户端（v2，监控/演示/轻控制）；Tier C 机器人 Agent 保持 Linux 为主。
2. **共享域用 Kotlin Multiplatform**（推荐）：协议/会话/能力/命令映射/模型状态/配置在 commonMain；
   UI 用 Compose Multiplatform（Android/iOS/桌面）；Web 端 Kotlin/Wasm（Beta）或独立 TS 客户端，
   以测试向量保证协议一致。
3. **热路径平台原生**：视频解码（MediaCodec/VideoToolbox/FFmpeg/WebCodecs）、3D 渲染
   （Filament 跨平台原生；Web three.js/WebGPU）、手柄（InputDevice/GameController/SDL3/Gamepad API）、
   传输（UDP 原生；Web 用 WebTransport 主、WebRTC 备）全部走平台适配层，不进共享 UI 框架。
4. **M0 起 KMP-ready**：`core:protocol` 不引用 `android.*`；crypto/transport 接口隔离；
   测试向量语言无关；v1 不引入 KMP 插件，避免过早复杂度。
5. **能力声明与降级**：HELLO 携带 `client_caps`；Agent 按位裁剪可选功能（深度/点云/HEVC 等），
   但认证/看门狗/急停等安全逻辑**不可降级**。
6. **Web 传输**：WebTransport（HTTP/3/QUIC）为主、WebRTC 为兼容备选；自签证书体验问题
   文档化并给出 WebRTC 备选路径；Web 不承诺低延迟主控与原始深度流。
7. **备选方案记录**：Rust core + UniFFI/wasm-bindgen 是长期备选（一份逻辑全平台共享、内存安全），
   若团队 Rust 能力强或跨平台成为主线，可经新 ADR 切换。

## 理由

- KMP 复用现有 Android Kotlin 资产，共享协议/会话逻辑，UI 也能跨 Android/iOS/桌面；
  平台热路径保持原生，避免 Flutter/WebView 在低延迟媒体与手柄上的穿层损耗。
- Web 浏览器限制决定其只能做 Tier B，分级承诺避免“全平台同功能”导致的过度设计与体验落差。
- 测试向量 + CI 差分可防止多端实现漂移（C++/Kotlin/iOS/Wasm）。

## 后果

- v1.x 需要一次共享层迁移（`android/core/*` → `shared/*`），有一次性重构成本；M0 的 KMP-ready
  约束把返工降到最低。
- iOS 本地网络权限、Web 证书/浏览器能力差异需要专门 UX 与文档；Tier B 功能受限需明确告知。
- 新增依赖（KMP/Compose Multiplatform/Filament 跨平台/WebTransport 库/SDL3/three.js）需纳入
  许可证与 SBOM 管理（12 文档）。

## 备选

- **Flutter**：UI 复用快，但低延迟媒体/手柄/3D 插件碎片化、热路径穿层，需大量平台代码；不推荐主控。
- **Rust core + 原生 UI（UniFFI/wasm-bindgen）**：长期更稳，但需重写规划、FFI 与团队技能成本；
  作为备选，不立即采用。
- **Qt/QML**：桌面强、移动端弱；不采用。
- **Tauri + Web 技术**：桌面轻量，移动/低延迟媒体支持有限；不采用。
