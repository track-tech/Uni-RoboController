# 18 协议实现指南与一致性测试（CTS）

> 项目定位（B 方案）：**标准协议 + Android 操作端 + 一致性测试 + mock/最小参考 Agent**。
> 机器人端生产实现由厂商/社区按本指南自行完成；项目只提供“最小参考 Agent”作为活文档，
> 并用 **CTS（Conformance Test Suite）** 保证各实现可互操作、安全语义一致。
> 协议细节以 [03-protocol.md](03-protocol.md) 为准；本文回答“怎么实现、怎么验收”。

## 1. 本文面向谁

| 角色 | 用法 |
|---|---|
| 机器人厂商/社区开发者 | 按 §3 分级实现，跑 §6 CTS 验收 |
| 项目维护者 | 维护 CTS、mock 与参考 Agent，防止协议碎片化 |
| App 开发者 | 用 mock + CTS 用例作为对端，验证客户端行为 |

## 2. 机器人端最小可用实现（MVP 清单）

一个“能被 App 正常发现、配对、控制、看到状态”的服务端，至少实现：

| # | 能力 | 必需 | 说明 |
|---|---|---|---|
| 1 | UDP 发现响应（`ANNOUNCE`） | ✅ | 广播/mDNS 响应；不含秘密 |
| 2 | 配对与认证（`AUTH`/`AUTH_OK`） | ✅ | QR/PIN 秘密；失败限速 |
| 3 | 会话（`HELLO`/`HELLO_ACK`/`SESSION_CTRL`） | ✅ | 单控制者、超时、重连窗口 |
| 4 | 能力描述（`CAPS`） | ✅ | capability JSON + 哈希；声明基础/增强档 |
| 5 | 控制（`CTRL`） | ✅ | 100 Hz 接收、TTL、死手、越界拒绝 |
| 6 | 遥测（`TELEM`） | ✅ | 20 Hz；含 `remote_age_ms`/`fault_flags` |
| 7 | 安全状态机（看门狗/急停/仲裁） | ✅ | 300 ms 零速、E-stop 锁存、RC 优先 |
| 8 | 反馈（`FEEDBACK`） | 基础档 | 视频统计/关键帧请求 |
| 9 | 视频（`VIDEO` + FEC） | 基础档 | H.264；分片/关键帧/SPS-PPS |
| 10 | 模型状态（`MODEL_STATE`） | 基础档（有 URDF 时） | 根位姿 + 关节；`joint_order_hash` |
| 11 | 管理 HTTP（info/caps/config/logs） | 基础档 | Token 认证 |
| 12 | 深度（`DEPTH`） | 增强档 | 可选；能力协商 |
| 13 | 地图（`MAP_*`） | 增强档 | 可选；体素瓦片/占据栅格 |
| 14 | 关节/笛卡尔命令 | 增强档 | 机械臂/人形臂 |

> “基础档”= v1 App 必须可用；“增强档”= v1.1 起按能力协商启用，缺失不影响基础档。

## 3. 分级实现路线（建议顺序）

```
Level 0 发现 + 配对 + 会话            （1–2 天）
Level 1 控制 + 遥测 + 安全状态机      （3–5 天）
Level 2 视频（H.264/FEC/关键帧）       （1–2 周，取决于硬件编码）
Level 3 模型状态 + URDF 模型包         （3–5 天，可复用 urdf_bundle）
Level 4 增强档：深度/点云/地图/关节命令（按需，1–4 周）
```

每级完成后跑对应 CTS 组；**P0 安全组必须全绿才能接实机**。

## 4. 关键实现要点（踩坑清单）

### 4.1 协议与安全

