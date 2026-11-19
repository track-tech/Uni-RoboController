# Stage S1 Brief — C++ `mock_robot`（Rev.3，待窄范围复审 Round 2b）

| 项 | 值 |
|---|---|
| 阶段 | S1 |
| 状态 | **Draft Rev.3（回应 Round 2 的 5 个 P0 / 27 个 P1）** |
| 作者 | root/lead |
| 日期 | 2026-11-20 |
| 变更 | 补消息线上格式/明文例外/会话超时统一/CTS 报告 schema/P0 ID；补状态机边界、重放顺序、锁定 per-源；补 ASAN-CTS/SIGTERM/WERROR/CI 规格；交付 soak.py/client/proto |
| 依赖 | S0 评审流程、`liburc_protocol`、`protocol/vectors`、`conformance` |

> **优先级**：Rev.3 的 §12 覆盖并优先于前文冲突段落；前文保留作为上下文。

## 0. Rev.2 变更摘要（相对 Rev.1）

1. **AAD 冻结**为“帧头且 crc=0”，回写 03/18；加入“错误 AAD 必须失败”负向量。
2. **seq 冻结**为“每方向全局、跨流共享”，重放窗口每方向；回写 02/03。
3. **认证门 fail-closed**：除 HELLO/AUTH 外全部要求加密+session+来源一致；未认证 claim/CTRL/ESTOP 丢弃并计数。
4. **状态机**：CLAIMED ≠ ARMED；必须显式 `arm`；看门狗/急停后不得由普通 CTRL 自动 arm。
5. **急停两步复位**：`release_estop` 只清锁存，`arm` 再使能；`ESTOP(0)` 不清锁存。
6. **POSIX-only**（Linux/CI 权威；Windows 开发用 Python ref server），移除 Winsock 承诺。
7. **单端口多流**：v1 全部实时流走 ctrl 端口，`stream` 区分；video/depth/map 端口预留。
8. **P0 CTS 矩阵**（18 §6.2 全部 P0）+ skipped=0 + 统计断言 + 变异检查；外部 target 改为 per-test mock。
9. **注入重构**：`--hold-next-ms`（一次性 TTL）、`--corrupt-aead`（翻转密文并重算 CRC）、`--seed`、`--stats-file`。
10. **参考实现同步**：`ref_server.py` 与 mock 共享冻结语义，默认 CTS 仍可对 Python ref 跑通。
11. **消息补全**：C++ 补 SESSION_CTRL/ESTOP/EVENT/ERROR/VIDEO/PONG 编解码与向量。
12. **CI**：mock-integration、asan、soak（dispatch/`[soak]`）、aarch64 构建 APP + `--help` 冒烟。

## 1. 目标与成功标准

实现官方 C++ `mock_robot`，复用 `liburc_protocol`，作为 App/CTS 默认对端：

- 通过 **18 §6.2 全部 P0 用例** + P1 组（遥测/视频/模型/故障注入），skipped=0；
- 与同步后的 Python `ref_server` 跑同一套 CTS 均通过（D5 成立）；
- 提供可复现故障注入与统计文件；
- CI：`mock-integration`、`asan`、`soak`（手动/dispatch）、aarch64 构建通过；
- 30 min 浸泡：RSS 增长 <1 MB/h、fd 不增长、看门狗不误触发、注入计数符合预期。

## 2. 范围

### 2.1 新增/修改（实现阶段）

