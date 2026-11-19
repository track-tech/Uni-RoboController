# 15 URDF 模型加载与机器人状态同步

> 目标：App 能加载任意四足/人形/轮足/机械臂的 URDF，按遥测实时同步关节与根位姿，
> 用于 3D 状态显示、关节限位提示与远程调试；模型与状态解耦，模型缺失时控制仍可用。
> 本文定义模型包格式、转换流程、协议扩展、渲染与失败处理。

## 1. 需求与边界

- **任意形态**：四足（12–16 DOF）、人形（20–50+ DOF，浮动基座）、轮足（16–20 DOF）、
  机械臂（6–7 DOF + 夹爪/灵巧手）；关节数量、名称、层级由 URDF 决定。
- **状态同步**：遥测携带根位姿 + 关节位置（可选速度/力矩），App 以 20–50 Hz 接收、60 Hz 渲染。
- **模型来源**：优先从机器人 Agent 下载“模型包”；也支持开发者本地导入 URDF/zip（离线预览/调试）。
- **非目标（v1）**：App 端不运行物理/碰撞检测；不执行 xacro 脚本；不做完整 SLAM/导航渲染。
- 若机器人没有 URDF：capability 用 `joints` 手写关节表，App 退化为“关节条 + 简化骨架”显示。

## 2. 模型包（Model Bundle）

### 2.1 目录结构

```
model-<name>-<hash8>/
├── model.json        # 元数据：链接/关节/限位/视觉/状态顺序/帧约定
├── model.glb         # 转换后的场景（节点=link，关节节点=joint:<name>）
├── preview.png       # 可选缩略图
└── LICENSE           # 可选，第三方网格/模型许可
```

- 打包为 zip（HTTP 下载），`bundle_hash = SHA-256(model.json + model.glb)` 的规范化哈希。
- capability 中携带 `bundle_hash` 与下载 URL；App 校验哈希后才渲染。
- 版本：`model_format: "glb+json/v1"`；格式变更升版本。

### 2.2 `model.json` schema（节选）

```jsonc
{
  "schema": "urc-model/v1",
  "name": "l4w4",
  "source": {"urdf": "l4w4.urdf", "xacro": false, "converter": "urdf_bundle/0.1"},
  "base_link": "base_link",
  "root_frame": "odom",
  "up_axis": "z",                 // URDF/ROS: z-up；渲染器内部转换
  "units": {"length": "m", "angle": "rad"},
  "links": [{"name": "base_link", "visual": ["base_link.stl"], "collision": ["base_link.stl"]}],
  "joints": [
    {
      "name": "FL_hip_joint", "type": "revolute",
      "parent": "base_link", "child": "FL_hip_link",
      "axis": [1, 0, 0], "origin_xyz": [0.2, 0.1, 0.0], "origin_rpy": [0, 0, 0],
      "limit": {"lower": -0.8, "upper": 0.8, "velocity": 30.0, "effort": 150.0}
    }
  ],
  "joint_order": ["FL_hip_joint", "FL_thigh_joint", "..."],   // 与遥测一致
  "render": {"scale": 1.0, "decimate": 0.5, "shadows": false}
}
```

- `joints[]` 包含所有关节（含 fixed），`joint_order` 仅包含**受控关节**（与遥测/命令对齐）。
- `type`：revolute / continuous / prismatic / fixed / floating（浮动基座用根位姿表达，不单列入 order）。
- `limit` 来自 URDF；若缺失，渲染仍可用，但**不允许**用于关节命令（安全校验拒绝）。

## 3. 转换流程（离线/开发机）

```
URDF / xacro ──(xacro 展开)──▶ URDF
  ──(urdfdom / urdf_parser_py 解析)──▶ links/joints/limits
  ──(mesh 解析 STL/DAE/OBJ)──▶ glTF（节点=link 层级）
  ──(meshoptimizer 简化/合并)──▶ model.glb
  ──(生成 model.json + 哈希)──▶ bundle.zip
```

- 工具：`tools/urdf_bundle`（Python，CLI + 库）：`urdf_bundle build <urdf|pkg> -o bundle.zip`。
- 依赖建议：`urdf_parser_py`（BSD）、trimesh（MIT）、assimp/`pygltflib`、meshoptimizer（MIT）、
  xacro（ROS，BSD，仅离线展开）。**Agent 不在线执行 xacro**，避免任意脚本执行。
- 网格格式：STL/OBJ/DAE（Collada）转 glTF；纹理内嵌；缺失网格用包围盒/占位体。
- 减面：默认 50%（移动端）；保留视觉外观，碰撞网格不导出（v1 不需要）。
- 单位：强制米/弧度；DAE 常见厘米单位需检测并缩放。
- 坐标系：URDF 为 z-up、x-forward；glTF/Filament 为 y-up，转换器统一旋转并记录 `up_axis`。
- 大模型限制：GLB ≤ 20 MB、三角形 ≤ 100 万（超限拒绝并提示减面）。

