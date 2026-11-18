# 13 rl_sar 兼容与桥接设计

> 目标：让 App 成为 rl_sar 机器人的**远程遥控输入源**与**状态观察端**，
> 不改 rl_sar 的观测/推理/FSM 语义，不依赖宇树 SDK，补丁尽量小、可向上游提交。
> 本文区分两个代码基线：**上游 `fan-ziqi/rl_sar`** 与用户实际部署的 **`rl_sar-036_frs` / `rl_sar-036_simple`**。
> 标注“已核对”的条目有源码/本地工程依据。

## 1. 为什么以 rl_sar 为第一兼容目标

- rl_sar 是“**观测 → TorchScript/ONNX 策略 → 动作 → PD 力矩 → 机器人 SDK/MCU**”的部署框架，
  支持 ROS 1/2、Gazebo/MuJoCo、libtorch/onnxruntime，支持四足/轮足/人形等多类机器人。
- 它已经解决了策略部署、FSM、观测历史、参数加载、力矩限幅等核心问题；
  本项目只需补上“**网络遥控输入**”和“**状态回传**”，不重复造轮子。
- rl_sar 官方支持列表覆盖四足、轮足、人形（Go2/Go2W/B2/B2W/G1/L4W4 等），
  与“任意四足/人形/轮足/机械臂”的目标形态高度重合；机械臂/其他形态走 ROS 2 适配器。
- 许可证 Apache-2.0，与本项目兼容；补丁可以 PR 上游化，避免长期维护 fork。
- 它已有实验性的 “Mobile Web 控制”（rosbridge + web_video_server），说明“手机遥控”是真实需求；
  该方案延迟与体验有限，本项目 App 是其正式替代。

## 2. 两个基线的差异（决定补丁注入点）

| 维度 | 上游 `rl_sar`（`rl_real_l4w4.cpp`） | 036_frs（用户部署分支） |
|---|---|---|
| 遥控输入 | MCU UDP `LowState.wirelessRemote`（40 B） | 同样来自 MCU 状态帧的 `wirelessRemote` |
| 速度换算 | 硬编码 `x=ly*1.5, y=-lx*1.5, yaw=-rx*2.0` | 读配置 `max_speed`：默认 `[2.0,1.0,1.5]`；Tomas 模式 `yaw=-rx*10` |
| FSM 状态 | Passive / GetUp / GetDown / Locomotion | 同左，但转移按键不同（见 §3.2） |
| Locomotion→Passive | 未实现（注释） | **同样未实现（注释）**，只能经 GetDown 或掉线保护退出 |
| 策略选择 | 无（单策略） | 0 默认 / 1 FS / 2 RS / 3 FAST / 4 Tomas，由 F1+ry、右肩等触发 |
| 网络状态通道 | 无 | 036_simple 有 **UDP 12345** 状态查询（22 B 请求/202 B 响应，无运动指令）；036_frs 的 9 B “031 速度包”代码保留但 socket 禁用 |
| 控制频率 | 200 Hz | 200 Hz（`dt=0.005`） |
| 策略频率 | 50 Hz（`decimation=4`） | 50 Hz（“50–80 Hz”中的 80 Hz 不在本分支） |
| 低层频率 | — | 项目方口述 500 Hz，PC 侧代码未见（待核实，可能在 MCU 固件） |
| 支持形态 | 四足/轮足 | 四足/轮足；上游还支持人形 G1、双足等 |
| URDF/模型 | `rl_sar_zoo/<robot>_description`（xacro） | 同左；可用于生成模型包 |

> 结论：**036 真机不读 `/dev/input/js*`**，虚拟手柄只能用于仿真；真机必须走“网络输入源补丁”。
> 036 已经打通“状态上行”（202 B 查询），缺的正是“网络运控下行”——这与本项目要补的层完全一致。

## 3. 已核对的 036 行为

### 3.1 输入与数据链路

- 200 Hz `RobotControl()` → `GetState()` 非阻塞 `recvfrom`（MCU `192.168.50.101:777`）→ 解析 40 B
  `wirelessRemote`（`head[2] + btn(16 bit) + lx/rx/ry/L2/ly` 浮点）→ 映射为 `Input::Gamepad` 与 `control`。
