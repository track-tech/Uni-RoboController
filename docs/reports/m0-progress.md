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
| CI（lint/vectors/CTS/双架构 C++） | ✅ | `.github/workflows/ci.yml` | 待 GitHub 实际运行确认 |
| 工具（链接检查/KMP-ready/差分） | ✅ | `tools/` | 本地通过 |
| aarch64 构建 | ⏳ | CI `ubuntu-24.04-arm` | 本地无 ARM 环境，待 CI 验证 |
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

## 4. 下一步（按关键路径）

1. C++ `mock_robot`（复用 `liburc_protocol`，发现/会话/控制/遥测/看门狗/急停/注入）——替换 Python 参考服务端，作为官方 mock。
2. Kotlin `android/core/protocol`（纯 JVM，吃同一套 vectors）+ `core:transport`。
3. Android 调试骨架（发现/配对/摇杆/日志/测试图直显）。
4. 最小参考 Agent 骨架（`agent/apps/urc-reference-agent.cpp`，单形态/无相机模式可跑）。
5. 远程 CI 实跑（含 aarch64），修复平台差异。
6. 完成后跑 16 文档 §9 Runbook，产出正式 M0 报告。
