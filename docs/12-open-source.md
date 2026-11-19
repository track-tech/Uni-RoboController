# 12 开源治理、许可证与依赖

## 1. 许可证选择

- 本项目计划采用 **Apache-2.0**：宽松、含明确专利授权、与机器人/Android 生态（ROS 2、GStreamer 动态链接、
  libwebrtc、RealSense 等）兼容，适合商业与社区共同使用。
- 修改与分发需保留版权/许可声明；文件头统一 SPDX：`SPDX-License-Identifier: Apache-2.0`。
- 贡献使用 **DCO**（`git commit -s`），不要求签署 CLA。
- 专利：Apache-2.0 提供专利授权；但**视频编解码（H.264/HEVC）的专利许可与软件许可证是两件事**，
  商用分发前需自行评估 MPEG-LA 等许可（见 §4）。

## 2. 依赖许可证清单（已核对官方 LICENSE）

> 取证：官方仓库 LICENSE/COPYING 原文；部分项目 GitHub 自动识别为 NOASSERTION，已人工读取原文确认。

### 2.1 直接依赖/推荐

| 项目 | 许可证 | 用途 | 边界 |
|---|---|---|---|
| GStreamer 核心 / plugins-base / good / bad | LGPL-2.1-or-later | 媒体管线、webrtcbin（1.16+ data channel） | 动态链接；修改库需开源修改 |
| gst-rkmpp（Rockchip 插件） | LGPL-2.1（插件） | RK MPP 编解码 | 依赖 MPP 库 Apache-2.0/MIT；锁定可信 fork（原仓库已 404，待核实） |
| libwebrtc / webrtc-sdk Android AAR | BSD-3-Clause | WebRTC 传输插件 | 保留版权声明 |
| librealsense | Apache-2.0 | RealSense 深度源 | 兼容 |
| PCL / OctoMap 库 / RTAB-Map | BSD-3-Clause | 点云/地图/SLAM（可选） | 兼容；**octovis 为 GPL-2.0，禁止链接** |
| nvblox / isaac_ros_nvblox | Apache-2.0 | 可选 TSDF/ESDF | CUDA/GPU 依赖 |
| Draco / FlatBuffers / ZXing / Rerun | Apache-2.0 | 点云压缩/序列化/扫码/可视化 | 兼容 |
| protobuf / zstd（BSD 选项）/ spdlog / yaml-cpp / cpp-httplib | BSD-3 / MIT | 序列化/压缩/日志/配置/HTTP | 兼容 |
| ROS 2（rclcpp） | Apache-2.0 | 适配器/可选 | 兼容 |
| OpenBot（参考） | MIT | 参考先例 | 不直接复制亦可 |
| Foxglove Studio（参考） | MPL-2.0（最后开源版） | 仅作对照 | 文件级 copyleft；不修改源码即可 |

### 2.1.1 跨平台客户端依赖（v1.x/v2，规划）

| 项目 | 许可证 | 用途 | 边界 |
|---|---|---|---|
| Kotlin / Kotlin Multiplatform（含 Kotlin/Native、Kotlin/Wasm） | Apache-2.0 | 共享域（协议/会话/映射/模型状态） | 兼容 |
| Compose Multiplatform / Compose Desktop | Apache-2.0 | Android/iOS/桌面共享 UI（Web 端按需） | 兼容 |
| Filament（跨平台） | Apache-2.0 | Android/iOS/macOS/Windows/Linux 3D | 兼容 |
| three.js（Web Tier B） | MIT | 浏览器 3D/点云/模型 | 兼容 |
| msquic / quiche / ngtcp2（择一，Agent 侧 WebTransport） | MIT / BSD-2 / MIT | HTTP/3 服务器，供 Web 客户端连接 | 兼容；锁定版本与 SBOM |
| SDL3（桌面手柄） | zlib | Windows/macOS/Linux 手柄与热插拔 | 兼容 |
| JmDNS | Apache-2.0 | 桌面 mDNS | 兼容；Avahi（LGPL-2.1）仅动态链接可选 |
| iOS/macOS 系统框架（VideoToolbox/Metal/GameController/Network） | Apple SDK 条款 | 平台能力 | 不属开源依赖；App Store 分发需遵守 Apple 条款 |

### 2.2 模型/URDF 工具链（新增）

| 项目 | 许可证 | 用途 | 边界 |
|---|---|---|---|
| Filament + gltfio-android | Apache-2.0 | App 3D 渲染（URDF 模型 + 点云） | 兼容 |
| assimp / meshoptimizer / trimesh | BSD-3 / MIT / MIT | 网格转换/减面/打包（离线工具） | 兼容 |
| urdfdom | BSD-3 | URDF 解析（Agent 侧限位/树） | 兼容 |
| Pinocchio | BSD-2 | 可选 FK/运动学（不进 App） | 兼容 |
| xacro | BSD（ROS） | **仅离线**展开 xacro；Agent 不执行 | 兼容 |
| Robot URDF/网格资产 | 由机器人厂商决定 | 模型包分发 | **必须逐项确认授权**，不得默认开源分发 |