- 下行 `SetCommand()`：16 个电机目标压缩为约 102 B UDP 帧（位置/Kp/Kd/轮速前馈），并做关节目标反解限幅。
- 轴映射（036）：`x=ly*max_speed[0]`、`y=-lx*max_speed[1]`、`yaw=-rx*max_speed[2]`；
  `ry` 用于策略选择（F1 按住时）；`max_speed` 默认 `[2.0, 1.0, 1.5]`。
- `start` 信号被同时用于“Tomas 可用条件”与“RC 在线判断”（`start==0` 连续 >100 周期 → 强制 GetDown）；
  其物理含义（按键/使能/链路位）**待核实**。

### 3.2 FSM 与按键（036，已核对本地分支）

| 触发 | 虚拟事件 | 转换 |
|---|---|---|
| R2 单独 | `RB_A` | Passive → GetUp |
| R1 单独 | `RB_B` | GetUp → RL_Locomotion |
| L2 单独 | `LB` | GetUp / RL_Locomotion → GetDown |
| L1 + X | `LB_X` | GetUp → Passive |
| B / Num9 | `B` / `Num9` | GetUp → GetDown |
| GetDown 完成 | 自动 `DPadUp` | GetDown → Passive |
| 掉线/看门狗 | 本地保护 | 强制 GetDown |

- **注意**：`RL_Locomotion → Passive` 在 `CheckChange()` 中被注释；从运动态“立即停”不能依赖切 Passive，
  只能经 GetDown（插值 2 s）或补丁新增的安全态。这是 E-stop 设计的关键约束。

### 3.3 现有安全能力与缺口

已有：Passive（kp=0, kd=8）阻尼态、GetDown 慢速下趴、关节力矩软限幅、MCU/RC/IMU 看门狗。
缺口（对抗验证重点，编号与 [14-adversarial-verification.md](14-adversarial-verification.md) 对应）：

| 编号 | 发现 | 影响 |
|---|---|---|
| RL-01 | 文档推荐 `LB+RB` 急停，但 036/上游 L4W4 FSM **均未处理** | 急停组合可能无效 |
| RL-02 | `TorqueProtect()` 只打印，源码注释 “Just a reminder, no protection” | 力矩越界无保护 |
| RL-03 | `AttitudeProtect()` 调用被注释 | 姿态超限不自停 |
| RL-04 | 036 **Locomotion→Passive 被注释**；运动态无即时安全出口 | 只能慢速 GetDown |
| RL-05 | 状态下行断流时无 PC 侧看门狗（036 有 MCU 看门狗：丢 400 周期≈2 s 强制下趴，日志写 “1 sec”，数值不一致） | “盲走”窗口长、日志误导 |
| RL-06 | 双输入源无仲裁：RC 每 200 Hz 重写 `control`，网络值若在 `GetState` 覆盖会被吞掉 | 网络遥控不可靠 |
| RL-07 | 断链后若实现成“保持最后命令”会持续运动；MCU 无数据时 PC 仍持续发 `sent_buff` | 失联不减速 |
| RL-08 | 输出队列无界、切换/重连不清零 | 陈旧动作/跳变 |
| RL-09 | `ReadYaml()` 缺文件静默继续 | 参数缺失→危险默认值 |
| RL-10 | 推理无超时/健康检查，`Forward()` 抢锁失败复用旧动作 | 模型卡顿持续输出 |
| RL-11 | 策略频率 50 Hz 与网络命令若 10 Hz 混用，观测阶跃超出训练分布 | 步态抖动/失稳 |
| RL-12 | `NavigationControl` 语义过载（策略选择/Tomas/状态兼容混在一起） | 接入点易错 |
| RL-13 | 202 B 状态响应无 CRC、电池字段大端其余小端、031 包无 magic/version/seq | 解析错误/版本兼容风险 |
| RL-14 | 观测/动作无时间戳 | 与视频对齐困难 |
| RL-15 | 策略切换清历史/队列，但网络模式切换、RC 接管、失联恢复未清 | 带着旧目标跳变 |

> 以上依据：`rl_real_l4w4.cpp`、`fsm_l4w4.hpp`、`rl_sdk.cpp`、本地 036_frs/036_simple 只读检查。
> 上游若已修复，以新版本为准并更新本表。

## 4. 集成层级