## 4. Capability 扩展

在 capability 中新增：

```jsonc
"model": {
  "present": true,
  "bundle_hash": "sha256:....",
  "format": "glb+json/v1",
  "url": "/api/v1/model/ab12cd34.zip",
  "joint_order": ["FL_hip_joint", "..."],     // 与 MODEL_STATE 等长
  "joint_order_hash": 123456789,               // CRC32(joint_order) 供快速校验
  "base_link": "base_link",
  "root_frame": "odom",
  "dof": 16
}
```

- `joint_order` 必须与遥测/命令的关节顺序一致；适配器负责把机器人 SDK 顺序映射到此顺序
  （参考 rl_sar 的 `joint_names` 与 `joint_mapping`）。
- `joint_order_hash` 用于握手/状态帧快速校验，避免“名称对但顺序错”的静默错误。
- 模型变更（换版本）→ 新 `bundle_hash`；控制中不允许静默替换，需重连/确认。

## 5. 状态同步协议

新增消息 `MODEL_STATE`（0x19，telemetry 流，不可靠，20–50 Hz，超长分片）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | u32 | 采样序号 |
| `ts_us` | u64 | 机器人采样时间（单调时钟） |
| `joint_order_hash` | u32 | 与 capability 比对 |
| `joint_count` | u16 | = len(joint_order) |
| `joint_pos[]` | f32 × N | 关节位置（rad 或 m） |
| `joint_vel[]` | f32 × N | 可选 |
| `joint_eff[]` | f32 × N | 可选 |
| `root_pos[3]` | f32 | map/odom 系位置 |
| `root_quat[4]` | f32 | 四元数（w,x,y,z，需统一；文档显式声明） |
| `root_vel[3]` / `root_omega[3]` | f32 | 可选 |
| `frame_id` | u8 | 0=odom，1=map，2=base（预留） |

- 关节数 50 → 载荷 4+8+4+2+200+200+200+12+16+24 ≈ 670 B，未超 1200 B；人形 50+ 关节需分片。
- 与 `TELEM` 分工：`TELEM` 保留摘要（模式/电量/链路/策略），`MODEL_STATE` 传高频关节/位姿；
  两者时间戳独立但都应来自机器人同一单调时钟。
- 状态频率：默认 30 Hz（人形/机械臂可 50 Hz）；带宽 50 关节 × 50 Hz × 4 B ≈ 10 KB/s，可忽略。
- **状态有效性**：`ts_us` 与 App 本地时钟估算偏差；超过 500 ms 未更新 → 模型置灰并提示“状态过期”。

## 6. App 渲染

### 6.1 技术选型

- 主选：**Filament（Apache-2.0）** 统一渲染（Android/iOS/macOS/Windows/Linux 原生支持）；
  后续 iOS/桌面客户端复用同一 glb 资产与关节更新逻辑；Web（Tier B）用 three.js/WebGPU
  加载同一模型包（可裁剪关节更新频率）。
  - `gltfio` 加载 `model.glb` 场景；节点名=link，关节节点=joint:<name>；
  - 每帧由 URDF 关节树 + 当前关节角计算各关节局部变换，更新 `TransformManager`；
  - 支持 PBR 材质、阴影可关、选中高亮、线框/坐标轴；
  - 点云用 Filament 的 `PrimitiveType::POINTS`（与模型同场景，避免多层 Surface 叠加问题）。
- 备选：纯 GLES 自定义渲染器（性能兜底）；或 WebView + three.js/urdf-loader（仅原型/离线预览）。
- 决策见 ADR-0011；若 Filament 点云性能不达标，保留“模型 Filament + 点云 GLES 叠加”的混合方案。

### 6.2 关节更新

- 从 `model.json` 建关节树（parent/child/axis/origin/limit）；
- 收到 `MODEL_STATE`：按 `joint_order` 更新关节角；根位姿应用到 base_link 的父节点；
- **插值**：保留最近 2–3 帧，渲染时按时间戳线性插值（关节角 lerp，根位姿 slerp）；
  外推最多 100 ms；超过则冻结并显示“数据延迟”；
- 关节限位可视化：超出 URDF 限位时高亮（红色）——仅提示，不替代机器人侧保护；
- 模型/状态不匹配（`joint_order_hash` 不一致、数量不符）→ 不渲染运动，显示诊断信息。

### 6.3 坐标系转换