```
agent/
├── CMakeLists.txt                 # urc_server 库、mock_robot、测试、URC_BUILD_APPS
├── include/urc/net.h              # POSIX UDP 抽象
├── src/net.cpp
├── include/urc/server.h           # ServerConfig / MockServer / 统计
├── src/server/{config,session,control,telemetry,video,discovery,server}.cpp
├── include/urc/messages.h         # 补 SESSION_CTRL/ESTOP/EVENT/ERROR/VIDEO/PONG
├── src/messages.cpp
├── apps/mock_robot.cpp
├── config/mock.json               # 示例 JSON 配置
└── tests/{test_vectors.cpp,test_server.cpp}
conformance/conftest.py            # URC_CTS_MOCK_BIN / REQUIRE_EXTERNAL / stats/report
conformance/test_protocol.py       # P0 矩阵扩展 + 可证伪断言
tools/codec_ref/
├── urc_ref/messages.py            # 补/核对消息编解码
├── gen_vectors.py                 # 新消息向量
└── ref_server.py                  # 同步冻结语义 + stats
protocol/vectors/{frames,crypto,frag,session}.json（重新生成）
protocol/examples/capability.mock_quadruped.json（rgb888 160×120@10）
docs/02,03,04,07,09,16,18        # 已回写 AAD/seq/认证门/arm/急停/单端口/视频/CTS
.github/workflows/ci.yml           # mock-integration / asan / soak / aarch64 app
.gitignore                         # build*/、artifacts/
```

### 2.2 非目标

- 不实现 GStreamer/MediaCodec/真实相机、FEC parity、HTTP 管理接口、深度/点云/地图、多形态适配、rl_sar。
- 不实现 Windows 网络（POSIX-only）；Windows 本地开发使用 Python ref server。
- 不实现生产级认证/密钥管理；M0 只验证协议/安全语义。

## 3. 行为规格（冻结）

### 3.1 CLI / 配置

```
mock_robot --bind 127.0.0.1 --ctrl-port 47800 --discovery-port 47810 \
  --capability protocol/examples/capability.mock_quadruped.json \
  --secret-file /tmp/urc.secret [--config agent/config/mock.json] [--no-camera] \
  [--drop P] [--hold-next-ms N] [--corrupt-aead P] [--stale-state] [--seed N] \
  [--stats-file path] [--watchdog-ms 300] [--ctrl-ttl-ms 200] [--session-timeout-ms 5000] [--verbose]
```

- 配置 JSON 优先级：默认 < `--config` < CLI；未知字段拒绝启动（英文错误）；秘密文件不存在则生成并打印 `URCPAIR:`（CI 预生成避免日志泄密）。
- 统计文件：JSON；每 500 ms 与退出时写入；字段见 §7。

### 3.2 认证门（fail-closed）

- 仅有 `HELLO`/`AUTH` 允许明文；其余帧必须 `flags.encrypted=1`、`session_id` 匹配、来源地址为当前会话。
- 未认证/加密失败/会话不匹配：丢弃 + 计数；不得返回状态、不得执行、不得触发 armed/estop 事件。
- 明文 `claim`/`CTRL`/`ESTOP`/`release_estop` 一律无效（CTS-P-02 必须覆盖）。
- 认证前 ERROR 仅允许 `0x0101`/`0x0103`/`0x0602` 的极小响应；限速 ≤2 次/秒/来源。

### 3.3 状态机

```
DISCONNECTED --HELLO--> PENDING --AUTH_OK--> AUTHENTICATED
AUTHENTICATED --claim--> CLAIMED --arm--> ARMED --CTRL--> ARMED(Moving)
ARMED --watchdog--> ARMED=false（EVENT 0x0002，零速）
ANY --ESTOP(≠0)--> ESTOP_LATCHED（zero；CTRL 忽略）
ESTOP_LATCHED --release_estop--> AUTHENTICATED/CLAIMED（仍 disarmed）
--arm--> ARMED
```

- `claim` 只授予控制权，不 arm；`SESSION_CTRL(arm)` 才接受 CTRL。
- 看门狗触发后 `armed=false`；普通 CTRL 不得自动 arm；必须 `arm`。
- `release` 释放控制权并 disarmed；`release_estop` 只清锁存；`arm` 仅当前控制者。
- 会话超时：清 claimed/armed/peer/方向密钥；**ESTOP 锁存保留**；需新会话 `release_estop`+`arm`。
- 已存在控制者时，其他来源 HELLO → 明文 ERROR 0x0103（限速），不允许覆盖会话。
- 单控制者；viewer 返回不支持。