### L0（推荐主路径）：rl_sar 网络遥控补丁

```
[App] ──UDP/加密──▶ [Agent] ──本地回环 UDP──▶ [rl_sar patch: UrcInput]
                                                    │ 与 RC 仲裁、校验、TTL
                                                    ▼
                                         RobotControl() → StateController → FSM
                                                    │ 安全状态机（E-stop/零速/GetDown）
                                                    ▼
                                             力矩 → MCU/SDK
[App] ◀──UDP/加密── [Agent] ◀──本地回环 UDP── [状态回传：扩展 202B / 新 UDP 帧]
```

**关键设计（针对 036 的接缝）**：

- **注入点**：不要在 `GetState()` 里覆盖 `control`（RC 每 200 Hz 会重写）；新增独立的
  `UrcInput` 抽象，在 `RobotControl()` 内、与 `StateController()` 同一临界区做仲裁与合并。
- **优先级**：`本地硬件急停 > RC 本地输入 > 网络遥操作 > 自主/导航`；任一来源失联回落到安全态，
  不锁存最后命令。RC 最近 500 ms 有活动（轴超阈值/按键）→ 网络被抑制并上报 `remote_suppressed`。
- **网络接管条件**：仅当 FSM 处于 `RL_Locomotion`、网络使能（armed）、输入新鲜时接管 `x/y/yaw`；
  GetUp/GetDown/Passive 仍由本地/RC 触发；策略选择、Tomas 等仍走原有逻辑。
- **命令信封**：`magic/version/msg_type/seq/send_ts_ns/ttl_ms/source_id/flags(deadman/enable/estop)/crc32`；
  载荷 `x/y/yaw`（可扩展 pitch/height/gait）。TTL 100–300 ms；过期即零速。
- **失败安全**：网络超时 100–300 ms → 零速（计算层）；>1 s 或输入异常 → 补丁调用安全态
  （**新增** `ForceSafeDamping()`：kp=0/kd=8 立即生效，绕过 FSM 的 Locomotion→Passive 缺口）；
  同时请求 GetDown 作为后续动作。
- **E-stop**：新增真正的锁存安全态：立即阻尼 + 禁止运动命令 + 记录故障；必须显式复位
  （App 二次确认 + 机器人侧确认）。补丁前 App 急停只能映射到 `LB_X`（且仅在 GetUp 有效），
  因此**补丁是 E-stop 可用性的前提**。
- **状态回传**：
  - 优先复用 036_simple 的 UDP 12345 查询（22 B 请求/202 B 响应），但需补 CRC/版本；
  - 或在补丁内新增状态 UDP 帧（推荐，避免解析 036 私有格式）：FSM、armed、命令回显、最后 seq、
    超时计数、16 关节 q/dq/tau_est、IMU、策略号/模型、推理耗时、输出队列深度、RC 在线、故障位。
- **策略选择/切换**：网络可请求切换策略（0–4），但需安全条件（站立/低速）+ 确认；切换时清历史、
  动作平滑缓存、输出队列（复用 036 已有做法），并设置冷却时间。
- **补丁组织**：新增 `src/rl_sar/urc/`（`urc_input`、`urc_safety`、`urc_state`）；
  修改点限制在 `rl_sdk.hpp/cpp`、`rl_real_<robot>.cpp` 的 `RobotControl()`、CMake 选项；
  默认编译关闭、行为与上游一致；提供 `git format-patch` + rebase 脚本 + 兼容矩阵。

### L1（零补丁兜底）：虚拟手柄 / uinput

- 仅对“遥控输入走 `/dev/input/js*`”的机型与仿真有效；**036 真机不适用**（遥控来自 MCU）。
- Agent 创建 uinput 虚拟手柄，轴/按键布局与 `joystick` 库一致；处理权限、设备序号、多手柄、热插拔。
- 局限：无状态回传、设备名/权限脆弱，仅作仿真开发与兼容兜底。

### L2：ROS 2 桥接（rl_sar 以 ROS 2 运行 / 通用形态）