- URDF/ROS（z-up）→ Filament（y-up）：转换器一次性旋转；`model.json` 标注 `up_axis`。
- 根位姿：`odom/map` 系 → 渲染世界系；`base_link` 到根位姿的变换由 URDF 决定；
- 约定：四元数统一 `(w,x,y,z)`；位置单位米；角度弧度；若机器人 SDK 用 `(x,y,z,w)` 或 NED，
  由适配器在 Agent 侧转换（App 不猜测）。
- 显示：网格/坐标轴/比例尺；支持“重置视角”“跟随机器人”。

### 6.4 性能

- 目标：人形 30–50 关节、≤30 万三角形，60 FPS（中端机）；点云与模型同场景时按需降档；
- 减面（转换器）、材质简化（无阴影/低分辨率纹理）、纹理压缩（KTX2 可选）；
- 热降频监测：降渲染分辨率/帧率；与视频解码共享 GPU 时监控掉帧；
- 内存：单模型 GLB ≤ 100 MB 解码内存；缓存多个模型用 LRU，磁盘上限可配置。

## 7. App 交互

- **模型视图**：叠加在视频上（半透明/画中画）或独立页面；显示关节角、限位、末端位姿；
- **关节面板**：按 URDF 关节树分组（腿部/臂/手/腰/头），滑块显示 URDF 限位；
  仅当能力声明 `joint_position` 模式时可用（见 08 文档）；
- **模型管理**：自动下载/更新（按 hash）、手动导入 zip/URDF（开发调试）、删除缓存、查看来源/版本；
- **诊断**：模型 hash、关节顺序、缺失关节、状态延迟、坐标系警告；
- **离线预览**：无机器人时加载本地 URDF 查看结构（可选功能）。

## 8. Agent 侧

- **模型仓库**：`/var/lib/urc/models/<robot_id>/<hash>/`；启动扫描/校验；HTTP 只读提供。
- **生成/导入**：开发者用 `tools/urdf_bundle` 生成 zip 后通过管理接口上传（管理员权限、大小限制、
  校验哈希/格式，不执行其中的脚本）；也支持部署时预置。
- **URDF 解析（可选）**：用 urdfdom（BSD-3）或 Pinocchio（BSD-2）解析，获取关节限位/树结构，
  用于命令校验与状态映射校验；不依赖 ROS。
- **状态映射**：适配器输出 `ModelState`（关节顺序=capability.joint_order）；若某关节不可用，
  用 NaN/缺省并标记；Agent 校验数量/哈希后发送。
- **安全**：模型 hash 与 capability 一致性、状态过期、关节数不匹配均触发降级/告警；
  模型文件不可包含可执行内容；下载/上传需鉴权。

## 9. 形态示例

| 形态 | DOF 示例 | 根位姿 | 状态 | 命令接口 |
|---|---|---|---|---|
| 四足 Go2/L4W4 | 12/16 | 浮动基座位姿 | 关节 q/dq | 速度（RL 策略）/动作 |
| 轮足 L4W4 | 16（含 4 轮） | 浮动基座位姿 | 关节 q/dq + 轮速 | 速度 + 高度/俯仰 |
| 人形 G1（rl_sar） | 29+ | 浮动基座位姿 | 关节 q/dq + IMU | 速度（RL）/关节（臂）/动作 |
| 机械臂 6/7 DOF | 6–7 + 夹爪 | 固定基座 | 关节 q/dq/eff | 关节/笛卡尔/轨迹 |
| 移动机械臂 | 底盘 + 臂 | 浮动/固定 | 全部 | 底盘速度 + 臂关节/笛卡尔 |

## 10. 失败与对抗（与 14 文档对应）

| 场景 | 期望 |
|---|---|
| 模型 hash 不符/被篡改 | 拒绝渲染并告警；控制不受影响 |
| 关节顺序/数量不匹配 | 不渲染运动，显示诊断；不用于命令 |
| 超大网格/纹理炸弹 | 解码前限制大小/三角形数；拒绝并提示 |
| URDF/GLB 解析异常 | 沙箱解析失败→回退“骨架显示”；不崩溃 |
| 状态时间戳跳变/断流 | 冻结/置灰；>500 ms 提示过期 |
| 根位姿跳变 | 显示异常标记；不改变控制 |
| 模型版本与机器人固件不匹配 | 提示可能失配；以关节名/限位诊断 |
| 下载中断/磁盘满 | 缓存校验失败重试；LRU 清理 |

## 11. 验收

- 加载 4 类 URDF（四足 16、人形 29、轮足 16、机械臂 7）均能正确显示层级与关节运动；
- 关节状态 30 Hz 下渲染 60 FPS，延迟（状态到画面）≤ 100 ms（插值后）；
- 关节顺序/限位与 URDF 一致；超出限位高亮；
- 模型包 ≤20 MB、下载 ≤5 s（局域网）、缓存复用；
- 模型篡改/关节不匹配/超大网格等对抗用例通过（见 14 文档）。
