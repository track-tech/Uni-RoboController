# Uni-RoboController

开源、**客户端分级跨平台**、面向局域网的**多形态机器人遥操作平台**。
v1 客户端为 Android 首发；v1.x 扩展 iOS/桌面（Tier A 全功能低延迟主控）；v2 扩展 Web 受限客户端（Tier B）。

一套 App 控制多种机器人：四足、人形、轮足、轮式（差速/阿克曼）、机械臂/移动操作臂，
支持多种物理手柄与屏幕虚拟手柄、可插拔视频传输、深度图像与点云地图、URDF 模型状态同步。

> 仓库：<https://github.com/track-tech/Uni-RoboController>
>
> 状态：**设计阶段**。本仓库当前包含设计文档 v0.1（2026-11-18，含 rl_sar 036 兼容方案与对抗验证方案），
> 代码尚未开始。许可证署名与组织归属以项目发起人确认为准。

## 目标

- **一个 App 控制多种机器人**：通过“能力描述（capability）+ 适配器（adapter）”抽象，不把 App 绑定到某一款机器人；目标覆盖任意四足、人形、轮足、机械臂。
- **URDF 模型同步**：加载机器人 URDF 转换后的模型包，按遥测实时同步根位姿与关节角，3D 显示机器人状态；模型与状态解耦，缺失/不匹配时安全降级。
- **可自定义的视频传输**：媒体管线（采集/编码/打包/FEC/传输/解码/渲染）每一层都可配置、可替换；默认提供局域网 UDP 低延迟通道，预留 WebRTC 传输插件。
- **深度与点云地图**：机器人侧构建体素地图并流式下发，App 渲染三维点云、占据栅格、深度图，支持测量与离线保存。
- **手柄友好**：同时支持多种型号、多只手柄，手柄映射可配置、可导入导出，屏幕虚拟手柄兜底。
- **客户端分级跨平台**：协议/能力模型与平台无关；Android 首发，iOS/桌面（Tier A）与 Web（Tier B）分期交付，客户端按能力声明自动降级。
- **开源可维护**：协议公开、模块边界清晰、依赖许可证干净（Apache-2.0 为主）。

## 非目标（v1）

- 公网/NAT 穿透（仅局域网；后续可选 WebRTC/WebTransport 插件支持）。
- v1 的 iOS/桌面/Web 客户端（v1.x/v2 分期交付，见 [docs/17-cross-platform.md](docs/17-cross-platform.md)）。
- 机械臂力控/关节力矩级遥操作、无人机自主飞行（作为后续扩展）。
- 云端账号体系、多租户、远程运维平台。

## 架构速览

