# 08 多形态机器人抽象与适配器

> 目标：一个 App 控制四足、轮式、机械臂、无人机等不同形态；新机器人只写“能力描述 + 适配器”，不改 App。
> 设计参考：VDA5050 的 factsheet/action 思路、ros2_control/LeRobot 的插件注册、Open-RMF 的 fleet adapter，
> 以及 ROS 2 标准消息（Twist/Ackermann/JointTrajectory）——但不照搬其复杂度。

## 1. 三层职责

```
能力描述 Capability（静态 JSON）   —— 机器人能做什么、命令/状态/限制/超时/安全动作
适配器 Adapter（Agent 插件）        —— 解析命令、调用机器人接口、采集状态、执行安全动作
仲裁/状态机（Agent 内核）           —— 本地急停 > RC > 网络 > 自主；模式/使能/看门狗
```

- **App 不硬编码任何机型**：根据 capability 生成控制界面、限幅、按钮与遥测字段。
- **适配器不直接处理网络**：只接收已校验的 `Command`，输出 `Telemetry` 与安全动作。
- **安全动作必须显式声明**：每个能力必须提供“零速/阻尼/下趴/急停”的映射，缺失则拒绝上机。

## 2. 能力描述 schema（`urc-capability/v1`）

```jsonc
{
  "schema": "urc-capability/v1",
  "robot_id": "l4w4-036",
  "name": "L4W4",
  "form": "wheeled_quadruped",       // quadruped | humanoid | wheeled_quadruped |
                                     // wheeled_diff | wheeled_ackermann | wheeled_omni |
                                     // manipulator | mobile_manipulator | drone | custom
  "vendor": "zhinao", "model": "l4w4",
  "frames": {"odom": "odom", "map": "map", "base": "base_link"},
  "transport": {"ctrl_port": 47800, "video_port": 47801, "depth_port": 47802, "map_port": 47803},
  "rates": {"control_hz": 100, "servo_hz": 200, "policy_hz": 50, "telemetry_hz": 20},
  "control": {
    "modes": [
      {"id": 0, "name": "rl_velocity", "interface": "velocity", "channels": [
        {"id": "body.linear_x", "range": [-2.0, 2.0], "deadband": 0.05},
        {"id": "body.linear_y", "range": [-1.0, 1.0], "deadband": 0.05},
        {"id": "body.angular_z", "range": [-1.5, 1.5], "deadband": 0.05}
      ], "deadman": true},
      {"id": 1, "name": "arm_joint", "interface": "joint_position",
       "groups": ["left_arm", "right_arm"], "rate_hz": 100, "deadman": true}
    ],
    "actions": [
      {"id": "action.get_up", "label": "站立", "risk": "medium", "hold_ms": 0},
      {"id": "action.get_down", "label": "趴下", "risk": "medium"},
      {"id": "action.passive", "label": "被动", "risk": "low"},
      {"id": "action.estop", "label": "急停", "risk": "high", "latched": true}
    ]
  },
  "limits": {
    "max_linear_speed": 2.0, "max_angular_speed": 1.5,
    "max_accel": 1.0, "max_yaw_accel": 2.0,
    "torque": [150, 150, 150, 30, "..."],
    "joint_ranges": [["..."]]
  },
  "timeouts": {"command_ttl_ms": 200, "watchdog_ms": 300, "state_stale_ms": 500},
  "safety": {
    "physical_estop": true,
    "rc_priority": true,
    "safe_state": "damping",          // zero | damping | get_down | custom
    "actions": {"zero": "PATCH_SAFE_ZERO", "damping": "PATCH_SAFE_DAMP",
                "get_down": "action.get_down"}
  },
  "telemetry": [
    {"id": "fsm_state"}, {"id": "battery"}, {"id": "joint_q"}, {"id": "imu"},
    {"id": "policy_name"}, {"id": "inference_ms"}, {"id": "faults"}
  ],
  "streams": [
    {"id": 0, "kind": "rgb", "codecs": ["h264"], "res": [1280, 720], "fps": [30, 60]},
    {"id": 1, "kind": "depth", "format": "z16", "res": [320, 240], "fps": [10, 15]}
  ],
  "map": {"capable": true, "voxel": 0.05, "tile": 4.0, "occupancy": true},
  "model": {
    "present": true,
    "bundle_hash": "sha256:....",
    "format": "glb+json/v1",
    "url": "/api/v1/model/ab12cd34.zip",
    "joint_order": ["FL_hip_joint", "..."],
    "joint_order_hash": 123456789,
    "base_link": "base_link",
    "root_frame": "odom",
    "dof": 16
  },
  "policies": [{"id": 0, "name": "default"}],
  "plugins": {"adapter": "rl_sar", "version": "1.0"}
}
```

规则：

