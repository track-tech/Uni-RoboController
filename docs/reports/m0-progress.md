# M0 进度报告（2026-11-19）

> 对应计划：[../16-m0-plan.md](../16-m0-plan.md)。当前状态：**M0 进行中（基础协议层与 CTS 已可运行）**。
> 本报告只记录事实与命令输出，完成后并入发布说明。

## 1. 完成情况

| 交付项 | 状态 | 位置 | 验证 |
|---|---|---|---|
| Python 参考编解码 | ✅ | `tools/codec_ref/urc_ref/` | crc/帧/加密/分片/消息自测 |
| 协议测试向量（60 例） | ✅ | `protocol/vectors/{frames,crypto,frag,session}.json` | `gen_vectors.py --check` 通过 |
| capability Schema + 5 份示例 | ✅ | `protocol/schemas/`、`protocol/examples/` | `check_caps.py` 全过 |
| C++ 协议库（帧/CRC/分片/加密/会话/消息） | ✅ | `agent/` | 向量测试 **136 checks / 0 failures** |
| Python 参考服务端（发现/配对/控制/遥测/看门狗/急停/视频/模型状态） | ✅ | `tools/codec_ref/ref_server.py` | CTS 动态测试通过 |
| CTS 静态组 | ✅ | `conformance/test_static.py` | 7 passed |
| CTS 动态组 | ✅ | `conformance/test_protocol.py` | 10 passed |
| CI（lint/vectors/CTS/双架构 C++） | ✅ | `.github/workflows/ci.yml` | run #4 全绿（含 aarch64 QEMU） |
| 工具（链接检查/KMP-ready/差分） | ✅ | `tools/` | 本地通过 |
| aarch64 构建 | ✅ | CI QEMU arm64 容器 | 编译 + CTest 通过 |
| C++ mock_robot / 最小参考 Agent | ⏳ | `agent/apps/`（待建） | — |
| Kotlin `core:protocol` | ⏳ | `android/`（待建） | — |
| Android 调试骨架 | ⏳ | `android/app/`（待建） | — |

## 2. 实现过程中发现并修正的协议歧义

编码实现暴露了设计文档里的循环定义/笔误，已回写文档：

| # | 问题 | 修正 |
|---|---|---|
| 1 | 加密 AAD “帧头原样含 crc” 与 “crc 覆盖密文” 循环依赖 | AAD = 帧头且 **crc=0**；crc 不参与 GCM，但 CRC 校验覆盖线上载荷 |
| 2 | CAPS 只有 zstd，无编码标识 | 增加 `encoding u8`（0=raw，1=zstd） |
| 3 | 通用分片头字段列出 4 项（10 B）却标 8 B | 固定 8 B：`msg_id u32, pkt_idx u16, pkt_cnt u16` |
| 4 | `key_confirm` 派生方式未定 | `HKDF-Expand(PRK, "urc/session/v1/confirm", 8)` |
| 5 | 发现报文只有文字描述 | 在 02 文档给出 DISCOVER/ANNOUNCE 字节布局 |
| 6 | `caps_hash`/`joint_order_hash` 定义不明确 | caps_hash=SHA-256(canonical JSON)[0:4]；joint_order_hash=CRC32C(名字以 `\n` 连接) |
| 7 | Python `unpack_announce` 偏移写错（10 vs 9） | 已修正，C++/Python 一致 |

## 3. 本地验证命令与结果

```bash
# 静态
python tools/check_links.py                          # links ok
python tools/check_kmp_ready.py                      # skip（android 尚未创建）
python tools/codec_ref/check_caps.py                 # all capabilities ok
python tools/codec_ref/gen_vectors.py --check        # 4 文件 OK

# C++（Windows MSYS2 ucrt64 + OpenSSL 3）
g++ -std=c++20 -Iagent/include -Iagent/third_party ...  # 构建 urc_vectors
agent/build/urc_vectors.exe protocol/vectors         # checks=136 failures=0

# CTS
python -m pytest conformance -m static -q            # 7 passed
python -m pytest conformance -m dynamic -q           # 10 passed
```

