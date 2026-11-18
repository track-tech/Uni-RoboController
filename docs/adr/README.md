# 架构决策记录（ADR）

| 编号 | 决策 | 状态 |
|---|---|---|
| [0001](0001-udp-default-webrtc-plugin.md) | 默认自研 UDP 传输，WebRTC 作为插件 | Accepted |
| [0002](0002-robot-integration-rl-sar.md) | 不依赖宇树 SDK；rl_sar 兼容层 | Accepted |
| [0003](0003-video-h264-default.md) | 视频默认 H.264，HEVC 可选 | Accepted |
| [0004](0004-depth-deprojection.md) | 传深度 + 客户端 GPU 反投影，不传点云本体 | Accepted |
| [0005](0005-voxel-tile-map.md) | 地图用体素瓦片 + 2D 占据栅格 | Accepted |
| [0006](0006-android-stack.md) | Android 原生 Kotlin/Compose + MediaCodec/GLES | Accepted |
| [0007](0007-agent-stack.md) | Agent 用 C++20 + GStreamer | Accepted |
| [0008](0008-license-apache2-gpl-isolation.md) | Apache-2.0 + GPL 隔离 | Accepted |
| [0009](0009-adversarial-release-gate.md) | 对抗验证作为发布门禁 | Accepted |
| [0010](0010-capability-schema.md) | 自研轻量能力描述 schema | Accepted |
| [0011](0011-urdf-model-filament.md) | URDF 模型包 + Filament 渲染 | Accepted |
| [0012](0012-generic-command-interfaces.md) | 通用命令接口（velocity/joint/cartesian/action） | Accepted |

## 新增 ADR 的格式

1. 背景（问题/约束）
2. 决定（做法）
3. 理由（为什么）
4. 后果（正面/负面/风险）
5. 备选（考虑过但未采用）

状态：Proposed / Accepted / Deprecated / Superseded。
