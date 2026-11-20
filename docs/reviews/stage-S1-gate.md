# Stage S1 Gate — C++ `mock_robot`

| 项 | 值 |
|---|---|
| 阶段 | S1 |
| Gate 日期 | 2026-11-20 |
| 评审对象 | `stage-S1-brief.md` Rev.3 + docs 02/03/09/18 冻结 |
| 流程 | Round 1（4 份）→ Rev.2 → Round 2（4 份）→ Rev.3 → Round 2b（4 份窄审）→ Rev.3.1 → Round 2c（4 份最终确认） |

## 1. Verdict：**PASS（有条件进入实现）**

- **P0 = 0**：Round 1/2/2b 的全部 P0 已关闭，Round 2c 四份确认均为 PASS。
- **P1 = 0 未关闭**：Round 2b 的 3 项构建 P1、2 项测试 P1、协议 P1 均已修复；Round 2c 确认通过。
- **P2 遗留**：见 §3，允许在实现阶段顺手修复，不阻塞。

## 2. 评审与关闭证据

| 轮次 | 评审员 | Verdict | P0 | 关闭方式 |
|---|---|---|---|---|
| Round 1 | review-protocol | FAIL | 2 | AAD 冻结、seq 全局、跨流重放测试 → Rev.2/3 |
| Round 1 | review-safety | FAIL | 3 | 认证门、claim≠arm、两步复位 → Rev.2/3 |
| Round 1 | review-build | CONDITIONAL | 0 | CI/ASAN/soak/隔离/POSIX → Rev.2/3 |
| Round 1 | review-tests | FAIL | 1 | P0 矩阵/报告/可证伪断言 → Rev.2/3 |
| Round 2 | r2-protocol | FAIL | 3 | 消息格式、明文例外、跨流重放 → Rev.3 |
| Round 2 | r2-safety | CONDITIONAL | 0 | 状态机边界/会话/重放/锁定 → Rev.3 |
| Round 2 | r2-build | CONDITIONAL | 0 | ASAN/soak/SIGTERM/CI 规格 → Rev.3 |
| Round 2 | r2-tests | FAIL | 2 | 会话超时、报告 schema/P0 ID → Rev.3 |
| Round 2b | r2-protocol | FAIL | 0（2 P0 残留） | 跨流 CTRL/FEEDBACK 用例、18 明文例外、MTU/端口 → Rev.3.1 |
| Round 2b | r2-safety | PASS（2 P2） | 0 | 18 P-02/gate_drop/arm 限定 → Rev.3.1 |
| Round 2b | r2-build | FAIL（3 P1） | 0 | 07 WSL、Gate 证据、16/17/10 job 名 → Rev.3.1 |
| Round 2b | r2-tests | FAIL（3 项） | 0 | K-01 arch suite、ref CLI、S-02/CRC → Rev.3.1 |
| Round 2c | r2-protocol | **PASS** | 0 | 确认 delta |
| Round 2c | r2-safety | **PASS** | 0 | 确认 delta |
| Round 2c | r2-build | **PASS** | 0 | 确认 delta |
| Round 2c | r2-tests | **PASS** | 0 | 确认 delta |

详细记录：
- [stage-S1-review.md](stage-S1-review.md)（Round 1）
- [stage-S1-review-round2.md](stage-S1-review-round2.md)（Round 2）
- [stage-S1-brief.md](stage-S1-brief.md) Rev.3（含 §12 冻结与交付清单）

## 3. 允许进入实现的条件

1. **冻结语义不得回退**：实现必须按 `stage-S1-brief.md` §12 与 docs 02/03/09/18；
   任何改动回写文档并升级评审，不得静默偏离。
2. **S1 实现交付物**：§12.9 清单全部交付（mock、net/server、messages 补全、replay/session 向量、
   ref_server 同步、CTS client/报告、soak、check_cts_report、CI jobs、文档回写）。