### 3.4 CTRL / TTL / 看门狗

- 接受条件：已认证+已 claim+已 arm+未锁存+TTL 有效+模式/轴数/范围合法。
- 轴缩放：优先 `channel.scale`，否则 `max(|lo|,|hi|)`；越界拒绝（ERROR 0x0301 限速 ≤1/s），不 clamp。
- 死手 bit0=0 → 轴清零；合法 CTRL（含死手释放）刷新看门狗。
- **TTL**：接收时刻记录；`--hold-next-ms` 扣住下一帧 N ms 后再处理；排队年龄 > TTL → 丢弃、`ttl_dropped++`、不刷新看门狗、不执行。
- **看门狗**：armed 状态下 >300 ms 无“有效 CTRL” → 零速、disarmed、`fault_flags.bit0`、EVENT 0x0002（每轮一次）。
- CTRL flags.bit1 保留（置 0）；急停只走 ESTOP。

### 3.5 急停

- `ESTOP(reason≠0)`：锁存、零速、disarm、EVENT 0x0001；重复发送按 flags bit4；控制忽略。
- `ESTOP(reason=0)`：**无效果**（不清锁存、不 arm）。
- 复位：`SESSION_CTRL(release_estop)` 清锁存（仍 disarmed）→ `SESSION_CTRL(arm)` 后 CTRL 才生效。
- 锁存跨会话超时保留；只有显式 release 才清除。

### 3.6 发现/认证/会话细节

- DISCOVER→ANNOUNCE：含 robot_id/name/form/ports/caps_hash/pair_state；不含秘密；限速。
- HELLO_ACK：session_id/robot_nonce/ports；capability mock 的 streams 与实际发送一致。
- AUTH：per-来源 5 次失败锁 30 s；锁到期后可重试；成功清零。
- 重放：每方向窗口 2048；重复/过旧丢并计数；AEAD 失败丢并计数；两者均不回显。
- CAPS：canonical JSON（sort_keys/紧凑/UTF-8），`caps_hash=SHA-256(canonical)[:4]`；分片 mtu=1190、msg_id=0x1000、encoding=0。
- 会话 5 s（可配）；TELEM/MODEL_STATE/VIDEO 停发；不解锁急停。

### 3.7 遥测/模型/视频

- TELEM 20 Hz：seq/ts/fsm_state/fault_flags/battery/x/y/yaw/policy/remote_age_ms（无控制时 9999）。
- MODEL_STATE 30 Hz：joint_count/order_hash 来自 capability；根位姿固定 + 正弦关节；`--stale-state` 停发。
- VIDEO 10 Hz：160×120 RGB888 渐变；23 B 头；分片 ≤1190 B；bit0 IDR、bit2 末片；无 FEC；
  capability `streams` 必须声明 rgb888/160×120/10，CTS 断言 CAPS 与实发一致。
- 所有实时流走 ctrl 端口；`stream` 字段区分。

### 3.8 故障注入与可复现

| 参数 | 行为 | 统计/断言 |
|---|---|---|
| `--drop P` | 出站包按 seeded PRNG 丢 P% | `dropped_tx` |
| `--hold-next-ms N` | 收到下一帧后延迟 N ms 处理（一次性） | `ttl_dropped`（若超 TTL），无动作 |
| `--corrupt-aead P` | 加密出站帧翻转密文中 1 字节并重算 CRC（强制 AEAD 失败） | `corrupt_tx`，对端 `aead_fail` |
| `--stale-state` | 停发 MODEL_STATE | App/CTS 过期检测 |
| `--seed N` | 注入/丢包确定性序列 | 复现 |

## 4. 设计决定（Rev.2）

