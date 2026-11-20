# Stage S1 独立审计 — C++ `mock_robot`（task-6）

| 项 | 值 |
|---|---|
| 阶段 | S1（C++ `mock_robot` + Python ref 同步 + CTS P0 矩阵 + CI） |
| 审计日期 | 2026-11-21 |
| 审计员 | `s1-auditor`（非实现者，只读代码；唯一写入本文件） |
| 审计对象 | HEAD `ecdabe7`（工作区另有 2 个未提交修改，见 §2.1） |
| 依据 | `docs/reviews/stage-S1-brief.md` §12、`docs/reviews/stage-S1-gate.md`、`docs/18-protocol-implementation-guide.md` §6、`docs/03-protocol.md`、`docs/reports/m0-progress.md` §5 |
| 本机环境 | Windows + MSYS2 g++ 16.2（POSIX 二进制）/ Python 3.12.9 / pytest 9.2.0；无可用 cmake（C++ 构建证据以 CI 为准） |

## 1. 结论摘要

- **执行证据全部复跑通过**：静态四件套、Python ref CTS、C++ mock CTS（连续 2 次）、C++ 向量 167/0、CI 2 个 run 均无失败。
- **预登记 8 个 mutant 全部被测试捕获**（1 个仅被 C++ 向量测试捕获，CTS 侧存在缺口，见 P1-04）；无“mutant 漏网”导致的一票否决。
- **发现 1 个 P0**：`CTS-C-03`（P0 ID）要求“未知 mode 拒绝+计数”，但 mock 不校验 `CTRL.mode`，未知 mode 会被执行；该 P0 用例只测了越界 axes，报告却记为 passed → **P0 用例假绿**（违反 `stage-S1-gate.md` §3.4“测试假绿→Gate 重开”）。
- **P1 8 项**：主要集中于“冻结语义未实现/未断言”（限速、明文 ERROR 例外集、S-02/S-05/P-01 冻结断言、非四足 CAPS↔视频一致性）与“soak 证据不可核验”。
- **Gate 结论：FAIL（Gate 重开）**。问题范围窄、可修复；关闭条件与复验清单见 §9。若 Gate 负责人把 P0-01 书面降级为 P1 并接受风险，则等价于 CONDITIONAL，但本审计不建议在 P0-01 修复前关闭 S1 Gate。

## 2. 审计范围与方法

### 2.1 代码/配置状态（审计时）

- `git rev-parse HEAD` = `ecdabe7a8164032af1a11cf0e5065cb022161cea`（`ci(s1): 触发30分钟浸泡验证 [soak]`）。
- `git status --porcelain`：`M conformance/test_static.py`、`M tools/soak.py`（**审计期间由实现侧并发修改，未提交**）。
  - `tools/soak.py` 未提交 diff：把 RSS/fd 采样移到 SIGTERM 前，并新增 RSS/fd 失败判据；
  - `conformance/test_static.py` 未提交 diff：`vectors_parse` 参数增加 `replay`。
  - 影响：CI 证据绑定 commit（`ed4d1bd`/`ecdabe7`），本地套件按“脏树”运行；本地 ref 套件 24 passed，HEAD 版本为 23 passed（与 `m0-progress.md` §5 的 23 一致）。
- 本地 `agent/build-posix/{mock_robot,urc_vectors}.exe` mtime 01:17，C++ 源码 mtime ≤01:13 且 `git status` 无 `agent/` 修改 → 二进制与 HEAD 源码一致。
- 只读审计：未修改仓库任何代码/配置；变异实验在**工作区外副本** `F:\DSH_WS\urc-audit` 进行（robocopy 排除 `.git`/`build*`）。

### 2.2 审计方法

1. 复跑 §6.2 验收命令与 4 个静态检查；
2. 复跑 Python ref 与 C++ mock 的同一套 CTS，并用 `tools/check_cts_report.py` 校验报告；
3. 工作区外副本中注入 9 个 mutant（8 个预登记 + 1 个“CRC-off 但只看 CTS”对照），g++ 重建后跑对应测试，确认测试失败；
4. 对 CTS 未覆盖的冻结语义写针对性探针（`probe_semantics.py`），同时打 ref 与 mock 做对照；
5. 逐项代码审查（认证门/状态机/会话/重放/TTL/看门狗/急停/CAPS/日志/ENV/CI）；
6. 用 GitHub API 核对 CI run 与 job 状态（匿名）。

## 3. 执行命令与原始结果

### 3.1 静态检查（工作区根目录）

| 命令 | 结果 |
|---|---|
| `python tools/check_links.py` | `links ok`，exit 0 |
| `python tools/check_kmp_ready.py` | `skip: android/core/protocol not present`，exit 0 |
| `python tools/codec_ref/check_caps.py` | 5 个 capability `[OK]`，`all capabilities ok`，exit 0 |
| `python tools/codec_ref/gen_vectors.py --check` | frames/crypto/frag/session/replay 全部 `[OK]`，exit 0 |

### 3.2 Python ref CTS（默认 target）

```powershell
$env:URC_CTS_REPORT='conformance\cts-report.json'
python -m pytest conformance -q
python tools/check_cts_report.py --suite dynamic --dynamic conformance\cts-report.json
```

- 结果：`24 passed`（等价静态 8 + 动态 16），exit 0；报告 `summary={'passed':14,'failed':0,'skipped':0,'xfail':0}`，11 个 P0 dynamic ID 全部 passed（另含 P1：`CTS-M-01/CTS-T-01/CTS-V-01`）。
- `check_cts_report` → `CTS report OK: P0 all passed, skipped=0, xfail=0`，exit 0。

### 3.3 C++ mock CTS（连续 2 次，per-test 启动 mock）

```powershell
$env:PATH="D:\msys64\usr\bin;$env:PATH"
$env:URC_CTS_MOCK_BIN='F:\DSH_WS\Uni-RoboController\agent\build-posix\mock_robot.exe'
$env:URC_CTS_REQUIRE_EXTERNAL='1'
python -m pytest conformance -m dynamic -q   # 连续 2 次
```

- 两次均 `16 passed`、exit 0；`conformance/cts-mock-report.json` 经 `check_cts_report --suite dynamic` 校验通过。
- fail-closed 反证（防止静默回退 Python ref）：
  - `URC_CTS_MOCK_BIN` 指向不存在的文件 → `FileNotFoundError`、exit 1（不回落）；
  - 不设 target 但 `URC_CTS_REQUIRE_EXTERNAL=1` → `Failed: URC_CTS_REQUIRE_EXTERNAL=1 but neither ...`、exit 1。
  - 结论：mock 模式确实运行 C++ mock，不是假绿回退。
- 报告缺陷：即便跑的是 mock，报告中 `target` 恒为 `"ref-server"`（见 P2-01）。

### 3.4 C++ 向量

```powershell
$env:PATH="D:\msys64\usr\bin;$env:PATH"
& '.\agent\build-posix\urc_vectors.exe' '.\protocol\vectors'
```