- 仿真：rl_sar 上游 ROS 仿真订阅 `/joy`，Agent 可用虚拟手柄或 `sensor_msgs/Joy` 注入。
- 真机（ROS 2 形态）：发布 `TwistStamped`/`Twist`、`AckermannDriveStamped`、
  `FollowJointTrajectory`/`Float64MultiArray` 等标准消息，订阅 `joint_states`/`robot_msgs`；
  需控制器自带超时（diff_drive 默认 0.5 s、Nav2 smoother 1 s、PX4 offboard 2 Hz proof-of-life）。
- 该路径不依赖 rl_sar 补丁，但不能替代 036 的 FSM 语义，需与 L0 配合或用于非 rl_sar 机器人。

### L3：仿真 / 数字孪生

- `rl_sim_mujoco` / Gazebo：Agent 通过虚拟手柄或补丁接入，用于 App 开发与回归。
- 用户已有的 `l4w4_sim2sim`（MuJoCo 扮 MCU、按真机 UDP 协议）可作为**数字孪生**：
  补丁运行在仿真侧，App 完全按实机路径连接，用于对抗测试（见 14 文档）。
- 仿真环境必须支持故障注入：丢包/延迟/重放/状态断流/推理卡顿/命令篡改/时钟偏移。

### L4（不推荐）：MCU 报文中间人

- 在 rl_sar 与 MCU 之间做 UDP 代理改写 `wirelessRemote`。依赖报文布局与时序、无状态回传，
  **仅用于测试注入，禁止作为产品路径**。

## 5. 能力描述派生（从 036/rl_sar 配置自动生成）

Agent 读取 `policy/<robot>/base.yaml`、`policy/<robot>/<config>/config.yaml` 与适配器配置，
生成 App 使用的 capability：

| 配置来源 | capability 字段 | 说明 |
|---|---|---|
| `num_of_dofs` / `joint_names` | `joints[]` | 训练顺序；与 `joint_mapping` 区分 |
| `dt` / `decimation` | `rates.servo_hz` / `rates.policy_hz` | 200 Hz / 50 Hz |
| `max_speed`（036）或源码硬编码（上游） | `channels[].range` | 036 默认 `[2.0, 1.0, 1.5]` |
| `torque_limits` / `rl_kp` / `rl_kd` / `action_scale` | `limits` / `safety.gains` | 显示与校验用，不替代内部限幅 |
| `model_name` / `p_*` 前缀 | `policies[]` | 0 默认 / 1 FS / 2 RS / 3 FAST / 4 Tomas |
| `observations` / `history` | `recording.schema` | 录制/回放校验 |
| FSM 源码/适配器配置 | `actions[]` | 站立/趴下/被动/策略选择/急停 |
| 036_simple 202 B 状态定义 | `telemetry` | 关节/IMU/电池/故障码 |
| `rl_sar_zoo/<robot>_description`（xacro/URDF） | `model` | 生成模型包；`joint_order` 取 `joint_names` 受控关节；见 15 文档 |

036 capability 示例（节选）：

```json
{
  "schema": "urc-capability/v1",
  "robot_id": "l4w4-036",
  "form": "wheeled_quadruped",
  "backend": "rl_sar",
  "rates": {"policy_hz": 50, "servo_hz": 200, "control_hz": 100},
  "policies": [
    {"id": 0, "name": "default"}, {"id": 1, "name": "FS"},
    {"id": 2, "name": "RS"}, {"id": 3, "name": "FAST"}, {"id": 4, "name": "Tomas"}
  ],
  "channels": [
    {"id": "body.linear_x", "range": [-2.0, 2.0]},
    {"id": "body.linear_y", "range": [-1.0, 1.0]},
    {"id": "body.angular_z", "range": [-1.5, 1.5]}
  ],
  "actions": [
    {"id": "action.get_up", "backend_key": "RB_A"},
    {"id": "action.locomotion", "backend_key": "RB_B"},
    {"id": "action.get_down", "backend_key": "LB"},
    {"id": "action.passive", "backend_key": "LB_X"},
    {"id": "action.estop", "backend_key": "PATCH_SAFE_DAMPING", "latched": true},
    {"id": "action.select_policy", "params": ["policy_id"]}
  ],
  "safety": {
    "watchdog_ms": 300, "estop_latched": true, "physical_rc_priority": true,
    "safe_state": "damping", "exit_motion": "get_down_then_passive"
  }
}
```

## 6. 数据录制与回放（为 RL 服务）

### 6.1 录制内容（统一时间轴，MCAP）

