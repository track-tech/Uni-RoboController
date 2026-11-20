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

- 帧头 32 B、小端、CRC-32/ISCSI（`0xE3069283` 校验串）；加密帧的 AAD 是**帧头且 crc 字段置 0**
  （不是含实际 crc 的帧头；按后者实现会解密失败）。
- HKDF 方向子密钥 + 12 B nonce（`dir+3B0+seq`）；**seq 每方向全局、跨流共享**；重放窗口每方向 2048；
  控制/遥测/地图必须加密。
- 认证门 fail-closed：明文仅允许 HELLO/HELLO_ACK/AUTH/AUTH_OK 与认证前 ERROR（0x0101/0x0103/0x0201/0x0602，限速）；
  其余帧必须已加密 + session 匹配 + 来源一致；未认证的 claim/CTRL/ESTOP/release/arm 一律丢弃并计数（gate_drop）。
- 会话超时 5 s；认证失败 5 次锁 30 s；单控制者；观察者只读；claim 不等于 arm，必须显式 arm。
- 控制帧 TTL 200 ms（接收侧排队时间）：过期丢弃；100 Hz 消费；重复帧去重；死手位为 0 时通道清零。
- **看门狗 300 ms → 零速**；**E-stop 锁存**；复位两步：`release_estop` 只清锁存，`arm` 重新使能；
  `ESTOP(reason=0)` 不清锁存；**仲裁优先级：硬件急停 > RC > 网络 > 自主**。
- 能力协商：`CAPS` 哈希、`client_caps` 降级、`joint_order_hash` 校验；不一致时拒绝运动渲染/关节命令。
- M0 mock 仅支持 rgb888 capability（否则拒绝启动）；非 rgb888 形态的 H.264/FEC 在 M2 实现。

### 4.2 视频

> M0 的 mock/参考服务端不实现 GStreamer/MediaCodec/H.264/FEC；仅发送 **RGB888 160×120@10** 测试图，
> 并在 capability `streams` 中如实声明（codecs=["rgb888"]）。真实视频链路（H.264/FEC/关键帧）在 M2 实现。

- 编码：H.264 优先（Baseline/Main），CBR、无 B 帧、GOP 1–2 s、关键帧带 SPS/PPS。
- 分片 ≤1200 B；每帧独立 `frame_id`；XOR FEC 1:8 起；`FEEDBACK` 请求关键帧。
- 接收端过期丢弃（>150 ms）；解码失败重建解码器。
- 参考编码器：x86 VAAPI/NVENC；ARM64 MPP/NV4L2；无硬编软编兜底并告警。

### 4.3 模型状态

- 关节顺序 = capability `model.joint_order`；`joint_order_hash = CRC32C(UTF-8(joint_order 以 "\n" 连接))`；
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
- 输出：控制台 + `cts-report.json`；P0 失败、skipped>0 或报告缺项均非零退出。
- **报告 schema（冻结）**：
  ```json
  {"schema":"urc-cts-report/v1","suite":"dynamic|static|arch","target":"...","started_at":"...",
   "cases":[{"id":"CTS-P-02","status":"passed|failed|skipped|xfail","duration_ms":0,"detail":""}],
   "summary":{"passed":0,"failed":0,"skipped":0,"xfail":0}}
  ```
- 用例必须用 `@pytest.mark.cts_id("CTS-...")` 标注；报告 hook 从 marker 取 ID。
- CI 必须断言：P0 ID 集合与 §6.2 完全一致、全部 `passed`、`skipped=0`、`xfail=0`。
- `CTS-K-01` 属于 `suite=arch`，由 `agent-aarch64` job 生成 `arch-report.json`；其余 P0 属于 `suite=dynamic`。
  `tools/check_cts_report.py` 校验两份报告的并集等于 12 个 P0 ID。

### 6.2 测试分组与用例（P0 完整清单，ID 冻结）

