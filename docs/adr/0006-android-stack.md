# ADR-0006 Android 原生 Kotlin/Compose + MediaCodec/GLES

- 状态：Accepted（v1 范围；跨平台演进见 ADR-0013）
- 日期：2026-11-18

## 背景

需要低延迟硬件解码、多手柄、深度反投影点云渲染；v1 仅 Android；团队可维护性。
（后续跨平台目标见 ADR-0013：共享域迁 KMP，媒体/渲染/手柄保持平台原生。）

## 决定

- Kotlin + Jetpack Compose + 单 Activity + 前台服务；Hilt/Coroutines/StateFlow。
- 视频 `MediaCodec` 异步 + `SurfaceView`；深度/点云 `OpenGL ES 3.0+` 专用渲染线程。
- 协议/传输为纯 Kotlin 核心模块（可 JVM 单测），Android 相关能力放在独立模块。

## 理由

- 跨平台框架（Flutter/RN）在 MediaCodec、InputDevice、GLES 上会引入额外延迟与适配成本。
- 原生 API 是低延迟与手柄兼容性的基础；模块化便于测试与替换。

## 后果

- 只支持 Android（符合约束）；iOS 需另建客户端（协议与 Agent 与平台无关）。
- 需处理设备碎片化（解码能力、GLES 差异、手柄模式）。

## 备选

- Flutter + 原生插件（开发快但热路径穿层多、手柄/GL 适配复杂）。
- Web 客户端（低延迟与控制能力不足）。