| # | 决定 | 理由 |
|---|---|---|
| D1 | 单线程 `select` 事件循环 + 单调时钟定时器 | 确定性、无锁；mock 非性能目标 |
| D2 | **POSIX-only** UDP；Windows 用 Python ref server | 消除未覆盖的 Winsock 分支与 CI 缺口 |
| D3 | 配置 JSON（nlohmann），M0 不引入 yaml-cpp | 少依赖；07 已注明 |
| D4 | 复用 `liburc_protocol`，补全消息编解码与向量 | 防双实现漂移 |
| D5 | CTS 支持 `URC_CTS_MOCK_BIN`（per-test 启动 C++ mock）、`URC_CTS_TARGET`（外部只读）、`URC_CTS_REQUIRE_EXTERNAL=1` | 真实验证、隔离、不假绿 |
| D6 | 认证门 fail-closed；claim≠arm；两步急停复位 | 安全语义明确、可测 |
| D7 | TTL 用接收后排队时间 + 一次性 hold 注入 | 跨设备无同步时钟且可证伪 |
| D8 | 视频仅 RGB888 测试图、无 FEC；capability 如实声明 | M0 范围；避免 App 误配 H.264 |
| D9 | 单端口多流 | 无需在握手中交换客户端端口；便于统一加密/重放 |

## 5. CTS 设计与 P0 矩阵

### 5.1 模式

- 默认：每用例启动 Python `ref_server`（现有行为）。
- `URC_CTS_MOCK_BIN=<path>`：每用例启动独立 C++ mock（随机端口/临时秘密），支持注入 fixture 参数；
  `URC_CTS_REQUIRE_EXTERNAL=1` 时缺 mode 直接失败。
- `URC_CTS_TARGET=host:port`：外部已运行 target（第三方实现），只跑非破坏性用例。
- 报告：conftest hook 输出 `cts-report.json`；CI 断言 `skipped=0`、P0 全绿。

### 5.2 必测 P0（对应 18 §6.2）

| 用例 | 新增/加强断言 |
|---|---|
| CTS-D-01 | ANNOUNCE 含 caps_hash、无秘密；与 CAPS canonical 一致 |
| CTS-P-01 | 错秘密 ×5 → 锁定；锁定期正确 AUTH 仍 0x0602 |
| CTS-P-02 | 未认证 claim/CTRL/ESTOP/release_estop/arm 全部无效果、无 armed/estop 事件、`gate_drop` 增加 |
| CTS-S-01 | 第二控制者 0x0103；原会话不受影响 |
| CTS-S-02 | 超时后：停发 TELEM/MODEL/VIDEO；旧 session 帧丢弃并 `sessions_expired++`；新 HELLO+AUTH；急停锁存保留 |
| CTS-C-01 | 控制回显正确；claim 后未 arm 时 CTRL 不生效 |
| CTS-C-02 | `--hold-next-ms 250` + TTL 200：`ttl_dropped=1`、无动作、watchdog 未触发 |
| CTS-C-03 | 越界/未知 mode 拒绝、限速；不 clamp、不运动 |
| CTS-S-03 | 断链 300 ms：EVENT/零速；CTRL 不自动 arm；action3 后恢复 |
| CTS-S-04 | ESTOP 锁存；ESTOP(0) 不解锁；release_estop 后仍需 arm |
| CTS-S-05 | 重放/AEAD 篡改 100% 拒绝并计数；无状态变化 |
| CTS-K-01 | 跨架构向量（已有） |

P1：遥测、视频（CAPS 一致性 + 重组）、模型状态、注入冒烟。

### 5.3 参考实现同步

`ref_server.py` 同步：认证门、claim/arm、两步复位、ESTOP(0) 无效果、会话超时（清密钥）、TTL（hold 注入）、
stats 文件、capability rgb888；**CLI 参数与 mock 同名同义**：`--watchdog-ms/--ctrl-ttl-ms/--hold-next-ms/
--drop/--corrupt-aead/--seed/--stale-state/--stats-file/--no-camera`。默认 `cts` job 对 ref 跑；
`mock-integration` 对 C++ mock 跑；两者使用同一套测试与同一报告检查。

