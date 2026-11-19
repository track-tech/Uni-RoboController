# Stage S1 对抗评审汇总（Round 2）

| 项 | 值 |
|---|---|
| 阶段 | S1 C++ `mock_robot` |
| 轮次 | Round 2（2026-11-20），评审对象 `stage-S1-brief.md` Rev.2 + docs 02/03/09/18 |
| 评审员 | r2-protocol / r2-safety / r2-build / r2-tests（独立只读） |

## 1. Verdict

| 评审员 | Verdict | P0 | P1 | 结论 |
|---|---|---|---|---|
| 协议/互操作 | **FAIL** | 3 | 9 | 核心消息无线格式；认证明文例外自相矛盾；跨流 seq/重放无测试 |
| 安全/失效 | CONDITIONAL | 0 | 7 | 状态机/会话/重放/锁定语义仍有未冻结路径 |
| 构建/平台 | CONDITIONAL | 0 | 6 | ASAN/soak/信号/CI 规格/Windows 回写仍不完整 |
| 测试/范围 | **FAIL** | 2 | 5 | 会话超时冲突；P0 矩阵/report 无 schema，仍可假绿 |

**结论：Gate FAIL。** Round 2 关闭了 Round 1 的 6 个 P0（AAD/seq 冻结/认证门/arm/急停两步/P0 矩阵框架已入 Brief），
但暴露出 5 个新 P0（均为文档/测试契约缺口，非实现安全漏洞）。Rev.3 修复后做窄范围复审（Round 2b）。

## 2. Round 2 P0（阻塞）

| ID | 问题 | 证据 | Rev.3 决议 |
|---|---|---|---|
| R2-P0-1 | 03 只有消息类型号，缺少 SESSION_CTRL 动作码/EVENT 码与载荷/ERROR/PING/PONG/FEEDBACK/stream 数值；App 无法实现，CTS 与 mock 共用 ref codec 会假绿 | 03:46-76；ref_server.py:45-49；messages.py:166-203；cts/client.py:16 | 03 增补 §3.1 枚举与逐消息载荷；新增 `protocol/proto/telemetry.proto`；CTS 增加“字节级固定样例”断言，不再只依赖同库 |
| R2-P0-2 | 认证门“除 HELLO/AUTH 外全部加密”与 HELLO_ACK/AUTH_OK/认证前 ERROR 明文矛盾；AUTH 的 session_id/来源规则未定义 | 02:82；03:97；09:100；18:59；ref:146,239,252 | 明确明文例外集：HELLO/HELLO_ACK/AUTH/AUTH_OK + 认证前 ERROR（0x0101/0x0103/0x0602，限速）；AUTH 必须 session_id=pending 且来源一致、一次性 |
| R2-P0-3 | “每方向全局 seq/跨流重放”无向量与 CTS 断言；每流独立 seq 的实现仍会全绿，GCM nonce 跨流复用不报错 | cts/client.py:27-72；crypto.json；Brief 矩阵 | 新增跨流同 seq 向量（断言 nonce 相同→必须禁止）、重放窗口回绕向量；CTS 断言客户端/服务端全局 seq 与跨流重复拒绝 |
| T2-P0-1 | 会话超时语义冲突：02:84-85 同时“10s 可恢复、密钥不重协商”与“清密钥”；S-02 不可判定 | 02:84-85；03:104-105 | 冻结：5 s 超时即失效，**清密钥**，必须新 HELLO+AUTH；删除“10 s 密钥复用”；CTS 断言旧帧丢弃、sessions_expired++、锁存保留 |
| T2-P0-2 | P0 矩阵完整性不可证伪：仅断言 skipped=0+P0 全绿；无 report schema/ID 集合断言，改名或条件跳过仍绿 | 18:112/143；Brief:177/210；16:93 | 冻结 `cts-report.json` schema；固定 12 个 P0 ID；CI 断言集合相等、全部 passed、skipped=0、无 xfail；用例打 `cts_id` marker |

## 3. Round 2 P1（Rev.3 必须关闭或用户接受）