- 帧头 32 B、小端、CRC-32/ISCSI（`0xE3069283` 校验串）；加密帧的 AAD 是线上帧头**原样**。
- HKDF 方向子密钥 + 12 B nonce（`dir+3B0+seq`）；重放窗口 2048；控制/遥测/地图必须加密。
- 会话超时 5 s；认证失败 5 次锁 30 s；单控制者；观察者只读。
- 控制帧 TTL 200 ms：过期丢弃；100 Hz 消费；重复帧去重；死手位为 0 时通道清零。
- **看门狗 300 ms → 零速**；**E-stop 锁存**，显式复位；**仲裁优先级：硬件急停 > RC > 网络 > 自主**。
- 能力协商：`CAPS` 哈希、`client_caps` 降级、`joint_order_hash` 校验；不一致时拒绝运动渲染/关节命令。

### 4.2 视频

- 编码：H.264 优先（Baseline/Main），CBR、无 B 帧、GOP 1–2 s、关键帧带 SPS/PPS。
- 分片 ≤1200 B；每帧独立 `frame_id`；XOR FEC 1:8 起；`FEEDBACK` 请求关键帧。
- 接收端过期丢弃（>150 ms）；解码失败重建解码器。
- 参考编码器：x86 VAAPI/NVENC；ARM64 MPP/NV4L2；无硬编软编兜底并告警。

### 4.3 模型状态

- 关节顺序 = capability `model.joint_order`；`joint_order_hash` = CRC32(order)；
- MODEL_STATE 20–50 Hz；`(w,x,y,z)` 四元数；状态过期 >500 ms 客户端置灰；
- 模型包 `model.glb+model.json` 走 HTTP，SHA-256 校验；Agent 不在线执行 xacro。

### 4.4 常见互操作坑

| 坑 | 规避 |
|---|---|
| 大小端混用 | 全部按 03 文档；用 CTS 向量验证 |
| CRC32C 实现错误 | 用 `"123456789"→0xE3069283` 自检 |
| 加密后 nonce 重复 | 每方向 seq 单调；禁止复用 seq |
| 发现报文泄露秘密 | ANNOUNCE 只含公开信息 |
| 未配对可控制 | AUTH 前拒绝 CTRL/ESTOP |
| 双控制者 | SESSION_CTRL claim 冲突返回 0x0103 |
| 看门狗未接线 | CTS 安全组强制验证（断链 400 ms 内停） |
| 关节顺序与模型不一致 | 启动时校验 + CTS 用例 |
| 能力声明与实现不符 | CTS 检查 CAPS 与实际支持项一致 |

## 5. 最小参考 Agent（项目提供，非生产）

- 目标：单机器人形态、单相机、基础档；Linux x86_64/aarch64。
- 组成：`liburc_protocol`（C++ 协议内核）+ GStreamer 单相机 H.264 + mock 适配器（速度/动作）
  + 简化 URDF 模型状态 + HTTP 管理。
- 明确不含：多形态适配、rl_sar 补丁、完整 SLAM/点云、机械臂关节控制、生产级 OTA/多用户。
- 用途：作为协议“活文档”与 App 联调对端；厂商可 fork 后替换机器人适配层。

## 6. CTS（Conformance Test Suite）

### 6.1 形态

- 仓库位置：`conformance/`（Python + pytest），依赖 `protocol/vectors/` 与 `tools/codec_ref/`。
- 两种模式：
  - `static`：校验 capability JSON、Schema、测试向量、文档链接（CI 每次跑）；
  - `dynamic`：作为“客户端”连接被测服务端（mock 或真实 Agent），跑发现/配对/控制/安全组。
- 输出：控制台 + `cts-report.json` + 人读 Markdown；P0 失败即非零退出。

### 6.2 测试分组与用例（节选，完整清单随实现补充）

