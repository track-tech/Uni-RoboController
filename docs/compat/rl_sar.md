# rl_sar 兼容矩阵

> 记录 rl_sar 基线、Uni-RoboController 补丁版本、验证结果。
> 详细设计见 [../13-rl-sar-bridge.md](../13-rl-sar-bridge.md)。

## 基线

| 基线 | 说明 | 状态 |
|---|---|---|
| `fan-ziqi/rl_sar`（上游 main） | 通用目标；L4W4/Go2 等 | 待接入 |
| `rl_sar-036_frs`（用户部署） | L4W4 四轮足；MCU `wirelessRemote` 遥控；200 Hz 控制/50 Hz 策略 | **首个真机目标** |
| `rl_sar-036_simple` | 036 简化版；含 UDP 12345 状态查询（22 B 请求/202 B 响应） | 状态通道参考 |

## 补丁版本

| 补丁版本 | 适用基线 | 内容 | 验证 |
|---|---|---|---|
| `urc-rl-sar-patch v0.1`（计划） | 036_frs | `UrcInput` 仲裁 + TTL 零速 + 状态回传 + 安全阻尼 | 待开发 |
| `v0.2`（计划） | 036_frs / 上游 | E-stop 锁存、状态新鲜度看门狗、推理超时、队列保护 | 待开发 |
| `v0.3`（计划） | 上游 | 通用 `IUrcInput`（PR 上游） | 待提交 |

## 已知差异/风险

- 036 的 `Locomotion→Passive` 在 FSM 中被注释 → 补丁必须提供 `ForceSafeDamping()`。
- 036 文档推荐的 `LB+RB` 急停未实现 → 补丁新增锁存急停。
- 036 的 202 B 状态响应无 CRC、字节序混用 → 优先使用补丁状态帧。
- 036 的 031 速度包代码保留但 socket 禁用 → 不复用，按本项目协议重新实现。
- 上游/036 的按键与策略选择差异 → 由适配器配置与 capability 描述吸收，App 不感知。