3. **实现后必须补交执行证据**（§12.10）：
   - CI run URL（lint/vectors/cts/mock-integration/asan/arch）；
   - `cts-report.json`（dynamic+arch，12 个 P0 ID 全 passed、skipped=0、xfail=0）；
   - 30 min soak 的 stats/RSS/fd 日志（dispatch/`[soak]` 触发）；
   - 预登记 mutant 的审计结果（§6.4）。
4. **独立审计**：`task-6` 由非实现者执行；若发现 P0 或测试假绿，Gate 重开。
5. **P2 遗留项**（不阻塞，实现期处理并记录）：
   - `docs/08` 其余示例已置 0；`03` 事件顺序/0x0103 释义已补；
   - aarch64 arch-report artifact 步骤需写入 CI；
   - brief §2.1 与 §12.9 的概览/清单差异以 §12.9 为准；
   - `session.json` 不再承载帧级重放负例（统一到 `replay.json`）。

## 4. 预登记 mutant（审计必查）

1. 关闭 CRC 校验；2. 关闭认证门；3. 关闭 TTL；4. 看门狗后不要求 arm；
5. `ESTOP(0)` 解锁；6. 关闭 replay 窗口；7. 跨流 seq 复用不拒绝；8. CAPS 与实发视频不一致仍通过。

任一 mutant 未被测试捕获 → 审计失败，Gate 重开。

## 5. 任务状态

- `task-1..4`、`task-7..14`、`task-16..19`：评审完成；
- `task-15`（本 Gate）：PASS；
- `task-5`（S1 实现）：解除阻塞，可领取；
- `task-6`（独立审计）：待实现完成后领取。

> 本 Gate 通过仅表示“方案可进入实现”，不代表 S1 已交付；实现完成并补齐执行证据后才算 S1 完成。

## 6. S1 完成验收（2026-11-21）

| 项 | 结果 |
|---|---|
| 实现提交 | `ed4d1bd`（mock_robot+CTS）、`ecdbabe7`（soak 触发）、`77fd355`（审计 P0/P1 修复）、`b17401e`（S-02/S-05 可证伪性） |
| 独立审计 | [stage-S1-audit.md](stage-S1-audit.md) 初判 FAIL（P0-01 mode 假绿 + P1）→ 修复 → §10.8 **最终 PASS**；P0=0，P1 全关闭，mutant 全部可捕获 |
| CI（常规） | run [44794676731](https://github.com/track-tech/Uni-RoboController/actions/runs/44794676731)（`b17401e`）：7/7 已执行 job success（lint/vectors/cts/mock-integration/mock-asan/agent-x86_64/agent-aarch64） |
| CI（含 soak） | run [44791424581](https://github.com/track-tech/Uni-RoboController/actions/runs/44791424581)（`77fd355`）：8/8 job success；mock-soak 30 min step success（18:18:28Z→18:48:28Z） |
| P0 矩阵 | dynamic 11 个 P0 全 passed；arch `CTS-K-01` passed；skipped=xfail=0；`tools/check_cts_report.py` 通过 |
| 单元/向量 | C++ 向量 `checks=167 failures=0`；Python ref CTS 25 passed；C++ mock CTS 17 passed ×3 |
| 30 min soak | 由 `tools/soak.py` 强制 exit_code=0 + RSS/fd 增长判据；step success；artifact 已上传（匿名不可下载，数值由代码判据保证） |

**结论：S1 完成，Gate 关闭。** 遗留 P2（不阻塞）：
`--verbose` 未实现；TTL 为注入模拟；无 secret-file 时打印 URCPAIR；soak 的 watchdog/dropped_tx 未自动断言；ANNOUNCE 限速无 CTS 用例。下阶段（S2）前处理或登记。

## 7. 任务状态（S1 完成时）

- `task-5` S1 实现：completed；
- `task-6` 独立审计：completed（审计报告 §10.8 PASS）；
- 下一阶段 `task-7` 起为 S2（最小参考 Agent），需重新走 Brief→对抗评审→Gate。
