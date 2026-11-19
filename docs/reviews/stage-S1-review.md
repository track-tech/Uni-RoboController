# Stage S1 对抗评审汇总（Round 1）

| 项 | 值 |
|---|---|
| 阶段 | S1 C++ `mock_robot` |
| 评审轮次 | Round 1（2026-11-20） |
| 评审对象 | `stage-S1-brief.md`（Draft） |
| 评审员 | review-protocol / review-safety / review-build / review-tests（独立只读） |

## 1. Verdict

| 评审员 | Verdict | P0 | P1 | 主要结论 |
|---|---|---|---|---|
| 协议/互操作 | **FAIL** | 2 | 4 | AAD 文档自相矛盾；seq/nonce 域未冻结，多流会 nonce 复用 |
| 安全/失效 | **FAIL** | 3 | 6 | 参考服务端未认证即可 claim/控制/清急停；验收缺 P0；claim 自动 arm |
| 构建/平台 | CONDITIONAL | 0 | 6 | ASAN/soak 无载体；外部 target 假绿；隔离/注入/arch/Windows 缺口 |
| 测试/范围 | **FAIL** | 1 | 7 | 急停复位语义与 09/03 冲突；外部 target 不可隔离；P0 用例缺失/假绿 |

**结论：Gate FAIL，S1 实现不得开始。** 需 Rev.2 Brief + 回写协议文档后第二轮评审。

## 2. 合并后的 P0（必须关闭）

| ID | 问题 | 证据 | Rev.2 决议 |
|---|---|---|---|
| P0-1 | AAD 文档写“帧头原样含 crc”，实现/02 为 crc=0；App 按 03/18 实现会全部解密失败 | 03:40、18:55 vs 02:93、03:115、frame.cpp:60/102、m0-progress:30 | 冻结 AAD=帧头且 crc=0；改 03/18；增加“错误 AAD 必须失败”负向量 |
| P0-2 | seq 文档为“每流独立”，nonce=dir‖seq → 多流同 seq 时 GCM nonce 复用 | 03:26/316 vs 02:92；crypto.py:65 | 冻结“每方向全局单调 seq（跨流共享）”；重放窗口每方向；改 02/03 |
| P0-3 | Python ref_server 未认证即可 claim/CTRL/ESTOP(0)，违反 HELLO/AUTH 前置与 I3/I4/I6 | ref_server.py:173-212,255-328；实测 | 冻结 fail-closed 认证门；ref_server 同步修复；新增未认证负例 CTS-P-02 |
| P0-4 | claim 自动 arm；watchdog 后任意 CTRL 自动 arm，违反显式使能 | ref:265-267,316-317；09:54 | 状态机：CLAIMED 后必须 action3 才 ARMED；watchdog→disarmed；CTRL 仅 ARMED 接受 |
| P0-5 | 急停复位语义冲突：Brief 说 action4 清除并 arm；09 要求复位后重新 arm | Brief:96 vs 09:64-65/92、03:173-177 | 冻结两步：action4 仅清锁存（不 arm）；action3 再 arm；ESTOP(0) 不解锁；更新 CTS |
| P0-6 | 验收=现有 10 项，缺 18 §6.2 P0 用例；篡改/watchdog 断言不可证伪 | test_protocol.py、18:109-130 | 验收改为 18 P0 矩阵全绿 + 新增可证伪断言；变异检查预登记 |

## 3. 合并后的 P1（Rev.2 必须处理或明确降级）

| 组 | 问题 | 决议 |
|---|---|---|
| 参考实现 | ref_server 与冻结语义冲突（auto-arm、ESTOP(0)、无认证、无 5s 超时、无 TTL） | 列入 S1 改动；两种 target 均跑同一 CTS |
| 隔离/假绿 | 常驻外部 mock 无法按用例隔离；env 未设静默回退 Python ref；发现用例可 SKIP；fault 用例无实例 | per-test C++ mock 启动（`URC_CTS_MOCK_BIN`）；`URC_CTS_REQUIRE_EXTERNAL=1`；skipped=0；注入用 fixture 参数起独立实例 |
| TTL | `--delay-ms` 连续流会触发 watchdog，无法区分 TTL；单线程 sleep 破坏定时 | 改为 `--hold-next-ms` 一次性扣包；recv 时刻记时；读取 `ttl_dropped` 统计断言；`--seed` 可复现 |
| 注入 | `--corrupt` 只坏 magic，不测 AEAD；无 seed | 改为 `--corrupt-aead`：翻转密文并按新密文重算 CRC，强制 AEAD 失败；增加计数器 |
| 消息/向量 | C++ 缺 SESSION_CTRL/ESTOP/EVENT/ERROR/VIDEO/PONG；新 codec 无向量 | 扩展 messages.h/.cpp + gen_vectors + session/vectors；三端一致 |
| CAPS/视频 | capability 声明 h264 1280×720，mock 发 RGB 160×120；CTS 硬编码 | capability mock 流改 rgb888 160×120@10；CTS 断言 CAPS 与实发帧一致；冻结 CAPS mtu/msg_id/canonical |
| 流/端口 | 文档列 video/depth/map 独立端口，ref 全走 ctrl socket | 冻结 v1 单 UDP 端口多流（stream 字段）；端口字段预留；改 02/03 |
| 安全细节 | 会话过期清理、锁存保持、release/arm 属主、HELLO 覆盖、限速、CTRL bit1、日志泄密 | 逐项写入冻结表与负例 |
| ASAN/soak | 无 CI 载体；浸泡标准不可量化 | 新增 asan job；soak job（workflow_dispatch / `[soak]` 提交触发）30 min，RSS/fd/stats 阈值断言 |
| 构建 | aarch64 缺 `-DURC_BUILD_APPS=ON`；Windows Winsock 无 CI；build-arm64 未忽略 | aarch64 加 APP 构建+`--help` 冒烟；**S1 改为 POSIX-only**（Windows 用 Python ref）；`.gitignore` 补；加 `-Werror` |
| 文档 | 07 YAML/编译期注入漂移；16 视频 320×240 与环境变量/报告不符 | 列入 S1 文档回写；16/18 改 env/报告；07 改 JSON+运行期 flag |

## 4. 已攻击未见异常（评审员确认）

- CRC32C 参数与“crc 覆盖帧头(置0)+密文+tag”自洽；
- HELLO/HELLO_ACK/AUTH_OK/ANNOUNCE 字段布局与向量一致；
- 通用 8B 分片与 23B 视频头未混用；
- 0 长载荷/1200 B 边界已有向量；未知 type 在码流层保留。

## 5. Root 裁定

1. 六个 P0 全部接受为阻塞项；Rev.2 Brief 逐项给出冻结语义与测试。
2. 先回写 docs/02、03、09、18 的冲突文字，再提交 Round 2 评审。
3. Round 2 由原 4 名评审员复查；若仍有 P0，停止并上报用户。
4. Round 2 PASS 前，`task-5`（S1 实现）保持 blocked。