远程 CI（GitHub Actions，run #4）：`lint`、`vectors`、`cts`、`agent-x86_64`、`agent-aarch64`
五个 job 全绿；aarch64 通过 QEMU arm64 容器编译并运行 CTest。
CI 运行记录：<https://github.com/track-tech/Uni-RoboController/actions/workflows/ci.yml>

## 4. 下一步（按关键路径）

1. C++ `mock_robot`（复用 `liburc_protocol`，发现/会话/控制/遥测/看门狗/急停/注入）——替换 Python 参考服务端，作为官方 mock。
2. Kotlin `android/core/protocol`（纯 JVM，吃同一套 vectors）+ `core:transport`。
3. Android 调试骨架（发现/配对/摇杆/日志/测试图直显）。
4. 最小参考 Agent 骨架（`agent/apps/urc-reference-agent.cpp`，单形态/无相机模式可跑）。
5. 远程 CI 实跑（含 aarch64），修复平台差异。
6. 完成后跑 16 文档 §9 Runbook，产出正式 M0 报告。

## 5. S1 进展（C++ mock_robot，2026-11-21）

- 实现：`agent/src/{net,mock_server}.cpp`、`agent/apps/mock_robot.cpp`、`agent/include/urc/{net,mock_server}.h`；
  消息补全 SESSION_CTRL/ESTOP/EVENT/ERROR/PING/PONG/FEEDBACK/VIDEO；`liburc_protocol` 复用。
- Python 参考实现同步：`ref_server.py` 冻结语义（认证门/claim-arm/两步急停/会话超时/TTL/注入/stats）。
- CTS：P0 矩阵（11 dynamic + CTS-K-01 arch）；`conftest.py` 支持 Python ref / C++ mock / 外部 target；
  `cts-report.json` schema + `tools/check_cts_report.py`；新增 `protocol/vectors/replay.json`。
- 向量：`checks=167 failures=0`（6 类向量，含跨流重放/错误 AAD/新消息）。
- CI（run #10，`ed4d1bd`）：lint / vectors / cts / mock-integration / mock-asan / agent-x86_64 / agent-aarch64
  **全部成功**；mock-soak 未触发（需 dispatch 或 `[soak]` 提交）。
  <https://github.com/track-tech/Uni-RoboController/actions/runs/44781937841>
- 本地验证：Python ref CTS 23 passed；C++ mock CTS 16 passed（3 次连续）；C++ 向量 167 checks；构建 `-Werror` 通过。
- 待办：30 min soak 执行证据、独立审计（task-6）、S2 最小参考 Agent。

### 5.1 审计与最终结果（2026-11-21）

- 独立审计初判 **FAIL**（P0-01：CTS-C-03 未测未知 mode，mock 未校验 `CTRL.mode`；P1×8）；
  修复后窄范围复验 **PASS**（P0=0、P1 全关闭、mutant 全部可捕获）。见 [stage-S1-audit.md](../reviews/stage-S1-audit.md) §10.8。
- 修复提交：`77fd355`（P0/P1）、`b17401e`（S-02/S-05 可证伪性）。
- CI：run [44794676731](https://github.com/track-tech/Uni-RoboController/actions/runs/44794676731) 7/7 job success；
  run [44791424581](https://github.com/track-tech/Uni-RoboController/actions/runs/44791424581) 8/8（含 30 min soak success）。
- CTS：dynamic 11 个 P0 全 passed + arch K-01 passed；Python ref 25 passed、C++ mock 17 passed（连续 3 次）；
  C++ 向量 167 checks。
- 遗留 P2：`--verbose`、TTL 注入语义、URCPAIR 日志约束、soak watchdog/dropped 断言、ANNOUNCE 限速 CTS。