- `channels[].id` 使用规范通道名（见 §3）；未知通道必须忽略（向前兼容）。
- `range` 是**硬限幅**；App 与 Agent 双重 clamp；适配器再做第三次校验。
- `actions[].risk` 决定 UI 确认方式（low 直接、medium 长按 500 ms、high 二次确认）。
- `safety.actions` 缺失 → capability 校验失败，拒绝加载。
- `model` 可选；有模型时 `joint_order` 必须与 `MODEL_STATE` 一致（见 15 文档），
  `joint_order_hash` 用于快速校验；模型包通过 HTTP 下载并按哈希缓存。
- 能力 JSON 通过 CAPS 下发并带哈希；App 缓存；变更时重新协商。

## 3. 规范通道注册表（v1）

| 类别 | 通道 | 单位 | 说明 |
|---|---|---|---|
| 底盘 | `body.linear_x` / `body.linear_y` / `body.angular_z` | m/s, m/s, rad/s | 默认移动通道 |
| 底盘 | `body.height` / `body.pitch` / `body.roll` | m, rad, rad | 轮足/人形可调姿态 |
| 底盘 | `body.steer` | rad | 阿克曼转向角 |
| 步态 | `gait.type` / `gait.speed` | enum/float | 步态/速度档 |
| 机械臂 | `arm.joint[i]` / `arm.cartesian.{x,y,z,rx,ry,rz}` | rad / m, rad | 关节或笛卡尔 |
| 末端 | `gripper.position` / `gripper.force` | 0–1 / N | 夹爪 |
| 云台 | `head.pan` / `head.tilt` / `camera.zoom` | rad / 倍率 | 相机 |
| 无人机 | `flight.throttle` / `flight.yaw` / `flight.pitch` / `flight.roll` | 归一化 | 后续 |
| 通用 | `vendor.<name>` | 自定义 | 厂商扩展，App 不解释，仅透传/显示 |

## 4. 命令模型与生命周期

```cpp
struct Command {
  uint32_t seq; uint64_t ts_us; uint32_t mode;
  uint8_t flags;                 // deadman/estop/mode_change
  std::array<int16_t, 16> axes;  // 按 capability 顺序
  std::array<uint32_t, 2> buttons;
};
```

- App 以 100 Hz 发送；Agent 校验：会话、角色、模式、范围、TTL、死手、急停锁存；
- 通过 → 适配器 `apply_command()`；拒绝 → 计数 + 限速日志 + 可选 ERROR；
- 模式切换：需 `flags.mode_change` + 冷却 + 适配器确认；切换时清零积分/平滑/队列；
- 仲裁优先级：**本地硬件急停 > RC 本地 > 网络 > 自主/导航**；切换来源时清零并限斜率；
- 任何来源失联 → 回落到安全态，**不锁存最后命令**。

### 4.1 命令接口类型（`control.modes[].interface`）

| interface | 载荷 | 适用形态 | 说明 |
|---|---|---|---|
| `velocity` | vx, vy, wz（可选 height/pitch） | 四足/人形/轮足/轮式（经 RL 策略或底盘控制器） | 默认移动接口 |
| `joint_position` | 关节组 + 目标角 | 机械臂/人形臂/灵巧手 | 限幅来自 URDF；需死手 |
| `joint_velocity` | 关节组 + 速度 | 云台/轮子/简单臂 | 限速 |
| `joint_trajectory` | 关节名+点+时间 | 机械臂 | 转发 `FollowJointTrajectory` |
| `cartesian_pose` | x,y,z,rx,ry,rz | 机械臂末端 | 由机器人侧 IK/控制器解算；v1 不在 App 端做 IK |
| `action` | 动作 ID + 参数 | 所有形态 | 站立/趴下/回零/夹爪/策略切换 |

- `groups` 定义关节分组（`left_arm`/`right_arm`/`head`/`legs`…），来自 URDF 树或适配器配置；
- App 根据 interface 生成 UI：摇杆（velocity）、关节滑块（joint_*，限位来自 URDF）、
  末端拖拽（cartesian，可选）、动作按钮（action）；
- v1 优先实现 `velocity` + `action` + `joint_position`；`joint_trajectory`/`cartesian` 在 v1.1。

## 5. 适配器接口（C++）

```cpp
class IRobotAdapter {
public:
  virtual ~IRobotAdapter() = default;
  virtual Capability capability() const = 0;
  virtual bool init(const YAML::Node& cfg, Error* err) = 0;   // 启动自检
  virtual void apply_command(const Command& cmd) = 0;          // 控制周期调用
  virtual Telemetry telemetry() = 0;                           // 摘要状态
  virtual ModelState model_state() = 0;                        // 关节/根位姿（驱动 URDF）
  virtual ModelMeta model_meta() = 0;                          // 模型包来源/哈希/joint_order
  virtual void safe_action(SafeAction action) = 0;             // zero/damping/get_down/estop
  virtual void on_mode_change(uint32_t mode) = 0;
  virtual Health health() const = 0;
};
```