## 6. CI / 验收

### 6.1 CI 变更

| job | 内容 |
|---|---|
| `cts` | 默认 Python ref；P0 全绿；skipped=0；上传 `cts-report.json` |
| `mock-integration` | 构建 `mock_robot`；`URC_CTS_MOCK_BIN` 跑全部动态组；随机端口；失败上传日志 |
| `mock-asan` | `-fsanitize=address,undefined` 构建 + ctest |
| `mock-soak` | `workflow_dispatch` 或 commit 消息含 `[soak]`；30 min；解析 stats/RSS/fd；失败上传 |
| `agent-aarch64` | `-DURC_BUILD_APPS=ON`；QEMU `mock_robot --help` 冒烟 |
| `lint/vectors` | 不变；新增消息向量检查 |

### 6.2 验收命令

```bash
cmake -S agent -B agent/build -DURC_BUILD_APPS=ON -DCMAKE_BUILD_TYPE=Release
cmake --build agent/build -j
ctest --test-dir agent/build --output-on-failure

# C++ mock 全量 CTS（per-test 启动）
URC_CTS_MOCK_BIN=agent/build/mock_robot URC_CTS_REQUIRE_EXTERNAL=1 \
  python -m pytest conformance -m dynamic -q

# 注入专项
URC_CTS_MOCK_BIN=agent/build/mock_robot URC_CTS_REQUIRE_EXTERNAL=1 \
  python -m pytest conformance -m dynamic -k "injection or ttl or corrupt or replay" -q

# ASAN
cmake -S agent -B agent/build-asan -DURC_BUILD_APPS=ON \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer"
cmake --build agent/build-asan -j && ctest --test-dir agent/build-asan --output-on-failure

# 浸泡（30 min）
python tools/soak.py --bin agent/build/mock_robot --duration 1800 --drop 5 --rate 100
```

### 6.3 浸泡判定

- 起始后 60 s 采样为基线；RSS 增长 <1 MB/h，fd 增量 ≤2，线程数不变；
- `watchdog` 不因注入误触发（仅断链测试触发）；`dropped_tx` ≈ 注入比例 ±20%；
- 结束 SIGTERM，汇总 `URC_STATS` 与 stats JSON；退出码 0；无 ASAN 报告。

### 6.4 变异检查（审计）

预登记 6 个 mutant，任一未被测试捕获即审计失败：

1. 关闭 CRC 校验；2. 关闭认证门；3. 关闭 TTL；4. 关闭看门狗 arm 门槛；
5. `ESTOP(0)` 解锁；6. 关闭 replay 窗口。

## 7. 可观测性

- `--stats-file` JSON（每 500 ms + 退出）：
  `rx_frames, tx_frames, rx_drop, gate_drop, auth_fail, lockout, replay_drop, aead_fail, ttl_dropped, invalid_ctrl, watchdog, estop, sessions_expired, dropped_tx, corrupt_tx`。
- 退出打印单行 `URC_STATS {...}`；不记录秘密/密钥/明文载荷。
- `--verbose` 打印状态转换与原因；日志英文。

## 8. 回滚

- 仅新增 `agent/` 代码、cts 扩展、CI job 与文档；不修改现有协议库公开语义（除补全消息）。
- 失败时禁用 `mock-integration`/`mock-asan`/`mock-soak`，保留 Python ref 作为 CTS 目标；`urc_vectors` 始终可回归。

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 冻结语义改动影响已有 CTS/ref | 先改 ref + 测试，再改 mock；默认 cts job 持续验证 |
| `--hold-next-ms` 阻塞单线程定时器 | 仅测试注入、上限 500 ms；TTL 判定先于定时器补偿；专项测试 |
| 状态机/会话清理竞态 | 显式状态转换 + 单元测试 + 审计变异 |
| CAPS/视频声明漂移 | CTS 断言 CAPS↔实发；capability 改为 rgb888 |
| CI 时间（Soak/ASAN） | soak 仅手动/dispatch；ASAN 单 job；缓存 |
| Windows 本地无法跑 C++ mock | 明确 POSIX-only；Windows 用 Python ref；CI 权威 |