| 流 | 内容 | 频率 |
|---|---|---|
| `video/rgb` | H.264 分片（帧 PTS/关键帧） | 30/60 Hz |
| `depth` | 深度帧（Z16/压缩） | 5–15 Hz |
| `map` | 点云瓦片/占据栅格增量 | 按需 |
| `control` | App 控制帧（seq/ts/按键/轴/模式） | 100 Hz |
| `robot_state` | FSM、策略号、命令回显、关节 q/dq/tau_est、IMU、电池、故障 | 50 Hz |
| `model_state` | 根位姿 + 关节（驱动 URDF 模型） | 30–50 Hz |
| `fsm_events` | 状态切换事件与原因 | 事件 |
| `rc_state` | 物理 RC 状态（用于仲裁回放） | 200 Hz（可选） |

### 6.2 回放/导出

- `tools/mcap_export`：导出 CSV/HDF5；按 `observations`/`history` 还原观测布局，与训练侧对齐；
- `tools/replay_check`：时间戳单调、维度匹配、控制帧间隔、深度缺失检查；
- 时间同步：App/Agent 单调时钟；补丁输出自身时钟；录制器估计偏移写入元数据；
- 元数据：capability、rl_sar 版本/commit、分支（036_frs）、补丁版本、配置哈希、模型 SHA256、机器人序列号。

### 6.3 036 状态源

- 优先用补丁状态帧（字段可控、带版本/CRC）；若未部署补丁，可临时解析 036_simple 202 B 响应，
  但必须校验长度/字段、补 CRC（或容忍缺失）、统一字节序，禁止直接信任。

## 7. 安全与失败处理

| 场景 | 期望行为 |
|---|---|
| App 退出/断网 | 清零输入；100–300 ms 零速；>1 s 安全阻尼 + 请求 GetDown |
| 补丁进程崩溃 | 回退到“无远程输入”配置：RC 可用则 RC；否则 MCU 看门狗（约 2 s）强制下趴 |
| RC 介入 | RC 优先，网络被抑制并提示；不产生命令跳变（切换时清零/限斜率） |
| 策略卡顿/NaN/Inf | 补丁检测 → 安全阻尼；禁止自动恢复运动 |
| 状态断流 | PC 侧状态新鲜度检查；超时→安全态；日志区分“MCU 看门狗”与“补丁看门狗” |
| 双输入冲突 | 仲裁器保证单一来源；切换时清历史/队列/平滑缓存 |
| 急停 | 补丁安全态锁存；硬件急停最终兜底；视频/App 不在安全链上 |
| 配置/模型变更 | 启动校验；变更需确认并重启；版本不匹配拒绝运行 |
| 模型/状态不一致 | 不渲染运动、禁止关节命令、告警；控制安全逻辑不受影响（见 09 文档 I11） |

## 8. 版本兼容与上游策略

- `compat/rl_sar.md` 维护矩阵：上游 commit/tag、036 分支、补丁版本、测试结果。
- 补丁默认编译关闭；交付 `git format-patch` + rebase 脚本；优先向上游提交通用 `IUrcInput`。
- 036 分支已偏离上游（202 B 状态、策略选择、FSM 按键），补丁需同时适配两个基线，
  以 036 为实机验收目标、以上游为通用目标。
- 不改 rl_sar 默认行为；未启用远程输入时与基线一致。

## 9. 里程碑（rl_sar 部分）

| 阶段 | 内容 | 周期 |
|---|---|---|
| R0 | 补丁接口/信封/仲裁定稿；036 仿真回放（数字孪生） | 3–5 天 |
| R1 | 036 真机网络速度接管（RC 优先、TTL 零速、状态回传） | 1–2 周 |
| R2 | 安全态（damping/GetDown）、E-stop 锁存、状态新鲜度看门狗 | 1–2 周 |
| R3 | 策略选择/切换、录制 MCAP 与导出校验 | 1 周 |
| R3.5 | URDF 模型包（rl_sar_zoo）+ 状态回传对接 | 1 周 |
| R4 | 上游 PR + 兼容矩阵 + CI（固定 commit 构建） | 1 周 |
| R5 | 其他机型（js 虚拟手柄、ROS 2 桥接）与实机验收 | 1–2 周 |
