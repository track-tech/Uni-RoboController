# Uni-RoboController

开源机器人遥操作**协议 + Android 操作端 + 一致性测试（CTS）**项目。

> 仓库：<https://github.com/track-tech/Uni-RoboController>
>
> 状态：**设计阶段（v0.1，2026-11-19）**。范围已收敛为 B 方案（见
> [ADR-0014](docs/adr/0014-scope-app-protocol-cts.md)）：本项目交付
> **Android App + 协议 + CTS + mock/最小参考 Agent**；机器人端生产实现由厂商/社区按协议完成。
> 代码尚未开始。

## 目标

- **标准协议口**：公开的线上协议、能力描述、URDF 模型包格式与实现指南；机器人端按需实现。
- **Android 操作端**：局域网自动发现、配对手柄/虚拟手柄、低延迟视频、URDF 状态同步、安全交互。
- **一致性测试（CTS）**：静态组 + 动态组（P0/P1），第三方实现用它自测，App 不逐家适配。
- **可跑的参考**：mock 服务端（全协议 + 故障注入）+ 最小参考 Agent（单形态/单相机/基础档，x86_64+aarch64）。
- **多形态机器人**：四足、人形、轮足、机械臂通过“能力描述 + 命令接口 + URDF”接入。

## 非目标（v1）

- 不提供生产级完整 Agent、多形态适配、rl_sar 补丁、完整 SLAM/点云地图实现。
- 不做 v1 的 iOS/桌面/Web 客户端（跨平台后置到 v1.x/v2）。
- 不做公网/NAT 穿透；仅局域网。
- 不替第三方实现的质量背书（只提供 CTS 与兼容登记）。

## 交付边界（B 方案）

| 本项目交付 | 由机器人端实现方交付 |
|---|---|
| 协议规范 + 测试向量 + 实现指南 | 生产 Agent（采集/编码/控制/遥测/安全） |
| Android App（基础档） | 具体机器人适配（rl_sar/ROS 2/厂商 SDK） |
| CTS（静态 + 动态） | 通过 CTS 并登记兼容性 |
| mock + 最小参考 Agent（示例） | 深度/点云/地图/关节控制（增强档按需） |
| 工具（codec_ref/urdf_bundle 等） | 机器人端部署/运维 |

## 基础档 / 增强档

| 档位 | 内容 | 版本 |
|---|---|---|
| v1 基础档 | 发现/配对/会话/控制/遥测/视频（H.264）/URDF 模型状态/手柄/安全交互 | v1（约 10–14 周，2 人） |
| v1.1 增强档 | 深度图像、点云/体素地图、关节/笛卡尔命令、RL/rl_sar 社区示例 | v1.1（约 3–4 周） |
| v1.x/v2 跨平台 | iOS/桌面（Tier A）、Web 受限（Tier B） | 后置，另行规划 |

## 架构速览

```
┌──────────── 客户端 App（v1: Android；v1.x: iOS/桌面） ────────────┐
│ 发现/配对   视频(MediaCodec)   深度/点云/栅格渲染   手柄/映射      │
│ 控制/遥测   URDF 模型/关节状态同步   安全交互/HUD   管理(HTTP)      │
└──────────────┬──────────────────────────────────────┬─────────────┘
               │ UDP 实时通道（控制/遥测/视频/模型状态，AES-GCM）│ HTTP 管理
               ▼                                      ▼
┌──────── 服务端（厂商/社区实现；本项目提供 mock + 最小参考 Agent） ────────┐
│ 发现/配对/会话   协议内核(UDP/加密/分片/FEC)   控制+看门狗+急停+仲裁     │
│ 媒体(采集→H.264)  遥测  MODEL_STATE  模型包  HTTP  安全状态机            │
│        ▲ 第三方实现必须通过 CTS（conformance/）                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## 仓库结构（规划）

```
Uni-RoboController/
├── docs/            # 设计文档与 ADR
├── protocol/        # 协议规范、schema、示例 capability、测试向量
├── conformance/     # CTS（静态 + 动态，Python/pytest）
├── android/         # Android App（v1）
├── agent/           # liburc_protocol + mock + 最小参考 Agent（示例）
├── tools/           # codec_ref / urdf_bundle / packet_viewer / latency_test
└── examples/        # 端到端示例配置
```

## 设计文档

| 文档 | 内容 |
|---|---|
| [docs/00-scope.md](docs/00-scope.md) | 需求、交付边界、基础档/增强档、成功标准 |
| [docs/01-architecture.md](docs/01-architecture.md) | 总体架构、组件边界、数据流、平台矩阵 |
| [docs/02-transport.md](docs/02-transport.md) | 传输、发现/配对/加密、跨平台传输注意 |
| [docs/03-protocol.md](docs/03-protocol.md) | 线上协议、消息、分片/FEC、版本化 |
| [docs/04-video.md](docs/04-video.md) | 视频采集/编码/打包/解码（基础档） |
| [docs/05-depth-pointcloud.md](docs/05-depth-pointcloud.md) | 深度/点云/地图（增强档） |
| [docs/06-android-app.md](docs/06-android-app.md) | Android App 设计（v1 基础档） |
| [docs/07-robot-agent.md](docs/07-robot-agent.md) | 最小参考 Agent 与实现结构（示例） |
| [docs/08-robot-abstraction.md](docs/08-robot-abstraction.md) | 能力描述、命令接口、多形态接入规范 |
| [docs/09-safety.md](docs/09-safety.md) | 安全设计（App 不是安全边界） |
| [docs/10-roadmap.md](docs/10-roadmap.md) | B 方案路线图、任务与风险 |
| [docs/11-testing.md](docs/11-testing.md) | 测试策略（含 CTS 与跨架构） |
| [docs/12-open-source.md](docs/12-open-source.md) | 许可证、依赖、治理、发布 |
| [docs/13-rl-sar-bridge.md](docs/13-rl-sar-bridge.md) | rl_sar 社区示例（可选，非核心承诺） |
| [docs/14-adversarial-verification.md](docs/14-adversarial-verification.md) | 对抗验证与发布门禁 |
| [docs/15-urdf-model.md](docs/15-urdf-model.md) | URDF 模型包、状态同步、渲染 |
| [docs/16-m0-plan.md](docs/16-m0-plan.md) | **M0 实施计划**（当前执行入口） |
| [docs/17-cross-platform.md](docs/17-cross-platform.md) | 跨平台规划（v1.x/v2） |
| [docs/18-protocol-implementation-guide.md](docs/18-protocol-implementation-guide.md) | **协议实现指南 + CTS**（面向机器人端实现者） |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR） |

## 里程碑（摘要）

M0 协议/CTS/mock/参考 Agent 骨架（3 周）→ M1 基础档（3–4 周）→ M2 硬化与 v1.0（2–3 周）
→ M3 v1.1 增强档（3–4 周）→ M4 跨平台（后置）。

> **当前执行入口**：[docs/16-m0-plan.md](docs/16-m0-plan.md)；协议接入见
> [docs/18-protocol-implementation-guide.md](docs/18-protocol-implementation-guide.md)。

## 许可证

计划采用 **Apache-2.0**（待确认，`LICENSE.tbd` 占位）。依赖与合规约定见
[docs/12-open-source.md](docs/12-open-source.md)。