| 来源 | 问题 | Rev.3 决议 |
|---|---|---|
| safety-1 | 锁存期间可先 arm 再 release_estop，折叠两步复位 | 冻结：锁存期间 `arm` 返回 0x0302 且不改变状态；`release_estop` 强制 disarmed/zero；测试时序 |
| safety-2 | HELLO 重建未定义状态重置；armed 可能跨 HELLO 保留 | 冻结 HELLO：清 claimed/armed/axes/keys，保留 estop 锁存；测试“arm→HELLO→未 arm 不可控” |
| safety-3 | 明文 AUTH 可重放绑定 peer | AUTH 仅接受 pending+来源一致+一次性；重放丢弃计数；测试第二 socket 重放 |
| safety-4 | “有效帧”未定义；重放/坏 AEAD 可延长会话 | 冻结：会话存活仅由成功解密+CRC+session 匹配的帧延长；坏 AEAD/重放不延长；测试 |
| safety-5 | 重放窗口与 AEAD 校验顺序未冻结 | 先 CRC→AEAD 成功→再更新重放窗口；坏 AEAD 高 seq 不得影响窗口；测试 |
| safety-6 | 认证前 ERROR 限速与 CTS-P-01 冲突；per-源锁定可 DoS | 冻结：AUTH 错误不计入 ERROR 限速；锁定 per-来源，其他来源不受影响；测试 |
| safety-7 | CTS-P-02 缺 release_estop/arm；计数未指定；篡改测试假绿 | P0 矩阵补明文 release/arm；计数 `gate_drop`；篡改测试断言无回显+`aead_fail` |
| build-1 | ASAN 只构建+ctest，不跑 CTS；UBSAN 不中断 | `mock-asan` 用 ASAN mock 跑动态 CTS；`abort_on_error/halt_on_error` |
| build-2 | SIGTERM 退出码未定义 | 捕获 SIGINT/SIGTERM→flush stats→exit 0；CI 测试 |
| build-3 | Gate 无执行证据；16 仍含不存在的 android job | Gate 要求 CI run URL + cts-report + soak stats；16 改 M0 判据含 mock-integration/asan/soak |
| build-4 | 无 `-Werror` | 增 `URC_WERROR`（CI ON，nlohmann SYSTEM include） |
| build-5 | Windows 本地零验证；CMake 无 UNIX 守卫 | apps/net 仅 UNIX；CMake 对非 UNIX 给出错误；补 WSL/devcontainer 指引 |
| build-6 | 新 job 规格不可落地（依赖/超时/artifact/PR [soak]） | 补完整 YAML：timeout-minutes、if: always、artifact、soak 仅 workflow_dispatch 或 main 提交含 [soak] |
| tests-a | S-04 未断言 ESTOP(0) 后锁存与零速 | 补断言 fault_flags.bit1、x/y/yaw=0、CTRL 无回显 |
| tests-b | TTL hold 250<watchdog 300 余量小；stats 500ms | TTL 测试用 `--watchdog-ms 600`；stats 计数变更立即 flush（原子写） |
| tests-c | S-05 只测 tag；client 吞异常无计数 | 加 CRC 错/AAD 错/重放分项；client 暴露 `aead_fail/replay_drop` |
| tests-d | soak.py 不存在；ref 缺注入参数/seed | 交付 `tools/soak.py`；ref 同步注入/seed/stats |
| tests-e | 文档漂移：18 H.264/FEC、`--report`；16 未回写；03 缺枚举 | 本次 Rev.3 一并回写 |
| protocol-p1 | joint_order_hash 写成 CRC32 | 统一 CRC32C+"\n"（03/15/18） |
| protocol-p1 | 重连窗口矛盾/MTU/单端口未回写 | 02/03/01/04 回写；UDP datagram ≤1280、明文 ≤1200 |
| protocol-p1 | AAD 错负向量缺失；telemetry.proto 缺失 | 增加负向量与 proto 文件（S1 交付） |
| protocol-p1 | 旧 CTS 编码旧语义（claim 直接 CTRL/复位即恢复） | S1 更新 tests/client：claim→arm；复位→release→arm |

## 4. 已确认关闭的 Round 1 P0

- AAD = 帧头且 crc=0（02/03/18 已一致）；
- seq 每方向全局、跨流共享（02/03 已一致）；
- capability mock 视频 rgb888/160×120@10（与 CTS 硬编码一致）；
- 认证门/CLAIMED≠ARMED/两步急停的文字已入 02/03/09/18（实现与测试待 S1）。

## 5. Root 裁定

1. 5 个 Round 2 P0 全部接受为阻塞；Rev.3 逐项给出契约/测试/CI 细节。
2. Rev.3 完成后做**窄范围复审（Round 2b）**：4 名评审员只核对 P0/P1 关闭项与本轮 diff，不再全量重审；
   仍按 0 P0 + P1 关闭/接受才 PASS。
3. Gate 证据：Round 2b 4 份 PASS/有条件 PASS、`cts-report.json` schema、CI run URL 计划；实现阶段持续验证。