```
┌────────────── 客户端 App（v1: Android/Kotlin；v1.x: iOS/桌面） ──────────────┐
│ 连接/配对   视频渲染(MediaCodec)   深度/点云/栅格渲染(GLES/Filament)   手柄抽象/映射     │
│ 遥测 HUD    URDF 模型/关节状态同步  录制/日志/设置        管理器(HTTP)   会话/安全          │
└───────────────┬───────────────────────────────────────────────┬──────────────┘
                │  UDP 实时通道（控制/遥测/视频/深度/地图，AES-GCM 可选）│ HTTP 管理通道
                ▼                                               ▼
┌──────────────────────── 机器人 Agent（C++/GStreamer，Linux） ─────────────────┐
│ 会话/发现/配对   传输层(UDP+WebRTC 插件)  媒体管线(采集→硬编→打包→FEC)         │
│ 控制解析/看门狗/状态机   地图构建(体素/占据栅格)   遥测   管理 HTTP   日志/录像   │
│ 状态同步(关节/根位姿)     模型包存储/下发           URDF 解析(限位)                 │
│                              │ 适配器插件（能力描述 + 命令映射 + 安全限制）      │
│              rl_sar 桥接（网络遥控注入+状态回传） · ROS 2 底盘/机械臂 · 自定义 MCU · Mock │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 设计文档

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 文档索引与阅读顺序 |
| [docs/00-scope.md](docs/00-scope.md) | 需求、约束、术语、非目标 |
| [docs/01-architecture.md](docs/01-architecture.md) | 总体架构、模块边界、数据流、技术选型 |
| [docs/02-transport.md](docs/02-transport.md) | 传输抽象、UDP 低延迟协议、发现/配对/加密 |
| [docs/03-protocol.md](docs/03-protocol.md) | 线上协议、消息格式、版本化 |
| [docs/04-video.md](docs/04-video.md) | 视频采集/编码/打包/FEC/自适应码率/解码渲染 |
| [docs/05-depth-pointcloud.md](docs/05-depth-pointcloud.md) | 深度图、点云、体素地图、瓦片与渲染 |
| [docs/06-android-app.md](docs/06-android-app.md) | App 架构、UI、手柄抽象、多手柄、保活 |
| [docs/07-robot-agent.md](docs/07-robot-agent.md) | Agent 架构、配置、平台适配、构建部署 |
| [docs/08-robot-abstraction.md](docs/08-robot-abstraction.md) | 多形态机器人能力模型与适配器 |
| [docs/09-safety.md](docs/09-safety.md) | 安全设计、看门狗、急停、故障处理 |
| [docs/10-roadmap.md](docs/10-roadmap.md) | 里程碑、任务拆分、验收标准、风险 |
| [docs/11-testing.md](docs/11-testing.md) | 测试策略、HIL、网络损伤、设备矩阵 |
| [docs/12-open-source.md](docs/12-open-source.md) | 许可证、依赖、治理、CI、发布 |
| [docs/13-rl-sar-bridge.md](docs/13-rl-sar-bridge.md) | rl_sar 兼容：网络遥控注入、状态回传、FSM/安全 |
| [docs/14-adversarial-verification.md](docs/14-adversarial-verification.md) | 对抗验证：安全不变式、威胁模型、故障注入、红队剧本 |
| [docs/15-urdf-model.md](docs/15-urdf-model.md) | URDF 模型包、转换、状态同步、Filament 渲染 |
| [docs/16-m0-plan.md](docs/16-m0-plan.md) | **M0 实施计划**（当前执行入口） |
| [docs/17-cross-platform.md](docs/17-cross-platform.md) | 客户端分级跨平台、共享内核、平台矩阵与迁移路径 |
| [docs/adr/](docs/adr/) | 关键决策记录（ADR） |

## 计划中的仓库结构

```
Uni-RoboController/
├── docs/                 # 设计文档（当前阶段）
├── protocol/             # 协议定义、示例 capability、schema
├── android/              # Android App（Kotlin/Compose，后续）
├── agent/                # 机器人 Agent（C++/GStreamer，后续）
├── adapters/             # 机器人适配器（unitree_go2、ros2_base、mock…）
├── tools/                # mock 机器人、抓包/回放、带宽计算器
└── examples/             # 配置示例、演示脚本
```

## 里程碑（摘要）

M0 文档与协议定稿 → M1 会话/控制/手柄 → M2 视频链路 → M3 深度/点云/URDF 模型 →
M4 地图/多形态 → M5 rl_sar 036 真机兼容 → M6 安全硬化与首个开源版本 →
M7 iOS/桌面客户端（Tier A）→ M8 Web 受限客户端（Tier B）。

> **当前执行入口**：M0 实施计划（仓库骨架 · 协议内核 · Mock 机器人 · 调试骨架）见
> [docs/16-m0-plan.md](docs/16-m0-plan.md)。
> 对抗验证贯穿 M1–M6，P0 安全用例未通过不发布。详见 [docs/10-roadmap.md](docs/10-roadmap.md)
> 与 [docs/14-adversarial-verification.md](docs/14-adversarial-verification.md)。

## 许可证

计划采用 **Apache-2.0**（待确认）。依赖许可证清单与合规注意事项见 [docs/12-open-source.md](docs/12-open-source.md)。