- `model_meta()` 由适配器声明 URDF 来源（路径/内嵌/预置包）；Agent 负责转换为模型包并对外提供。
- `model_state()` 输出顺序必须等于 `capability.model.joint_order`（或 `capability.joints` 顺序）。

适配器注册：静态注册表 + 配置文件 `adapter: <name>`；可选动态库插件（ABI 版本化）。
适配器不得直接读网络；不得阻塞超过一个控制周期；内部线程需报告健康状态。

## 6. 参考适配器

| 适配器 | 机器人 | 关键实现 |
|---|---|---|
| `rl_sar`（主） | 036 L4W4、上游 rl_sar 机型（Go2/Go2W/G1 等四足/轮足/人形） | 网络输入注入补丁 + 状态回传；RC 优先；URDF 取自 rl_sar robot description；见 13 文档 |
| `ros2_base` | 差速/全向/阿克曼底盘 | 发布 `TwistStamped`/`Twist`、`AckermannDriveStamped`；订阅 `odom`/`joint_states`；依赖控制器超时（diff_drive 0.5 s、Nav2 smoother 1 s） |
| `ros2_manipulator` | 机械臂/人形臂 | `FollowJointTrajectory`（轨迹）或 `Float64MultiArray`（伺服）；可选 MoveIt 2 Servo；限位来自 URDF |
| `custom_mcu` | 自定义 UDP/CAN 机器人 | 加载协议描述（字段/字节序/CRC）；参考 L4W4 的 031/102 B 帧 |
| `mock` | 开发/测试 | 模拟所有形态与故障注入；内置示例 URDF；CI 默认 |
| `mavlink`（后续） | PX4 无人机 | MAVLink offboard；必须 >2 Hz proof-of-life；RC override 优先 |

## 6.1 形态与命令/模型对照

| 形态 | 典型 DOF | 主要命令接口 | URDF 状态 |
|---|---|---|---|
| 四足 | 12–16 | velocity + action | 浮动基座 + 关节 |
| 轮足 | 16–20（含轮） | velocity（+height/pitch）+ action | 浮动基座 + 关节/轮速 |
| 人形 | 20–50+ | velocity（RL）+ joint_position（臂/手）+ action | 浮动基座 + 关节 + 手 |
| 机械臂 | 6–7 + 夹爪 | joint_position/trajectory/cartesian + action | 固定基座 + 关节 |
| 移动机械臂 | 底盘 + 臂 | velocity + joint_position/cartesian | 浮动/固定基座 |

## 7. 形态 → 默认 UI 映射

| 形态 | 左摇杆 | 右摇杆 | 扳机/按钮 | 默认动作 |
|---|---|---|---|---|
| `wheeled_quadruped` | 前后/横移 | 偏航 | 扳机=速度档 | 站立/趴下/被动/RL 运动 |
| `wheeled_diff` | 前后 | 偏航 | 扳机=加速 | 使能/急停 |
| `wheeled_ackermann` | 速度 | 转向 | 侧键=换挡 | 使能/急停 |
| `manipulator` | 末端 XY | 末端 Z/旋转 | 扳机=夹爪 | 使能/回零/急停 |
| `mobile_manipulator` | 底盘 | 机械臂/云台 | 扳机=夹爪 | 底盘/臂切换 |
| `drone`（后续） | 油门/偏航 | 俯仰/横滚 | 侧键=模式 | 解锁/起飞/降落/急停 |

- 默认 profile 随 capability 的 `form` 生成；用户可改映射，保存到本地。
- 高风险动作（站立/解锁/起飞）长按或二次确认；急停永远一键。
- 多手柄：槽位 0=移动，槽位 1=云台/机械臂；UI 明确当前槽位与来源。

## 8. 能力协商与版本

- App 握手后接收 CAPS；校验 schema 版本、必需字段、安全动作完整性；
- 不兼容 → 提示升级，不进入控制页；可只读（视频/遥测）连接；
- 能力变更（换模型/改参数）→ EVENT + 重新拉取；控制中不接受静默变更；
- 适配器版本与协议版本写入 capability，便于问题定位与灰度。

## 9. 扩展流程（新机器人接入清单）

1. 选择适配器类型（rl_sar / ROS 2 / custom / mock）；
2. 准备 URDF/xacro（或已有模型），用 `tools/urdf_bundle` 生成模型包；
3. 编写 capability JSON（通道/接口/动作/限幅/超时/安全动作/模型元数据）；
4. 实现/配置适配器（命令映射、`model_state()` 状态采集、安全动作）；
5. 离线单测：限幅、模式、看门狗、急停、关节顺序；
6. 仿真/数字孪生联调（含模型状态同步）；
7. 台架低速 → 实机；
8. 对抗验证用例（见 14 文档）通过后纳入支持列表。