## 10. 已解决/待评审确认的问题

1. AAD/seq 已冻结并回写 02/03/18。
2. 认证门/claim-arm/急停两步复位已冻结并回写 03/09/18。
3. TTL 采用 hold 注入 + stats 断言；`--hold-next-ms` 是否可接受？
4. POSIX-only + 单端口多流是否接受？（拒绝则需 Windows CI 与客户端端口握手机制）
5. `ref_server` 同步改动是否在 S1 范围内？（当前：是）
6. CTS per-test C++ mock 是否足以替代共享 target 的真实性？（另保留 `URC_CTS_TARGET` 只读模式）

## 11. Gate 证据

- 第二轮 4 份评审报告：P0=0；P1 关闭或用户接受；
- Brief Rev.2 与 docs 02/03/09/18 的最终 diff；
- `stage-S1-gate.md` PASS；
- `task-5` 依赖全部 review 任务；
- 预登记 mutant 列表 + 审计任务说明。

---

# 12. Rev.3 冻结补充（优先于前文；回应 Round 2）

## 12.1 消息契约补全（关闭 R2-P0-1）

- `docs/03-protocol.md` 已新增 §3.1 枚举/流 ID 与 §3.2 逐消息载荷（SESSION_CTRL/EVENT/ERROR/PING/PONG/FEEDBACK）；
- 新增 `protocol/proto/telemetry.proto`（TELEM 字段号/类型冻结）；
- C++ `messages.h/.cpp` 补齐：SESSION_CTRL、ESTOP、EVENT、ERROR、VIDEO、PONG、FEEDBACK 的 pack/unpack；
- `protocol/vectors/session.json` 增加上述消息的固定字节样例（5 个 SESSION_CTRL 动作、3 个 EVENT、ERROR、PING/PONG、FEEDBACK）；
- CTS 增加**独立硬编码期望字节**的契约测试（不通过 urc_ref 解码生成期望），防止“同库假绿”；
- capability `streams[].id` 是逻辑编号，帧头 `stream` 固定 VIDEO=2/DEPTH=3/MAP=4（03 §3.1）。

## 12.2 明文例外与 AUTH（关闭 R2-P0-2）

明文仅允许：`HELLO`、`HELLO_ACK`、`AUTH`、`AUTH_OK`、认证前 `ERROR`（0x0101/0x0103/0x0602，≤2/s/来源）。
其余帧必须加密 + session 匹配 + 来源匹配，否则丢弃计数。

AUTH 规则：
- 只接受本来源的 pending 会话；`AUTH.session_id` 必须等于该 pending ID；
- 每个 pending 会话只接受一次 AUTH；AUTH_OK 后重复/重放 AUTH 丢弃并计数；
- 失败 per-来源计数，5 次锁 30 s；仅影响该来源；成功清零；
- HELLO 时旧会话立即失效（claimed=false、armed=false、轴清零、旧密钥作废），**急停锁存保留**；
  已存在其他来源控制者时 HELLO → 明文 ERROR 0x0103（限速），不覆盖现有会话。

## 12.3 状态机边界（关闭 safety P1-1/2）

| 当前状态 | 事件 | 结果 |
|---|---|---|
| ESTOP_LATCHED | `arm` | ERROR 0x0302；状态不变 |
| ESTOP_LATCHED | `release_estop` | 清锁存；claimed 保持；armed=false；轴清零 |
| AUTHENTICATED | `release_estop` | no-op（未锁存） |
| CLAIMED | `arm` 且当前控制者 | ARMED |
| AUTHENTICATED（未 claim） | `arm` | ERROR 0x0103（先 claim）；状态不变 |
| ARMED | watchdog 超时 | armed=false、零速、EVENT 0x0002；需 action3 |
| ARMED/CLAIMED | ESTOP(≠0) | 锁存、armed=false、零速、EVENT 0x0001 |
| 任意 | HELLO（同来源） | 新 pending；清 claimed/armed/轴；旧密钥作废；锁存保留 |
| 任意 | 会话超时 | 清 claimed/armed/peer/密钥；锁存保留 |
| 未 claim / 未 arm | CTRL | 丢弃计数；输出保持零（不回显旧命令） |