| ID | 级别 | 组 | 用例 | 期望 |
|---|---|---|---|---|
| CTS-D-01 | P0 | 发现 | 广播 DISCOVER→ANNOUNCE | 含 id/ports/caps_hash；无秘密；caps_hash 与 canonical 一致 |
| CTS-P-01 | P0 | 配对 | 错误秘密 ×5 | 锁定 30 s；锁定期正确 AUTH 仍 0x0602；仅该来源锁定 |
| CTS-P-02 | P0 | 配对 | 未认证 claim/CTRL/ESTOP/release_estop/arm | 全部无效果、无 armed/estop 事件、`gate_drop` 增加 |
| CTS-S-01 | P0 | 会话 | 第二控制者 claim | 0x0103；原会话不受影响 |
| CTS-S-02 | P0 | 会话 | 5 s 无有效帧 | 会话失效；EVENT 0x0004；清密钥；新 HELLO；锁存保留 |
| CTS-C-01 | P0 | 控制 | claim 后未 arm 的 CTRL；arm 后 100 Hz | 未 arm 不生效；arm 后回显一致 |
| CTS-C-02 | P0 | 控制 | TTL 过期帧 | 丢弃；不执行；`ttl_dropped` 计数 |
| CTS-C-03 | P0 | 控制 | 越界 axes/未知 mode | 拒绝 + 计数；不 clamp 放行 |
| CTS-S-03 | P0 | 安全 | 断链 300 ms | 零速；≤400 ms 停；CTRL 不自动 arm，action3 后恢复 |
| CTS-S-04 | P0 | 安全 | ESTOP | 锁存；estop_acked；ESTOP(0) 不解锁；release_estop 后仍需 arm |
| CTS-S-05 | P0 | 安全 | 重放/篡改控制包 | 100% 拒绝并计数；跨流 seq 复用（CTRL↔FEEDBACK）必须 replay_drop；Agent→App TELEM/VIDEO seq 全局递增 |
| CTS-K-01 | P0 | 跨架构 | x86_64/aarch64 向量 | 字节级一致；suite=arch 报告 |

> 级别：P0 = 发布/接实机门槛；P1 = 基础档完整；P2 = 增强档。

### 6.3 运行方式

```bash
# 静态组（CI 每次）
python -m pytest conformance -m static -q

# 动态组 A：CTS 自行启动 Python 参考服务端（默认）
python -m pytest conformance -m dynamic -q

# 动态组 B：CTS 自行启动 C++ mock（每个用例独立进程，支持注入参数）
URC_CTS_MOCK_BIN=agent/build/mock_robot \
URC_CTS_REQUIRE_EXTERNAL=1 \
python -m pytest conformance -m dynamic -q

# 动态组 C：连接已运行的外部 target（第三方实现；破坏性用例自动排除）
URC_CTS_TARGET=192.168.1.20:47800 \
URC_CTS_SECRET_FILE=/tmp/urc.secret \
URC_CTS_REQUIRE_EXTERNAL=1 \
python -m pytest conformance -m dynamic -q
```

- `URC_CTS_REQUIRE_EXTERNAL=1`：缺少 target/mock 直接失败，不允许静默回退 Python ref。
- `URC_CTS_MOCK_BIN` 模式按用例启动/停止 mock；注入用例通过 fixture 附加 `--hold-next-ms`/`--corrupt-aead` 等参数。
- `cts-report.json` 由 conftest hook 生成（路径 `URC_CTS_REPORT` 可覆盖），CI 断言 P0 ID 集合、全 passed、skipped=0、xfail=0；
  `target` 字段必须区分 `ref-server`/`mock`/外部 target，`duration_ms` 记录真实耗时。
- 跨架构 `arch-report.json` 由 `tools/gen_arch_report.py` 运行 `urc_vectors` 后生成（不得手写 passed）。
- 安全组默认只读/短时；涉及运动的用例必须显式 `--allow-motion`（对 mock/台架），防误伤实机。

### 6.4 通过标准

- **P0 全绿**（§6.2 全部 P0 项）：发现、未认证拒绝、配对/锁定、会话超时、单控制者、控制 TTL/越界、
  看门狗（含需重新 arm）、急停（含两步复位）、重放/篡改拒绝、跨架构向量。
- P1 全绿：遥测、视频、模型状态、故障注入冒烟；skipped=0；报告归档。
- P2 按增强档声明逐项通过。
- 任何 P0 失败禁止接实机；报告随 Release 归档。
- 项目自带的 mock/参考 Agent **必须**通过同一 P0 矩阵；否则视为参考实现不合格。

## 7. 服务端接入 Checklist

```
[ ] 实现 Level 0–3 并按 §2 清单自测
[ ] capability JSON 通过 Schema；能力声明与实际一致
[ ] 跑 CTS static + dynamic（mock 与真实各一次）；P0 全绿、skipped=0
[ ] 实机前：安全组（认证门/看门狗/急停两步复位/断链/重放）全绿
[ ] 声明与实发一致：CAPS 的 streams（编码/分辨率/帧率）与实际视频帧一致
[ ] 视频：720p30/1080p30 实测延迟/码率/关键帧恢复
[ ] 模型：URDF 包 hash/joint_order 校验；MODEL_STATE 与模型一致
[ ] 文档：填写实现说明（端口/加密/降级/已知限制）并在项目登记
```

## 8. 参考实现与生态边界

- 项目维护：协议、CTS、mock、最小参考 Agent、App。
- 社区/厂商维护：生产 Agent、机器人适配、rl_sar/ROS 2 示例、增强档实现。
- 任何第三方实现通过 CTS 后可登记到 `docs/compat/implementations.md`（待建），项目不为其质量背书。