- `checks=167 failures=0`，exit 0；覆盖 frames/crypto/frag/session/replay 6 类，含跨流同 seq、重复、旧包、u32 回绕、错误 AAD、新消息固定字节。

### 3.5 CI 证据（GitHub API，匿名）

| run | head | 结论 | 说明 |
|---|---|---|---|
| [44781937841](https://github.com/track-tech/Uni-RoboController/actions/runs/44781937841)（run #10） | `ed4d1bd` | **success** | 7 job success（lint/vectors/cts/mock-integration/mock-asan/agent-x86_64/agent-aarch64），`mock-soak` skipped（符合规格） |
| [44783428075](https://github.com/track-tech/Uni-RoboController/actions/runs/44783428075)（run #12） | `ecdabe7` | **success** | 8/8 job success，含 `mock-soak` 30 min（17:27:56–17:57:57Z）；`soak-report.json` artifact 已生成 |

> 证据限制：匿名无法下载 artifact/日志内容，soak 报告内容未直接核验；且该 run 使用**旧版** `tools/soak.py`（见 P1-07），仅“job 绿”不足以证明 §6.3 判据。

## 4. 代码审查逐项

| 审查项 | 结论 | 证据 |
|---|---|---|
| 认证门 fail-closed | **通过** | `mock_server.cpp:324-369`：明文仅 HELLO/AUTH，其余 `gate_drop`；加密帧要求 `authenticated_ && has_ctx_ && from==peer_`。CTS-P-02 实测 gate_drop 增长、无 estop/控制效果；ref 同（`ref_server.py:294-338`） |
| claim ≠ arm | **通过** | `mock_server.cpp:527`（`!claimed_ \|\| !armed_` 拒绝 CTRL）；CTS-C-01 通过 |
| 两步急停 | **通过** | `mock_server.cpp:566-580`（`reason==0` 不清锁存）、`513-519`（release 只清锁存）；CTS-S-04 通过；M5 mutant 被捕获 |
| 会话超时清密钥/保锁存 | **通过（实现）** | `mock_server.cpp:616-620`：先 EVENT 0x0004，再 `reset_session(true)` 清 ctx/peer/claimed/armed；`reset_session` 保留 estop；CTS-S-02 通过；探针实测 EVENT `0x4` 已发送（但 CTS 未断言，P1-03） |
| 全局 seq/重放 | **通过** | mock 每方向单一 `ReplayWindow`（`mock_server.cpp:347-350`）；Agent→App `tx_seq_` 全局（`:193`）；`replay.json` 含跨流同 seq/回绕/旧包；M6/M7 mutant 被捕获 |
| TTL + stats | **部分通过** | `:352-360` 以 `--hold-next-ms` 注入模拟 TTL，`ttl_dropped` 计数；stats 临时文件+rename（`:650-670`）；CTS-C-02 通过。TTL 非到达时间判定、排队帧不参与（P2-08） |
| 看门狗 | **通过** | `mock_server.cpp:621-627` 超时置 `armed_=false`、零速、EVENT 0x0002；重新 arm 才能控制；CTS-S-03 通过；M4 mutant 被捕获（`TimeoutError`，运动未被清零断言失败） |
| CAPS/视频声明一致 | **四足通过，其他能力不一致** | 四足 capability（rgb888 160×120）与实发一致；`--capability capability.mock_arm.json` 时 CAPS 声明 h264 1280×720，实发 rgb888 160×120（探针 `video_frame_bytes=57600`）→ P1-06 |
| ref/mock 同一套 CTS | **通过（同一套用例）** | ref 16 dynamic 与 mock 16 dynamic 同一组用例、均全绿；`URC_CTS_REQUIRE_EXTERNAL=1` 防回退；但语义上 mock 存在未知 mode 偏差（P0-01） |
| CI 假绿 | **存在 2 处实质弱点** | ① `mock-soak` 旧脚本无 RSS/fd 判据且退出后采样（P1-07）；② 报告 `target` 恒 ref-server / `duration_ms=0`，checker 不校验 target（P2-01）；arch-report 为内联硬编码 JSON（P2-05） |
| 日志泄密 | **未发现敏感泄漏** | 日志仅 caps_hash/路径/状态；`--secret-file` 存在时不打印秘密；无 `--secret-file` 时打印 `URCPAIR:` 属配对供给行为（P2-09 记录约束） |
| ENV/路径处理 | **基本正确，有小瑕疵** | Windows 下 mock stats 用仓库内相对路径（`conftest.py:105-112`）；mock 模式 `target` 标注错误（P2-01）；`.cts-tmp/` 累积临时文件（P2-10） |
| 消息补全/向量契约 | **通过** | `messages.h` 覆盖 SESSION_CTRL/ESTOP/EVENT/ERROR/VIDEO/PONG/FEEDBACK 等；`session.json` 含 5 个 action、3 个 event、error/ping/pong/feedback/video 固定字节；`gen_vectors --check` 通过 |

## 5. 变异检查表（工作区外副本，g++ 重建）

- 复本：`F:\DSH_WS\urc-audit`（工作区外，robocopy 排除 `.git`/构建目录）。
- 构建：`g++ -std=c++20 -O1 -Iagent/include -Iagent/third_party agent/src/*.cpp agent/apps/mock_robot.cpp -lcrypto -o agent/mut-build/mock_robot.exe`（MSYS2 g++ 16.2，约 15 s/次）。
- 执行：`URC_CTS_MOCK_BIN=<mutant exe> URC_CTS_REQUIRE_EXTERNAL=1 python -m pytest conformance -m dynamic -q -k <expr>`；向量用 `urc_vectors.exe protocol/vectors`。
- 驱动与原始结果：`F:\DSH_WS\urc-audit\mut\run_mutants.py`、`mutants-result.json`。

| # | 预登记 mutant | 注入点 | 判定测试 | 结果 |
|---|---|---|---|---|
| 1 | 关闭 CRC 校验 | `frame.cpp` 去掉 `bad crc` 抛错 | `urc_vectors`（`decode/bad_crc`） | **捕获**：`[FAIL] decode/bad_crc: unexpected decode success`，`checks=167 failures=1` |
| 2 | 关闭认证门 | `mock_server.cpp` 明文非握手包直接分发 `on_ctrl/on_estop/on_session_ctrl` | `CTS-P-02` | **捕获**：`AssertionError: assert 0 >= 5`（gate_drop=0） |
| 3 | 关闭 TTL | 删除 hold 后的 TTL 判定 | `CTS-C-02` | **捕获**：`AssertionError: assert 0 == 1`（ttl_dropped=0） |
| 4 | 看门狗后不要求 arm | `on_ctrl` 看门狗触发后放行 CTRL | `CTS-S-03` | **捕获**：`TimeoutError: timeout waiting type 0x07`（零速断言不成立） |
| 5 | `ESTOP(0)` 解锁 | `on_estop` reason==0 清锁存 | `CTS-S-04` | **捕获**：`AssertionError: assert (0 & 2)`（fault_flags bit1 丢失） |
| 6 | 关闭 replay 窗口 | 去掉 `client_replay_.accept` 拒绝 | `CTS-S-05` | **捕获**：`assert 0 >= 1`（replay_drop=0） |
| 7 | 跨流 seq 复用不拒绝 | FEEDBACK 绕过全局窗口 | `CTS-S-05` | **捕获**：`assert 0 >= 1`（replay_drop=0） |
| 8 | CAPS 与实发视频不一致 | 视频改为 80×60（CAPS 仍 160×120） | `CTS-V-01` | **捕获**：视频字节数与 CAPS 声明不一致断言失败 |
| 8b | 对照：CRC-off 仅看 CTS | 同 #1 | `CTS-S-05` | **未被捕获（exit 0）** → CTS 缺“CRC 错但 AEAD 合法”负例（P1-04）；仅向量层捕获 |

结论：8 个预登记 mutant 均被**测试总集**捕获，满足 Gate §4 的“不得漏网”；但 #8b 暴露了“动态 CTS 单层不可捕获 CRC 关闭”的覆盖缺口。

## 6. CTS 之外的语义探针（ref 与 mock 对照）

脚本：`F:\DSH_WS\urc-audit\mut\probe_semantics.py` → `probe-result.json`（只读调用工作区 ref/mock）。

| 探针 | ref | mock | 判定 |
|---|---|---|---|
| 未知 `CTRL.mode=99` + 合法轴值 | ERROR 0x0301，`invalid_ctrl=1`，x 保持 0.5 | **无 ERROR、`invalid_ctrl=0`、x 变为 1.0（被执行）** | **P0-01** |
| 无 pending 会话的明文 AUTH | 明文 ERROR **0x0102** | 明文 ERROR **0x0102** | P1-01（例外集只有 0x0101/0x0103/0x0602） |
| AUTH_OK 后重复 AUTH（同来源） | ERROR 0x0102，无计数 | 同 | P1-01（冻结要求“丢弃并计数”） |
| 5 次错误 AUTH 后 | 锁定该来源，正确 AUTH→0x0602；**其他来源仍可认证** | 同 | 通过（实现正确，但 CTS 未断言“仅该来源”，P1-05） |
| 会话超时事件 | 收到 EVENT 0x4 | 同 | 通过（CTS 未断言，P1-03） |
| 30 次 HELLO / 0.6 s | **30 次 HELLO_ACK** | 30 次 | P1-02（要求 ≤10/s） |
| 40 次 DISCOVER / 0.6 s | **40 次 ANNOUNCE** | 40 次 | P1-02（要求 ≤20/s） |
| 已存在控制者时 10 次其他来源 HELLO | 仅 2 个明文 ERROR（限速生效） | **10 个**（不限速） | P2-02（mock 与 12.2“限速”不一致） |
| `--verbose` 握手+ESTOP | 2 行日志，无状态信息 | 同 | P2-03（`--verbose` 未实现） |
| CAPS↔视频：四足 capability | — | rgb888 160×120，`frame_bytes=57600` 一致 | 通过 |
| CAPS↔视频：`capability.mock_arm.json` | — | CAPS=h264 1280×720，实发 `frame_bytes=57600`（rgb888 160×120） | **P1-06** |
| 5 个 capability 的 `caps_hash` | — | mock 广播值 5/5 与 Python canonical 一致 | 通过 |

## 7. 缺陷清单

### P0

**P0-01 `CTS-C-03` 假绿：mock 不校验 `CTRL.mode`，未知 mode 被执行**
- 证据：探针（§6 第 1 行）：ref 对 `mode=99` 返回 ERROR 0x0301 且 `invalid_ctrl++`、不运动；mock 无错误、`invalid_ctrl=0`、轴值被执行（x→1.0）。
- 代码：`agent/src/mock_server.cpp:526-564`（`on_ctrl` 只校验 axis_count/range/flags，忽略 `ctrl.mode`；`Capability::mode_ids` 在 `agent/include/urc/mock_server.h:56` 声明但从未加载/使用）。
- 规范：`docs/03-protocol.md:178,186`（“机器人侧对 mode、axis_count、范围做校验”）；`docs/18-protocol-implementation-guide.md:136`（CTS-C-03 = P0，“越界 axes/未知 mode → 拒绝 + 计数”）；`docs/18-protocol-implementation-guide.md:177`（自带 mock 必须通过同一 P0 矩阵）。
- 测试缺口：`conformance/test_protocol.py:273-283` 只发越界轴，没有未知 mode 用例，故 CTS-C-03 记为 passed。
- 影响：P0 用例验证结论不可信；参考实现与 ref/冻结文档不一致，App 若以 mock 为联调对端会掩盖实现缺陷。
- 建议：mock 从 capability 加载 `mode_ids` 并在 `on_ctrl` 校验（未知→ERROR 0x0301 + `invalid_ctrl++` + 不运动、不刷新看门狗）；CTS-C-03 增补 `mode=99`+合法轴值断言；ref/mock/ASAN 三处 CTS 重跑。

### P1

**P1-01 认证前明文 ERROR 例外集被破坏 + AUTH 重放未“丢弃并计数”（ref 与 mock 同）**
- 证据：探针——无 pending 的明文 AUTH（任意来源）得到**明文 ERROR 0x0102**；AUTH_OK 后重复 AUTH 也返回 0x0102，且 `auth_fail/gate_drop` 均无增量。
- 代码：`mock_server.cpp:425-427`、`tools/codec_ref/ref_server.py:271-273`（`ERR_SESSION` 明文、`send_error(..., rate_limit=False)`）。
- 规范：`docs/03-protocol.md:127-131`、`docs/reviews/stage-S1-brief.md` §12.2（明文 ERROR 仅允许 0x0101/0x0103/0x0602；AUTH_OK 后重复/重放 AUTH 丢弃并计数）。
- 影响：冻结明文例外集失效（可被用于状态探测/无认证错误响应放大），且“重放 AUTH 丢弃并计数”未被实现与测试。
- 建议：该场景改为静默丢弃并计入 `gate_drop`（或新增 `auth_replay_drop`）并补 CTS 负例；不改变已冻结的错误码语义时需回写文档并复审。

**P1-02 `HELLO_ACK ≤10/s/来源`、`ANNOUNCE ≤20/s` 未实现（ref 与 mock 同）**
- 证据：探针 30 次 HELLO→30 个 ACK；40 次 DISCOVER→40 个 ANNOUNCE（0.6 s 内）。
- 代码：`mock_server.cpp:299-322`（`handle_discovery` 无速率限制）、`379-416`（`on_hello` 无速率限制）；`ref_server.py:210-224,243-264` 同。
- 规范：`stage-S1-brief.md:348`（冻结）。
- 建议：按来源做令牌桶；补 CTS 断言（或明确记录为 S2 P1 并回写文档，需 Gate 负责人接受）。

**P1-03 CTS-S-02 未断言 EVENT 0x0004（实现正确但验收不可证伪）**
- 代码：`conformance/test_protocol.py:206-231` 只断言 `sessions_expired`、旧会话帧被丢、锁存保留；探针证明 mock 实际发送 EVENT 0x4。
- 规范：`stage-S1-brief.md` §12.6（S-02 增加断言 EVENT 0x0004）、`docs/03-protocol.md:138`。
- 建议：在超时前挂起接收并断言 EVENT 0x0004，再断言新会话帧被丢弃/新 HELLO 可用。

**P1-04 CTS-S-05 缺“CRC 错但 AEAD 合法”负例**
- 证据：`test_protocol.py:104-110` 的 `_tampered` 会重算 CRC（只制造 AEAD 失败）；mutant #8b（关闭 CRC）下 CTS-S-05 exit 0，仅 `urc_vectors` 的 `decode/bad_crc` 捕获。
- 规范：`stage-S1-brief.md` §12.6（S-05 增加“CRC 错但 AEAD 合法”负例）。
- 建议：构造 CRC 错误、密文/AAD 未变的帧（服务端应 aead_fail/丢弃且不执行），并让 S-05 断言。

**P1-05 CTS-P-01 缺“仅该来源锁定”断言**
- 代码：`test_protocol.py:148-165` 只验证锁定与正确 AUTH 被拒；探针证明其他来源仍可正常认证（行为正确）。
- 规范：`docs/18-protocol-implementation-guide.md:130`。
- 建议：用第二个 `UrcClient`（不同源端口）验证锁定期内可正常 HELLO/AUTH。

**P1-06 非四足 capability 下 CAPS↔实发视频不一致**
- 证据：`--capability protocol/examples/capability.mock_arm.json` 时 CAPS 声明 h264 1280×720，mock 仍发 rgb888 160×120（`frame_bytes=57600`）；`mock_server.cpp:268-295` 硬编码 `w=160,h=120`，不读取 `capability.streams`。
- 规范：`docs/03-protocol.md:165`（声明与实际必须一致，否则视为实现缺陷）、brief §9 风险。
- 影响：S1 明确把 mock 作为多形态 App 联调 target（CLI 暴露 `--capability`，仓库含 5 个 capability 示例），非四足形态会出现“App 按 h264/720p 解码 mock”的联调失败。
- 建议：按 capability 生成视频头/分辨率与编码，或限制 mock 只接受 rgb888 形态并在文档/CLI 明确；CTS 增加对非四足 capability 的一致性用例（至少断言 `video header/res` 与 caps 一致）。

**P1-07 30 min soak 证据不可核验 §6.3**
- 证据：run 44783428075 使用 `ecdabe7` 的 `tools/soak.py`：RSS/fd 在 SIGTERM+`proc.wait()` **之后**采样（`tools/soak.py@ecdabe7:124-131`），进程已退出 → 报告 `rss_kb/fds` 恒为 0；且仅当 exit code≠0 才失败（`:143-146`），没有 RSS/fd 判据。修复（采样前移+阈值判据）在审计时**仍未提交**。
- 旁证：本地 `artifacts/soak-local.json`（3 s 冒烟）同样是 `rss_kb=0, fds=0`；其中 `exit_code=1` 是 Windows `TerminateProcess` 语义，不代表 mock 失败。
- 影响：`stage-S1-gate.md` §3.3 要求的“30 min soak 的 stats/RSS/fd 日志”无法从该 run 的 report 证明；job success 只证明 mock 退出 0。
- 建议：提交 soak.py 修复 → 用 `workflow_dispatch` 或 `[soak]` 重跑 30 min；在报告/CI step 中显式判 RSS 增长 <1 MB/h、fd ≤2、`watchdog` 误触发、`dropped_tx≈5%±20%`，并把 `[soak]` 周期采样行保留为审计证据（artifact 匿名不可下载时，审计需 job 日志访问权限）。

**P1-08 CTS 其余冻结断言/注入覆盖缺口（验收可信度）**
- `stage-S1-brief.md` §12.7：S-05 应收集 TELEM+VIDEO ≥20 帧断言 Agent→App 全局 seq；现有用例默认 `--no-camera`，只断言 `client.agent_seq_ok`（`test_protocol.py:354-355`）。
- 18 §6.2 S-03 期望“≤400 ms 停”，用例未测停时（`test_protocol.py:288-303`）。
- brief §6.2 注入专项命令含 `corrupt`，但 CTS 无 `--corrupt-aead` 用例（全文件无引用）。
- 建议：逐项补测或回写范围说明并经 Gate 负责人确认。

### P2

| ID | 问题 | 证据 |
|---|---|---|
| P2-01 | CTS 报告 `target` 恒为 `"ref-server"`（mock 模式也不改），`duration_ms` 恒 0；`check_cts_report` 不校验 target → mock/ref 报告不可区分，CI 证据弱化 | `conformance/conftest.py:217,221`，`tools/check_cts_report.py:34-53` |
| P2-02 | mock 对“已存在控制者时其他来源 HELLO”的 0x0103 明文 ERROR 未限速（ref 有）；探针 mock 10 次/0.6 s vs ref 2 次 | `mock_server.cpp:379-382`（`rate_limit=false`），brief §12.2“限速” |
| P2-03 | `--verbose` 未实现：ref/mock 都只解析参数，无状态转换日志；探针日志无状态行 | `ref_server.py:584`、`mock_server.h:30`、`mock_server.cpp`（无引用）；brief §7 |
| P2-04 | 硬编码线上契约测试存在同义反复（`struct.pack("<Q",7)==struct.pack("<Q",7)`、Frame payload 回读），且覆盖消息有限 | `conformance/test_protocol.py:115-122` |
| P2-05 | `arch-report.json` 由 CI 内联 `python -c` 硬编码生成（内容恒 passed），非测试输出 | `.github/workflows/ci.yml:164-174` |
| P2-06 | mock 未校验 HELLO `proto_major`（ref 校验并回 0x0201） | `mock_server.cpp:384-389` vs `ref_server.py:248-250` |
| P2-07 | 未锁存时 `release_estop` 仍发 EVENT 0x0005（12.3 表要求 AUTHENTICATED 下 no-op） | `mock_server.cpp:513-519`、`ref_server.py:386-394` |
| P2-08 | TTL 为 `--hold-next-ms` 注入模拟，非到达时间判定；阻塞期间排队的 CTRL 不参与 TTL | `mock_server.cpp:352-360`、`ref_server.py:329-337`；brief §12.5 已定义注入法，建议注释/文档标注模拟边界 |
| P2-09 | 无 `--secret-file` 时 stdout 打印 `URCPAIR:<base64 秘密>`（配对供给用途）；CI/CTS 均已传 secret-file，需在文档/运维约束中注明禁止日志落盘 | `mock_server.cpp:140,155`、`ref_server.py:135` |
| P2-10 | `.cts-tmp/` 每个 mock 用例生成 stats 临时文件且不清扫（已 gitignore） | `conftest.py:105-112`；工作区 `.cts-tmp/` 有数百文件 |
| P2-11 | 审计期工作区脏（`M tools/soak.py`、`M conformance/test_static.py`）；本地 ref 套件按脏树 24 passed，HEAD 为 23（与 m0 §5 一致）→ 建议所有验收证据固定 commit | §2.1 |
| P2-12 | mock 对 `HELLO` 的 `proto_major`/`role` 等字段校验弱于 ref（同 P2-06）；`Capability::mode_ids` 为死字段（并入 P0-01 修复） | `mock_server.h:56` |

## 8. Gate 判定对照

- `stage-S1-gate.md` §3.2 “S1 交付物清单”：全部文件存在（`git show --stat ed4d1bd` 24 文件 + 能力示例更新；`conformance/cts/client.py`、`tools/soak.py`、`tools/check_cts_report.py`、`protocol/vectors/replay.json`、`protocol/proto/telemetry.proto`、messages 补全、ref_server 同步等）；文档回写在 Gate 前提交（`8ab2f5f`）。
- §3.3 执行证据：CI run URL ✅、`cts-report.json`（dynamic+arch）✅（本地复跑+artifact 存在）、30 min soak stats/RSS/fd ❌（P1-07）、预登记 mutant 审计结果 ✅（本文 §5）。
- §3.4 独立审计：发现 **P0 + 测试假绿**（P0-01）→ 按 Gate 规则重开。
- §4 预登记 mutant：8/8 被测试捕获（其中 CRC 仅向量层捕获，P1-04 要求补 CTS）→ 未触发“mutant 漏网”否决项。
- 其余验收：静态/向量/ref CTS/mock CTS/双 run CI 均绿；未发现“同一套 CTS 只跑 ref 不跑 mock”“静默回退 ref”等假绿路径（`URC_CTS_REQUIRE_EXTERNAL` 探针验证）。

## 9. Gate 结论与复验清单

**Gate 结论：FAIL（Gate 重开）** — 依据 `stage-S1-gate.md` §3.4；阻断项只有 P0-01。实现主体质量高（8/8 mutant 捕获、全部基线套件与 CI 绿），不属于需要推翻实现的问题。

关闭条件（建议顺序）：

1. **修复 P0-01**：mock 校验 `CTRL.mode` + CTS-C-03 增补未知 mode 断言；ref/mock/ASAN 三处 CTS 与 `check_cts_report` 全部复跑通过（预期 dynamic 仍为 16 passed）。
2. 修复或书面接受 P1-01..P1-08（至少 P1-01/02/03/04/05/06/08 的代码/测试改动；P1-07 必须重跑出有效 soak 证据）。
3. 提交工作区未提交修改（`tools/soak.py`、`conformance/test_static.py`）并把验收证据绑定到新 commit；重跑 CI 与 30 min soak。
4. 窄范围复审（建议 2 个角色：安全/失效 + 测试/范围）确认 delta，再更新 `stage-S1-gate.md` 结论并关闭 task-6。

复验最小命令集：

```powershell
# 静态
python tools/check_links.py; python tools/check_kmp_ready.py
python tools/codec_ref/check_caps.py; python tools/codec_ref/gen_vectors.py --check
# ref CTS + 报告
$env:URC_CTS_REPORT='conformance\cts-report.json'; python -m pytest conformance -q
python tools/check_cts_report.py --suite dynamic --dynamic conformance\cts-report.json
# mock CTS（应连续 2 次）
$env:PATH="D:\msys64\usr\bin;$env:PATH"
$env:URC_CTS_MOCK_BIN='<repo>\agent\build-posix\mock_robot.exe'; $env:URC_CTS_REQUIRE_EXTERNAL='1'
python -m pytest conformance -m dynamic -q
# 向量
& '<repo>\agent\build-posix\urc_vectors.exe' '<repo>\protocol\vectors'
# P0-01 定点复验（修复后应 ERROR 0x0301 且不运动）
#   参考 F:\DSH_WS\urc-audit\mut\probe_semantics.py 中 probe_unknown_mode()
```

## 10. 剩余风险与建议

1. **mock 作为“契约 oracle”的可信度**：mock 与 ref 存在未知 mode、限速、明文 ERROR 集、`proto_major` 等偏差；建议把“ref/mock 行为差分 CTS”纳入套路（同一用例双跑并比较关键 stats），避免单个实现漂移。
2. **CAPS 漂移**：建议 CTS-V-01 由 capability 派生期望（res/codec/帧字节），并对 examples 全量跑；mock 视频参数从 capability 读取。
3. **soak 可证伪性**：soak 必须能因 RSS/fd 超限而失败；建议 report 中同时保存 `baseline`/`final`/周期采样，CI step 解析并断言；否则 30 min job 只是“跑过”。
4. **报告证据链**：`target` 应由实际 env 填入（`mock:<path>` / `target:<host:port>`），`duration_ms` 用真实耗时；`check_cts_report` 增加 target 非空/非默认校验，防止“跑 ref 交 mock 报告”。
5. **TTL 语义**：mock/ref 目前以注入方式模拟 TTL；若 S2 起要接真实 Agent，应实现按帧 ts/到达年龄的 TTL 并在文档标注注入法与真实法差异。
6. **审计环境限制（如实记录）**：本机无 cmake（C++ 构建仅由 CI 证明）；Windows 上 MSYS POSIX mock 的 SIGTERM 退出码不可复现（`TerminateProcess`）；匿名 GitHub 无法下载 artifact，soak 报告内容未直接核验；审计期间工作区存在并发未提交修改。

---

### 附：证据文件（工作区外，审计实验目录）

| 路径 | 内容 |
|---|---|
| `F:\DSH_WS\urc-audit\mut\run_mutants.py` | 9 个 mutant 的注入/构建/测试驱动 |
| `F:\DSH_WS\urc-audit\mut\mutants-result.json` | 每个 mutant 的构建 exit、测试 exit、失败断言原文 |
| `F:\DSH_WS\urc-audit\mut\probe_semantics.py` | §6 语义探针脚本 |
| `F:\DSH_WS\urc-audit\mut\probe-result.json` | §6 探针原始结果（ref/mock 对照） |
| `F:\DSH_WS\urc-audit` | 工作区外仓库副本（robocopy，排除 `.git`/构建目录），g++ 16.2 重建 mock/向量 |

> 说明：本审计未修改工作区代码/配置；工作区内仅新增本文件。

---

# 10. 复验记录（2026-11-21，HEAD `77fd355`）

> 本节为针对 §7 缺陷修复的**窄范围复验**；上文 §1–§9 的 FAIL 记录与证据保留不变。
> 复验对象：`77fd355 fix(s1): 修复审计P0/P1并触发浸泡复验 [soak]`（工作区干净，`git status` 无输出；本地 HEAD = origin/main = `77fd3559`）。
> 复验方式：只读审查修复 diff + 复跑全部基线套件 + 工作区外副本（`F:\DSH_WS\urc-audit2`）g++ 重建并注入定点 mutant + 语义探针（`mut/probe_verify.py`）。

## 10.1 复验命令与结果

| 项 | 命令/方式 | 结果 |
|---|---|---|
| 静态四件套 | `check_links/check_kmp_ready/check_caps/gen_vectors --check` | 全部 exit 0（`links ok`、5 capability OK、5 向量文件 OK） |
| Python ref CTS | `URC_CTS_REPORT=conformance\cts-report.json; python -m pytest conformance -q` | **25 passed**（原 24 + 新增 HELLO_ACK 限速用例），`check_cts_report` OK；报告 `target=ref-server`、14/14 用例 `duration_ms>0` |
| C++ mock CTS | 同 §3.3，`URC_CTS_MOCK_BIN=urc-audit2\agent\mut-build\mock_robot.exe`（由 `77fd355` 源码 g++ 重建） | **连续 2 次 17 passed**（原 16 + 限速用例）；报告 `target=mock`、14/14 `duration_ms>0`、11 P0 全 passed、skipped/xfail=0，`check_cts_report` OK |
| C++ 向量 | `urc_vectors.exe protocol/vectors` | `checks=167 failures=0`，exit 0 |
| arch 报告工具 | `python tools/gen_arch_report.py --bin <新urc_vectors> --vectors protocol/vectors --out ...` + `check_cts_report --suite arch` | 报告由真实运行结果生成（`checks=167 failures=0`），`CTS report OK`，exit 0（原 P2-05 硬编码报告已修） |
| 稳定性 | 新增/改动用例（hello_ack_rate/CTS-C-03/CTS-S-02/CTS-S-05/CTS-P-01）连续跑 3 次 | 3/3 全绿（5 passed/次） |

## 10.2 定点变异复验（工作区外副本，g++ 重建）

驱动：`F:\DSH_WS\urc-audit2\mut\mut2.py` → `mut2-result.json`。

| ID | 注入点（针对修复后代码） | 判定测试 | 结果 |
|---|---|---|---|
| R1 | 删除新增的 `mode_ids` 校验（`mock_server.cpp` on_ctrl） | CTS-C-03（`-k out_of_range_and_bad_mode`） | **CAPTURED**：`expected error 0x0301, got None` → P0-01 修复可证伪 |
| R2 | 关闭 CRC 校验（`frame.cpp`） | CTS-S-05（`-k replay_tamper`） | **NOT CAUGHT（exit 0）** → P1-04 仍不可证伪（见 10.4/10.5） |
| R3 | 删除会话超时 `EVENT 0x0004`（`mock_server.cpp` tick） | CTS-S-02（`-k session_timeout`） | **NOT CAUGHT（exit 0）** → P1-03 断言被 try/except 吞掉 |
| R4 | 关闭 VIDEO 发送（`send_video` 立即 return） | CTS-S-05（`-k replay_tamper`） | **CAPTURED**（但失败原因是 `TimeoutError: timeout waiting type 0x07`，属看门狗时序副作用，非 seq 断言；见新 P2-13） |
| R5 | 关闭 HELLO_ACK 限速 | `-k hello_ack_rate` | **CAPTURED**：`assert 30 <= 12` → P1-02 修复可证伪 |

## 10.3 语义探针复验（ref 与 mock 对照）

脚本：`F:\DSH_WS\urc-audit2\mut\probe_verify.py` → `probe2-result.json`。

| 探针 | ref | mock | 结论 |
|---|---|---|---|
| 未知 `CTRL.mode=99` + 合法轴值 | ERROR 0x0301，`invalid_ctrl=1`，x 保持 0.5 | 同 | **P0-01 行为已修** |
| 无 pending 明文 AUTH | 静默无响应，`gate_drop=1` | 同 | **P1-01 已修** |
| 30 个 HELLO 突发 | **10 个 HELLO_ACK** | **10 个** | **P1-02 已修**（≤10/s） |
| 40 个 DISCOVER 突发 | **20 个 ANNOUNCE** | **19 个** | **P1-02 已修**（≤20/s；测试仅覆盖 HELLO_ACK，见新 P2-16） |
| 会话超时（500 ms） | 收到 EVENT 0x0004 | 同 | **P1-03 实现正确，但 CTS 断言可选（未关闭）** |
| 5 次错误 AUTH 后另一来源认证 | 正常认证 | 同 | **P1-05 已修** |
| 四足 CAPS↔视频 | rgb888 160×120，`frame_bytes=57600` 一致 | 同 | **P1-06 四足一致性已修** |
| 非 rgb888 capability（mock_arm） | 拒绝启动并打印原因 | 同 | **P1-06 以“仅支持 rgb888”收口，docs 16/18 已注明** |

## 10.4 P0/P1 关闭表

| 原 ID | 修复内容 | 复验判定 | 依据 |
|---|---|---|---|
| **P0-01** 未知 mode 假绿 | mock 校验 `mode_ids`；CTS-C-03 改名并加 `mode=99` 断言 | **已关闭 ✅** | 探针 + CTS-C-03 + mutant R1 |
| P1-01 明文 0x0102 / AUTH 重放未计数 | 无 pending/来源/会话不符改为静默 `gate_drop++`；P-02 加 AUTH 计数断言 | **已关闭 ✅** | 探针（无响应、gate_drop=1）+ 代码 review + CTS-P-02 |
| P1-02 HELLO_ACK/ANNOUNCE 限速 | ref/mock 增加每来源/全局 1 s 窗口限速 | **已关闭 ✅**（ANNOUNCE 无 CTS 用例，仅探针） | 探针 10/20 + 新测试 + mutant R5 |
| P1-03 S-02 未断言 EVENT 0x0004 | 新增 `_recv_event(EVT_SESSION_EXPIRED)`，但包在 `try/except TimeoutError: pass` | **未关闭 ❌（测试不可证伪）** | mutant R3 不被捕获；`test_protocol.py:241-244` |
| P1-04 CRC 负例缺失 | 新增“CRC 错”帧：`bad_crc[40] ^= 0xFF`（未重算 CRC） | **未关闭 ❌（负例构造错误）** | mutant R2 不被捕获；`test_protocol.py:405-413` 翻转的是**密文字节**，AEAD 同时失效，关闭 CRC 后仍被 AEAD 拒绝；注释“密文未改”与实现不符 |
| P1-05 P-01 缺“仅该来源锁定” | 增加另一来源 hello/auth | **已关闭 ✅** | CTS-P-01 + 探针 |
| P1-06 非四足 CAPS↔视频漂移 | ref/mock 要求 rgb888 capability（否则拒绝启动），视频按 caps res/fps；docs 16/18 注明 | **已关闭 ✅（范围收口）** | 探针 + 文档 diff；H.264 留待 M2 |
| P1-07 soak 证据不可核验 | `tools/soak.py` 采样前移 + RSS/fd 阈值判据已提交；新 run 含 30 min soak | **部分关闭 ⏳（待 CI/soak 证据）** | 代码 review 通过；run 44791424581 的 mock-soak 复验时仍 in_progress；artifact 匿名不可下载；且 §6.3 的 watchdog 误触发 / `dropped_tx≈5%±20%` 仍未自动断言（新 P2-15） |
| P1-08 其它 CTS 缺口 | S-03 加停时断言；S-05 加 TELEM/VIDEO 帧收集 | **部分关闭 ⏳** | S-03 已加（阈值 0.5 s，`test_protocol.py:334-340`）；S-05 实际只 `assert seen > 0` 且在首个 VIDEO 即 break，未断言 ≥20 帧（`test_protocol.py:373-383`）；VIDEO-off mutant 被捕获属看门狗副作用（R4） |

P2 复核：P2-01（target/duration）、P2-02（occupied HELLO 限速）、P2-05（arch 报告工具）、P2-06（proto_major 校验）、P2-07（release_estop no-op）、P2-10（`.cts-tmp` 清理）、P2-11（工作区干净、证据绑 commit）、P2-12（mode_ids）**已关闭**；P2-03（`--verbose`）、P2-08（TTL 注入语义）、P2-09（URCPAIR 秘密打印）**仍未处理（P2 可延后）**；P2-04 部分处理（删除了 `struct.pack` 同义反复，`Frame.payload` 回读断言仍在）。

## 10.5 新发现（复验引入/暴露）

| ID | 级别 | 问题 | 证据/建议 |
|---|---|---|---|
| **新 P1-A（对应 P1-03/P1-04 汇总）** | P1 | 两处“已修复”断言实际不可证伪：S-02 的 EVENT 断言被 `except TimeoutError: pass` 吞掉；S-05 的 CRC 负例翻转的是密文字节（`test_protocol.py:409-410`），CRC-off mutant 仍可通过 | mutant R2/R3 均 NOT CAUGHT。修法：去掉 try/except；CRC 负例改为**只改 CRC 字段**（如 `raw[28]^=0xFF`，不动密文）或重加密后改 CRC，并断言 `aead_fail` 不增/帧被丢弃且不执行 |
| **新 P2-13** | P2 | 新 S-05 在 `connect()`（已 arm）后先收集最多 3 s 帧再发 CTRL；若首帧 VIDEO 晚于看门狗 300 ms，看门狗触发导致后续 `x>0.5` 断言超时 → CI 慢机 flaky 风险（R4 的失败即此路径） | 收集期间保持发合法 CTRL 刷新看门狗，或收集后重新 arm；同时把断言改为 `seen>=20` 且至少 1 帧 VIDEO |
| **新 P2-14** | P2 | `proto_major != 1` 回**明文** ERROR 0x0201，超出冻结明文例外集（03 §4.1 仅 0x0101/0x0103/0x0602）；ref 原有、本次 mock 新增，CTS 无覆盖 | `mock_server.cpp:426-428`、`ref_server.py:269-270`。需回写 docs 02/03/brief（把 0x0201 加入例外集）或改用允许码 |
| **新 P2-15** | P2 | soak 判据口径偏松/不全：`allowed_kb = max(1024, 1024*elapsed/3600)` 在 30 min 时允许 1 MB（≈2 MB/h），约为 §6.3“<1 MB/h”的 2 倍；且未断言 watchdog 不误触发、`dropped_tx≈注入比例±20%` | `tools/soak.py:146-152`；§6.3 |
| **新 P2-16** | P2 | 新增限速测试仅覆盖 HELLO_ACK（阈值 `<=12`，略宽于 10/s），ANNOUNCE ≤20/s 只有探针验证、无 CTS 用例 | `test_protocol.py:124-146` |

## 10.6 CI / soak 状态（run #13 `44791424581`，HEAD `77fd355`）

复验时（2026-11-21 02:29 +08 / 18:29Z）核对 GitHub API：

| job | 状态 |
|---|---|
| lint / vectors / cts / mock-integration / mock-asan / agent-x86_64 / agent-aarch64 | **7/7 success**（18:18–18:22Z 完成） |
| mock-soak | **in_progress**（30 min soak 18:18:28Z 开始，预计 ~18:48Z；artifact `soak-report.json` 尚未生成上传） |

- **结论：soak 证据“待证据”**，不假设通过；新 run 的 soak 使用已提交的修复版 `tools/soak.py`（RSS/fd 前置采样 + 阈值判据），需在 job 完成后核对：8/8 job success、`soak-report.json` 的 `exit_code=0`、`rss_kb/fds/baseline` 数值合理（非 0）、job 日志含 `[soak] t=...` 周期采样的 RSS 走势。
- 匿名无法下载 artifact/日志的权限限制同 §3.5；复验未能直接读取 `soak-report.json` 内容。

## 10.7 复验结论

**复验结论：FAIL（暂不关闭；P0 已关闭，2 项 P1 的测试可证伪性未达标，soak 证据待补）。**

- **P0：已清零**。P0-01 行为、CTS 断言、mutant 三层验证均通过；静态/ref CTS/mock CTS/向量/CI 基线全绿。
- **判定 FAIL 的唯一原因是“验收不可信”类 P1 未真正关闭**：P1-03（EVENT 断言可选）与 P1-04（CRC 负例构造错误）各只需 2–5 行测试修补，**不涉及实现回退**；P1-07 需等 soak job 完成并核对报告；P1-08 的 VIDEO seq 断言弱于冻结要求。
- 关闭条件（很小）：① 删除 S-02 的 try/except，使 EVENT 0x0004 断言强制；② CRC 负例只改 CRC 字段/不动密文，并让 CRC-off mutant 被 CTS 捕获；③ 用 run #13 完成证据核对 soak（8 job 全绿 + 报告判据）；④ 建议顺手修新 P2-13（避免 S-05 flaky）并在 PR 中标注新 P2-14/15/16 的接受/延期决定。
- 满足 ①②③ 后建议直接判定 **PASS（narrow re-audit）**；本轮不重开 P0，不要求重跑 30 min soak（除非 ② 改动影响 mock 行为——不会）。

## 10.8 最终窄范围复验（2026-11-21 03:00 +08，HEAD `b17401e`）

> 实现侧已提交 `b17401e fix(cts): 修复S-02/S-05可证伪性与明文例外`（本地 = origin/main，工作区干净）。
> 本次为 §10.5 P1-A 与 P2-14/16 的**最终确认**，只读实现，仅追加本节。

### 10.8.1 修复 diff 核对（`77fd355..b17401e`）

| 项 | 核对结果 |
|---|---|
| P1-03 S-02 EVENT 断言 | `try/except TimeoutError: pass` 已删除；`_recv_event(c1, EVT_SESSION_EXPIRED, timeout=2.0)` **强制断言**（`test_protocol.py:241`） |
| P1-04 CRC 负例 | 改为 `bad_crc[28] ^= 0xFF`（**只破坏 CRC 字段**，密文/tag/AAD 不变），且新增“若 CRC 被错误关闭则该清零帧会执行 → 断言 x>0.5”双重断言（`test_protocol.py:405-416`） |
| P1-08 / 新 P2-13 | S-05 现在 `assert seen >= 20`、`assert video_seen >= 1`，收集后 `client.arm()` 重新 arm（`test_protocol.py:369-386`）；消除看门狗时序耦合 |
| P1-02 限速断言 | HELLO_ACK 断言收紧为 `acks <= 11` |
| 新 P2-14 | `0x0201` 已加入明文 ERROR 例外集（docs 03 §4.1、18 §4、brief §12.2 三处同步） |

### 10.8.2 本地复跑（HEAD `b17401e`，g++ 由 `F:\DSH_WS\urc-audit2` 重建）

| 项 | 结果 |
|---|---|
| 静态四件套 | 全部 exit 0 |
| Python ref CTS（全量） | **25 passed**，`check_cts_report` OK（P0 全 passed、skipped/xfail=0） |
| C++ mock CTS（连续 2 次） | **17 passed ×2**，报告 `target=mock`、14 用例 `duration_ms>0`，`check_cts_report` OK |
| 定向用例 2 次（`-k "session_timeout or replay_tamper"`） | **2 passed ×2** |
| C++ 向量 | `checks=167 failures=0` |
| arch 报告工具 | `checks=167 failures=0` → `CTS-K-01 passed`，`check_cts_report --suite arch` OK |

### 10.8.3 关键 mutant 最终确认（修复后源码）

| mutant | 判定测试 | 结果 |
|---|---|---|
| 关闭 CRC 校验（`frame.cpp` 去 CRC 抛错） | CTS-S-05 | **CAPTURED**：`aead_fail` 仅 1，`assert >=2` 失败（CRC 关闭后该帧 AEAD 合法被执行，不再计 aead_fail） |
| 删除 EVENT 0x0004（`tick` 去 send_event） | CTS-S-02 | **CAPTURED**：`TimeoutError: event 0x0004 not received` |
| 关闭 VIDEO 发送（`send_video` 直接 return） | CTS-S-05 | **CAPTURED**：`assert video_seen>=1` 失败（`assert 0 >= 1`），且不再是看门狗副作用 |

→ **P1-03、P1-04、P1-08（含 P2-13）全部关闭**。

### 10.8.4 CI / soak 最终证据

| run | 结论 | 证据 |
|---|---|---|
| [44794676731](https://github.com/track-tech/Uni-RoboController/actions/runs/44794676731)（#14，`b17401e`） | **7/7 已执行 job success**（lint/vectors/cts/mock-integration/mock-asan/agent-x86_64/agent-aarch64，18:38–18:44Z）；`mock-soak` skipped（commit 无 `[soak]`，符合规格） | GitHub API jobs（经 gh-proxy 匿名读取） |
| [44791424581](https://github.com/track-tech/Uni-RoboController/actions/runs/44791424581)（#12，`77fd355`，含 soak） | **8/8 job success**：`mock-soak` → `30 min soak` step **success（18:18:28Z→18:48:28Z，恰好 30 min）**，artifact 上传 step success | GitHub API jobs；`soak.py@77fd355` 已含 exit_code=0 + RSS 增长 + fd 增长判据，step 成功即表示这些判据通过 |
| soak 报告内容 | `soak-report.json` artifact 已生成（upload success），但**匿名无法下载内容**；报告数值未直接读取 | 判据由 `soak.py` 代码强制（`tools/soak.py:146-152`）；job 成功等价于其判据通过 |

> 复核限制（如实记录）：GitHub 匿名 API 限额用尽后改用 gh-proxy 读取 jobs 元数据；artifact/日志内容仍受匿名权限限制。因此 soak 的“8 job 全绿 + 30 min step success + 判据代码强制”可确认；报告的 `rss_kb/baseline/exit_code` 具体数值未直接核验。§6.3 中 watchdog 误触发与 `dropped_tx≈5%±20%` 仍未写入自动判据（P2-15，非阻塞）。

### 10.8.5 最终 P0/P1 关闭表与结论

| ID | 状态 | 复验依据 |
|---|---|---|
| P0-01 | **已关闭 ✅** | 行为探针 + CTS-C-03 + mutant R1（§10.2） |
| P1-01 | **已关闭 ✅** | 静默丢弃/gate_drop 探针 + CTS-P-02 |
| P1-02 | **已关闭 ✅** | 探针 10/20 + 新用例 + mutant R5；ANNOUNCE 仅探针（P2-16） |
| P1-03 | **已关闭 ✅** | 强制 EVENT 断言 + mutant R3 捕获（§10.8.3） |
| P1-04 | **已关闭 ✅** | 只改 CRC 字段负例 + mutant R2 捕获（§10.8.3） |
| P1-05 | **已关闭 ✅** | CTS-P-01 另一来源断言 + 探针 |
| P1-06 | **已关闭 ✅** | rgb888-only 收口 + 探针 + docs 16/18 |
| P1-07 | **已关闭 ✅** | soak.py 判据提交 + run #12 8/8 job success（含 30 min soak step success）；报告数值待有权限者抽查 |
| P1-08 | **已关闭 ✅** | S-03 停时断言 + S-05 `seen>=20`/`video_seen>=1` + mutant R4 捕获 |

**最终复验结论：PASS（窄范围复验通过）**。

- P0 = 0；P1 全部关闭；预登记 8 mutant 与复验定点 mutant（mode/CRC/EVENT/VIDEO/HELLO 限速）均可被测试捕获；静态/ref CTS/mock CTS/向量/arch 报告/CI 两个 run 均绿；soak 30 min step 成功且判据已代码化。
- S1 Gate 可据此关闭（历史 FAIL 记录保留于 §1–§9 供追溯）。
- 遗留 **P2（不阻塞，建议下阶段处理）**：P2-03 `--verbose` 未实现；P2-08 TTL 为注入模拟；P2-09 无 secret-file 时打印 URCPAIR；P2-15 soak 阈值 30 min 时允许 1 MB（约 §6.3 的两倍）且 watchdog/dropped_tx 未自动断言；P2-16 ANNOUNCE 限速无 CTS 用例。
- 证据目录（工作区外）：`F:\DSH_WS\urc-audit2\mut\{mut2.py, mut2-result.json, probe_verify.py, probe2-result.json, arch-report.json}`。
- 本次复验未修改实现；仅在本文件追加 §10.8（提交建议：`docs(s1): 追加S1审计最终复验结论`）。