## 12.4 会话/重放/锁定（关闭 safety P1-3..6、T2-P0-1）

- 会话存活只由“CRC 通过 + 解密成功 + session 匹配”的帧延长；重放帧、坏 AEAD 帧不延长；
- 5 s 超时 → 会话失效；**清方向密钥**，必须新 HELLO+AUTH；急停锁存保留；
- 帧处理顺序固定：CRC → 解密 → session/来源校验 → 重放窗口；只有全部通过才更新窗口；
- 坏 AEAD 的高 seq 不得推进窗口；重放/坏 AEAD 分项计数；
- 锁定 per-来源（IP:port），AUTH 失败才计数；AUTH 错误不受 ERROR 限速影响；
- HELLO_ACK ≤10/s/来源；ANNOUNCE ≤20/s；发现非法包静默丢弃。

## 12.5 TTL/看门狗可证伪（关闭 safety P1-1、tests-b）

- TTL 测试配置：`--ctrl-ttl-ms 200 --watchdog-ms 600 --hold-next-ms 250`；
- 持续 100 Hz CTRL，一次 hold 命中下一 CTRL；断言：`ttl_dropped=1`、`watchdog=0`、无轴跳变、后续控制恢复；
- `--hold-next-ms` 只作用于下一入站 CTRL；单线程阻塞上限 500 ms；定时器用绝对时间追赶；
- stats 计数变更立即原子写入（临时文件 + rename），另每 500 ms 与退出时 flush；CTS 读文件断言。

## 12.6 CTS 报告与 P0 矩阵（关闭 T2-P0-2、tests-a/e）

- 18 §6.1 已冻结 `urc-cts-report/v1` schema；12 个 P0 ID 固定（18 §6.2）；
- pytest `@pytest.mark.cts_id("CTS-...")`；conftest hook 生成报告；
- CI 用 `tools/check_cts_report.py` 断言：P0 ID 集合完全相等、全部 passed、skipped=0、xfail=0；
- 默认 `cts`（Python ref）与 `mock-integration`（C++ mock）都必须通过该检查；
- S-04 增加断言：ESTOP(0) 后 `fault_flags.bit1` 仍置位、x/y/yaw=0、CTRL 不回显；
- S-05 分项断言 replay_drop/aead_fail，且“篡改帧不得被回显”；增加 **CRC 错但 AEAD 合法** 的负例；
- S-02 增加断言：超时后旧 session 帧被丢弃并 `sessions_expired++`、EVENT 0x0004、锁存保留；
- S-03 增加断言：watchdog 后未 arm 的 CTRL 不回显、无运动；action3 后才恢复；
- 客户端 `conformance/cts/client.py`：connect 走 claim→arm；暴露 `aead_fail/replay_drop`；不吞解密异常；
- 旧用例改为新语义（claim≠arm、两步复位）。

## 12.7 跨流 seq/重放（关闭 R2-P0-3）

- `crypto.json` 增加：同 seq 不同 stream 的 nonce 相同（证明必须全局 seq）、u32 回绕窗口、重复/旧包；
- `session.json` 增加跨流重复 seq 的负例；
- CTS 增加（可证伪）：
  - App→Agent 方向：CTRL(stream=0) 用 seq=X 后，FEEDBACK(stream=6) 复用 seq=X → 必须 `replay_drop++` 且 FEEDBACK 不处理；
  - Agent→App 方向：连接后收集 TELEM(stream=1) 与 VIDEO(stream=2) ≥20 帧，断言 seq 严格递增且 `replay_drop=0`；
  - 新增 `protocol/vectors/replay.json` 承载帧级负例（同 seq 跨流、回绕、重复、旧包），不再塞进 `session.json`；
  - C++/Python 测试都用一个“每方向全局窗口”，跨流重复必须拒绝。
