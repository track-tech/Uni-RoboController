# 设计文档索引

本目录是 Uni-RoboController（暂定名）的完整设计文档。**所有实现必须在对应设计文档定稿后开始**，
新增较大功能时遵循同样流程：先改文档 / 新增 ADR，再写代码。

## 阅读顺序

1. [00-scope.md](00-scope.md) —— 要做什么、不做什么、约束与术语。
2. [01-architecture.md](01-architecture.md) —— 总体架构与模块边界。
3. [02-transport.md](02-transport.md) —— 网络传输、发现、配对、加密。
4. [03-protocol.md](03-protocol.md) —— 线上协议与消息格式（实现者的接口契约）。
5. [04-video.md](04-video.md) —— 视频链路。
6. [05-depth-pointcloud.md](05-depth-pointcloud.md) —— 深度图与点云地图。
7. [06-android-app.md](06-android-app.md) —— App 设计（含手柄）。
8. [07-robot-agent.md](07-robot-agent.md) —— 机器人端 Agent。
9. [08-robot-abstraction.md](08-robot-abstraction.md) —— 多形态机器人抽象与适配器。
10. [09-safety.md](09-safety.md) —— 安全设计（必读）。
11. [10-roadmap.md](10-roadmap.md) —— 路线图、任务拆分与验收。
12. [11-testing.md](11-testing.md) —— 测试策略。
13. [12-open-source.md](12-open-source.md) —— 开源治理、许可证与依赖。
14. [13-rl-sar-bridge.md](13-rl-sar-bridge.md) —— rl_sar 兼容与桥接（首要集成目标）。
15. [14-adversarial-verification.md](14-adversarial-verification.md) —— 对抗验证方案（发布门禁）。
16. [15-urdf-model.md](15-urdf-model.md) —— URDF 模型加载、状态同步与 3D 渲染。
17. [16-m0-plan.md](16-m0-plan.md) —— **M0 实施计划**（交付物/WBS/排期/验收 Runbook，当前执行入口）。
18. [17-cross-platform.md](17-cross-platform.md) —— 客户端分级跨平台、共享内核与平台适配。
19. [adr/](adr/) —— 架构决策记录。

## 补充文档

- [protocol-compat.md](protocol-compat.md) —— 协议版本兼容矩阵与校验方式。
- [third-party.md](third-party.md) —— 第三方代码/依赖清单与许可证。
- [compat/rl_sar.md](compat/rl_sar.md) —— rl_sar 基线、补丁版本与已知差异。
- [../protocol/README.md](../protocol/README.md) —— 协议定义、示例 capability、测试向量规划。

## 文档约定

- 文档语言为中文；代码标识符、协议字段、日志为英文。
- 协议字段表是**强约束**：实现与文档不一致时以文档为准，或先提交文档变更 + ADR。
- 文档中的“v1 / 后续”表示版本范围；v1 指首个开源 Release。
- 所有时间单位：协议中用微秒（`*_us`）或毫秒（`*_ms`）并显式标注；带宽用 `kbps`。
- 所有坐标/单位遵循 ROS 2 约定：右手系、米、弧度；机器人坐标系 `base_link`，地图坐标系 `map`。

## 变更流程

1. 修改设计文档（必要时新增 ADR）。
2. 在 PR 中同时更新受影响的文档（协议、接口、验收标准）。
3. 协议版本号按 [03-protocol.md](03-protocol.md) 的版本化规则递增。