### 2.3 明确不引入/仅独立进程使用

| 项目 | 许可证 | 处理 |
|---|---|---|
| Sunshine / moonlight-android / moonlight-common-c | GPL-3.0 | **不链接、不复制代码**；仅可作独立进程/协议参考（本项目不使用） |
| FAST-LIO2 | GPL-2.0 | 仅作为可选外部 SLAM 进程（不链接）；或改用 BSD 许可 LIO |
| gst-plugins-ugly 中依赖 GPL 库的插件 | LGPL 模块 + GPL 外部库 | 默认不打包；如启用需逐插件评估并履行 GPL |
| unitree_sdk2 / legged_sdk / unitree_ros2 | BSD-3-Clause | 本项目不依赖（rl_sar 内部自行使用） |

### 2.3 合规规则

1. **GPL 隔离**：任何 GPL 代码不得进入 Apache-2.0 发布物；只允许“独立进程 + 可选外部组件 + 文档说明”。
2. **LGPL**：动态链接；分发时提供可替换库的方式；不修改 GStreamer 源码（如修改需开源修改部分）。
3. **MPL**：只影响被修改的源文件；不修改即无义务。
4. **静态链接**需逐项评估（尤其 LGPL），默认禁止。
5. **SBOM**：每次发布生成 CycloneDX/SPDX SBOM；CI 做许可证扫描（允许列表 + 人工复核例外）。
6. **第三方代码引入**：需在 `docs/third-party.md` 记录来源/版本/许可证/修改说明。

## 3. 仓库与治理

```
Uni-RoboController/
├── README.md / LICENSE / NOTICE / CHANGELOG.md
├── docs/                       # 设计、ADR、协议、兼容矩阵、第三方清单
├── protocol/                   # schema（proto）+ 示例 capability + 兼容性测试向量
├── android/                    # Gradle 工程
├── agent/                      # CMake 工程
├── adapters/                   # rl_sar_bridge / ros2_base / ros2_manipulator / mock
├── patches/                    # rl_sar 等上游补丁（format-patch + rebase 脚本）
├── tools/                      # mock_robot / packet_viewer / mcap_export / bw_calc / latency_test
├── examples/                   # 端到端配置与演示
├── .github/                    # CI、issue/PR 模板、release 流程
└── SECURITY.md / CONTRIBUTING.md / CODE_OF_CONDUCT.md
```

- **维护者**：至少 2 名（Android、机器人端各 1），关键模块有 CODEOWNERS。
- **决策**：架构/协议/安全变更 → ADR/RFC；维护者共识，冲突由项目负责人裁决。
- **发布**：语义化版本；协议版本独立；发布说明含已知限制与对抗测试摘要。
- **构建产物**：Agent 提供 `amd64`/`arm64` 双架构包（deb/rpm/多架构容器镜像），同一版本号；
  CI 同时构建两种架构（aarch64 交叉 + QEMU 向量测试）。
- **兼容矩阵**：`docs/compat/` 记录 App↔Agent↔适配器↔rl_sar 版本组合与测试结果。
- **分支策略**：`main` 受保护；功能走 PR；release 分支 + 标签；补丁分支按上游 commit 固定。

## 4. 安全与合规

- `SECURITY.md`：漏洞报告渠道、响应时限、披露流程；禁止公开提交安全利用细节。
- 依赖更新：Renovate/Dependabot + 人工复核；关键依赖锁版本与哈希。
- 构建：CI 固定工具链镜像；发布产物签名/校验和；APK 签名密钥离线保管。
- 隐私：不采集用户数据；诊断包脱敏；日志不含密钥。
- 编解码专利：H.264 默认；在 README 声明使用者需自行评估专利许可；提供“仅软件/可选 HEVC”说明。
- **模型资产授权**：URDF 与网格可能属于机器人厂商/第三方，模型包分发前需确认许可；
  项目中只放“示例/自制”模型，其余由用户从机器人导入。
- 出口/无线电：遵守当地法规（Wi-Fi/蓝牙功率、机器人操作），文档免责声明。

## 5. 社区与贡献

- 贡献路径：新适配器 / capability 文件 / 手柄 profile / 传输插件 / 文档与测试。
- 文档：README 快速开始（mock 机器人 10 分钟跑通）、平台移植指南、手柄适配指南、故障排查。
- 示例：rl_sar 036 配置、ROS 2 差速底盘、机械臂、mock；演示视频。
- 行为准则（Contributor Covenant）；issue 模板要求环境/复现/日志。
- 发布节奏：v1 前每 2–3 周预发布；v1 后 minor 季度、patch 按需。