- capability `streams[].id` 到帧 `stream` 的映射在 03 §3.1 冻结（VIDEO=2/DEPTH=3/MAP=4），App 不按逻辑 id 误判。
- C++/Python 参考实现都用“每方向全局 seq”，测试断言跨流重复拒绝。

## 12.8 构建/CI 落地（关闭 build P1-1..6）

- CI job 规格：
  - `mock-integration`：安装 cmake/g++/libssl-dev；`cmake -DURC_BUILD_APPS=ON -DURC_WERROR=ON`；随机端口启动；`URC_CTS_MOCK_BIN` 跑动态组；`timeout-minutes: 15`；`if: always()` 上传日志/`cts-report.json`；
  - `mock-asan`：`-fsanitize=address,undefined` + `-fno-omit-frame-pointer`；ctest + **CTS 用 ASAN mock 跑动态组**（`ASAN_OPTIONS=detect_leaks=1:abort_on_error=1`、`UBSAN_OPTIONS=halt_on_error=1`）；安装 cmake/g++/libssl-dev；`timeout-minutes: 25`；失败 `if: always()` 上传 build/log/cts-report；
  - `mock-soak`：仅 `workflow_dispatch` 或 main 提交含 `[soak]`；`timeout-minutes: 45`；30 min；解析 stats/RSS/fd；失败上传；
  - `agent-aarch64`：`-DURC_BUILD_APPS=ON`；QEMU `mock_robot --help`；
  - `android-build` 不在 M0 gate（S4 加入）。
- `URC_WERROR` 选项只对项目源启用；nlohmann 以 SYSTEM include；
- CMake `if(UNIX)` 守卫 apps/net；非 UNIX 明确报错；Windows 用 Python ref（文档 07/17/16 已注明）；
- SIGINT/SIGTERM：置停止标志、select EINTR、flush stats、关闭 socket、exit 0；CI 测试退出码；
- `tools/soak.py` 交付；stats 原子写；日志写文件（不用 PIPE 防阻塞）；
- `.gitignore` 增加 `build*/`、`artifacts/`。

## 12.9 交付物新增（更新 §2.1）

- `conformance/cts/client.py`、`conformance/test_protocol.py`、`conformance/conftest.py`；
- `tools/soak.py`、`tools/check_cts_report.py`（校验 dynamic+arch 报告并集=12 个 P0 ID）；
- `protocol/vectors/replay.json`；`protocol/proto/telemetry.proto`；
- `tools/codec_ref/urc_ref/messages.py`、`gen_vectors.py`、`ref_server.py`（同参数集+stats）；
- `agent/include/urc/messages.h`、`agent/src/messages.cpp` 补全；
- `docs/01,02,03,04,07,09,10,15,16,17,18` 回写（含 07 的 WSL/devcontainer 指引与单端口）。

## 12.10 Gate 证据（Rev.3）

- Round 2b 4 份窄范围复审：P0=0；P1 关闭或用户书面接受；
- 文档 diff 与 Brief §12 对应关系表；
- **执行证据**（Gate 后补）：CI run URL、`cts-report.json`（dynamic+arch）、`mock-soak` stats/RSS/fd 日志；
- Gate PASS 后才创建/领取 `task-5`；实现阶段按 §6 验收。

## 12.11 仍需用户/评审确认

1. POSIX-only + Python ref 作为 Windows 开发路径是否接受？
2. 单端口多流（v1）是否接受？
3. 30 min soak 仅在 dispatch/`[soak]` 触发，是否满足 M0 gate？（不会阻断日常 PR）
4. Round 2b 采用 4 名原评审员窄范围确认，是否接受？
