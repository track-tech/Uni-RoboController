# ADR-0012 通用命令接口（velocity / joint_* / cartesian / action）

- 状态：Accepted
- 日期：2026-11-18

## 背景

“任意四足/人形/轮足/机械臂”意味着不同机器人需要不同控制语义：
四足/人形/轮足通常以速度指令驱动 RL 策略；机械臂/人形臂需要关节或末端指令；
部分机器人提供站立/趴下/回零/夹爪等动作。不能只做 `cmd_vel`。

## 决定

- capability 的每个控制模式声明 `interface`：
  `velocity`、`joint_position`、`joint_velocity`、`joint_trajectory`、`cartesian_pose`、`action`；
- 每个 interface 定义自己的载荷通道/关节组/频率/限幅/死手要求；
- App 按 interface 生成 UI（摇杆/关节滑块/末端拖拽/动作按钮）；
- 适配器负责把通用命令翻译为机器人接口（rl_sar 速度、ROS 2 Twist/Ackermann/JointTrajectory、
  厂商 SDK），并对关节命令做 URDF 限位 + 适配器限幅双重校验；
- v1 实现 `velocity`、`action`、`joint_position`；`joint_trajectory`/`cartesian_pose` 在 v1.1。

## 理由

- 单一 `cmd_vel` 无法覆盖机械臂/人形臂；为每种形态硬编码 App 不可维护。
- 接口类型 + 能力描述让 App 通用、适配器专用；与 ROS 2 标准消息自然映射。
- 关节/末端接口风险更高，用死手 + 限幅 + 确认降低误操作。

## 后果

- 需要维护接口类型与 UI 生成逻辑；适配器实现量增加。
- `cartesian_pose` 需要机器人侧 IK/控制器支持；App 不做 IK（避免不可控运动）。

## 备选

- 只做速度接口（机械臂/人形臂不可用）。
- 为每种形态写专用 App 页面（不可扩展）。