| ID | 级别 | 组 | 用例 | 期望 |
|---|---|---|---|---|
| CTS-D-01 | P0 | 发现 | 广播 DISCOVER→ANNOUNCE | 响应含 id/ports/caps_hash；无秘密 |
| CTS-D-02 | P1 | 发现 | 重复/伪造 ANNOUNCE | App 去重/提示；不自动信任 |
| CTS-P-01 | P0 | 配对 | 错误秘密 ×5 | 锁定 30 s；错误码 0x0602 |
| CTS-P-02 | P0 | 配对 | 未认证发 CTRL/ESTOP | 拒绝并计数 |
| CTS-S-01 | P0 | 会话 | 第二控制者 claim | 0x0103 或只读 |
| CTS-S-02 | P0 | 会话 | 5 s 无包 | 会话失效；看门狗独立生效 |
| CTS-C-01 | P0 | 控制 | CTRL 100 Hz 正常 | TELEM 命令回显一致 |
| CTS-C-02 | P0 | 控制 | TTL 过期帧 | 丢弃；不执行迟到命令 |
| CTS-C-03 | P0 | 控制 | 越界 axes/未知 mode | 拒绝 + 计数；不 clamp 放行（除非配置） |
| CTS-S-03 | P0 | 安全 | 断链 300 ms | 零速；≤400 ms 停；恢复需重新 arm |
| CTS-S-04 | P0 | 安全 | ESTOP | 锁存；estop_acked；控制被忽略 |
| CTS-S-05 | P0 | 安全 | 重放/篡改控制包 | 100% 拒绝并计数 |
| CTS-T-01 | P1 | 遥测 | 20 Hz TELEM | 字段完整；`remote_age_ms` 递推合理 |
| CTS-V-01 | P1 | 视频 | 关键帧/分片/FEC | 帧完整率 ≥ 阈值；丢中片整帧丢弃 |
| CTS-V-02 | P1 | 视频 | 关键帧请求 | ≤2 s 内恢复 |
| CTS-M-01 | P1 | 模型 | MODEL_STATE 30 Hz | `joint_order_hash` 匹配；插值正常 |
| CTS-M-02 | P1 | 模型 | 模型包哈希 | 下载校验失败拒绝加载 |
| CTS-F-01 | P1 | 故障注入 | 丢包 10%/延迟 50 ms | 控制安全；视频降级可恢复 |
| CTS-K-01 | P0 | 跨架构 | x86_64/aarch64 向量 | 字节级一致 |
| CTS-X-01 | P1 | 降级 | client_caps 无 video/depth | 服务端不推对应流；安全逻辑不变 |

> 级别：P0 = 发布/接实机门槛；P1 = 基础档完整；P2 = 增强档。

### 6.3 运行方式

```bash
# 静态组（CI 每次）
pytest conformance -m static --report cts-report.json

# 动态组（对 mock 或真实服务端）
pytest conformance -m dynamic --target 192.168.1.20:47800 --secret-file /tmp/urc.secret
# 对官方 mock
pytest conformance -m dynamic --target 127.0.0.1:47800 --secret-file /tmp/urc.secret
```

- `--target` 支持 `host:port` 与 `--discover`（走 mDNS/广播发现后连接）。
- 安全组默认只读/短时；涉及运动的用例必须显式 `--allow-motion`（对 mock/台架），防误伤实机。

### 6.4 通过标准

- P0 全绿：发现、配对、会话、控制 TTL、看门狗、急停、重放拒绝、跨架构向量。
- P1 全绿：遥测、视频、模型状态、故障注入冒烟。
- P2 按增强档声明逐项通过。
- 任何 P0 失败禁止接实机；报告随 Release 归档。

## 7. 服务端接入 Checklist

```
[ ] 实现 Level 0–3 并按 §2 清单自测
[ ] capability JSON 通过 Schema；能力声明与实际一致
[ ] 跑 CTS static + dynamic（mock 与真实各一次）
[ ] 实机前：安全组（看门狗/急停/断链/重放）全绿
[ ] 视频：720p30/1080p30 实测延迟/码率/关键帧恢复
[ ] 模型：URDF 包 hash/joint_order 校验；MODEL_STATE 与模型一致
[ ] 文档：填写实现说明（端口/加密/降级/已知限制）并在项目登记
```

## 8. 参考实现与生态边界

- 项目维护：协议、CTS、mock、最小参考 Agent、App。
- 社区/厂商维护：生产 Agent、机器人适配、rl_sar/ROS 2 示例、增强档实现。
- 任何第三方实现通过 CTS 后可登记到 `docs/compat/implementations.md`（待建），项目不为其质量背书。
