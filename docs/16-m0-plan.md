# 16 M0 实施计划（B 方案：协议内核 · CTS · mock/最小参考 Agent · App 骨架）

> B 方案定位见 [ADR-0014](adr/0014-scope-app-protocol-cts.md)：本项目交付 **Android App + 协议 + CTS +
> mock/最小参考 Agent**；机器人端生产实现由厂商/社区按 [18 实现指南](18-protocol-implementation-guide.md) 完成。
> 本文把 M0 展开为可执行计划：交付物、接口冻结、WBS、3 周排期、验收 Runbook。
>
> M0 完成判据：**CI 全绿 + C++/Kotlin/Python 三端同一套向量 + CTS 静态组/基础动态组跑通 +
> App 真机与 mock 全链路（发现→配对→控制→遥测→看门狗→急停）+ 最小参考 Agent 可构建（x86_64/aarch64）**。
> 日期：2026-11-19。2 人（Android 1、协议/工具/C++ 1），周期 3 周。
> **当前进度**：[reports/m0-progress.md](reports/m0-progress.md)（协议层、向量、C++ 库、CTS 已可运行）。

## 1. 目标与范围

### 1.1 目标（3 周）

| 工作线 | 目标 |
|---|---|
| A（Android） | Kotlin 协议内核 + UDP/发现 + 最小调试骨架（发现/配对/控制/遥测/测试图） |
| C（C++/协议） | `liburc_protocol`（帧/分片/加密/会话）+ mock 服务端 + 最小参考 Agent 骨架 |
| T（工具/测试） | Python 参考实现、测试向量、capability Schema、**CTS 静态/动态框架**、CI |

### 1.2 M0 不做（防蔓延）

- 真实 GStreamer 视频链路、MediaCodec 解码（M1；M0 用 **原始 RGB888 测试图**走 VIDEO 分片）。
- 深度/点云/地图/关节命令（v1.1 增强档）。
- mDNS 发现（M1；M0 只做 UDP 广播发现 + 手动 IP）、相机扫码（M1）。
- 产品级 UI、前台服务、多手柄完整矩阵（M1）。
- 生产级参考 Agent（M0 只做“能连、能控制、能回状态”的骨架；单相机视频在 M1）。
- 跨平台（v1.x/v2）：M0 只保留 KMP-ready 边界与双架构构建。

### 1.3 M0 决策（记录）

| # | 决策 | 理由 |
|---|---|---|
| D1 | mock 与最小参考 Agent 共用 `liburc_protocol` + 同一配置格式 | 一套协议实现两用，避免漂移 |
| D2 | Python `tools/codec_ref` 为测试向量唯一真源 | C++/Kotlin 差分对齐 |
| D3 | M0 视频走 RGB888 测试图（160×120@10，VIDEO 通道分片；capability 如实声明 rgb888） | 不引入 GStreamer/MediaCodec 依赖 |
| D4 | TELEM 从 M0 起用 protobuf | 避免中途换格式导致向量作废 |
| D5 | 加密第 1 天实现（OpenSSL 3 / javax.crypto），默认开启；不提供生产关闭开关（仅隔离测试构建可调试） | 认证/重放是安全地基 |
| D6 | 配对秘密 M0 用控制台 `URCPAIR:<base64>`，M1 加二维码 | 不背相机权限依赖 |
| D7 | 发现 M0 实现 **UDP 广播 DISCOVER/ANNOUNCE**；App 自动列表 | 自动发现是 v1 核心体验，M0 先打通 |
| D8 | aarch64 **QEMU 容器**构建 + 协议向量在 M0 进入 CI | 机器人端 x86_64/ARM64 双目标（07 文档 §10）；交叉工具链留 M2 |
| D9 | CRC32C 用 CRC-32/ISCSI；加密布局按 02/03 文档冻结 | 向量据此生成 |
| D10 | `core:protocol` 保持 KMP-ready（禁止 `android.*`） | v1.x 跨平台迁移零返工 |
| D11 | **CTS 是 M0 交付物**（静态组 + 基础动态组），不是 M1 才做 | 协议必须有可执行验收 |
| D12 | 最小参考 Agent 只做单形态/速度+动作/假 URDF 状态 | 活文档，不做生产 Agent |

### 1.4 待发起人确认（不阻塞）

| # | 事项 | 默认 |
|---|---|---|
| Q1 | LICENSE（Apache-2.0？署名） | 先 `LICENSE.tbd` |
| Q2 | CI 用 GitHub Actions | 是 |
| Q3 | 参考 Agent 是否也要支持“无相机”纯控制模式 | 默认支持（`--no-camera`） |

## 2. 交付物与文件树（M0 结束时）

```
Uni-RoboController/
├── .github/workflows/ci.yml             # lint / vectors+cts-static / agent(x86+aarch64) / android
├── protocol/
│   ├── schemas/capability.schema.json
│   ├── examples/capability.{l4w4,mock_quadruped,mock_humanoid,mock_wheeled,mock_arm}.json
│   └── vectors/{frames,crypto,frag,session}.json      # ≥60 例
├── conformance/                         # CTS（Python + pytest）
│   ├── cts/（discovery.py pairing.py security.py control.py telemetry.py video.py model.py）
│   ├── cts/report.py
│   └── pyproject.toml
├── tools/
│   ├── codec_ref/（urc_ref/ gen_vectors.py difftest.py check_caps.py）
│   └── check_kmp_ready.py
├── agent/                               # C++ 协议库 + mock + 参考 Agent
│   ├── include/urc/{frame,frag,crypto,session,messages,capability}.h
│   ├── src/{frame,crc32c,frag,crypto,session,messages}.cpp
│   ├── apps/mock_robot.cpp
│   ├── apps/urc-reference-agent.cpp     # 最小参考 Agent 骨架
│   ├── tests/                           # CTest 吃 vectors
│   └── CMakeLists.txt
├── android/
│   ├── core/protocol/                   # 纯 JVM，KMP-ready
│   ├── core/transport/                  # UDP + 广播发现
│   └── app/                             # 调试骨架（发现/配对/摇杆/日志/测试图）
└── reference/                           # 参考 Agent 的配置/文档（可选独立目录）
```

## 3. 接口冻结（编码前不再改；改动走文档 + 向量再生成）

同 [16 旧版] 的 1–9 项保持：帧头/消息枚举/握手/CTRL/MODEL_STATE/TELEM/加密布局/超时数值/向量格式；
新增：

10. **发现报文**：`DISCOVER/ANNOUNCE` 字段与端口（02 §4、03 §3）；M0 只广播，M1 加 mDNS。
11. **capability 基础档字段**：`model`、`control.modes`、`safety`、`rates`、`streams`；增强档字段可缺省。
12. **CTS 用例 ID/级别/报告 JSON 格式**：见 [18 文档](18-protocol-implementation-guide.md) §6。

## 4. mock 与参考 Agent 行为

### 4.1 mock_robot（全协议模拟，用于 App/CTS 开发）

```
mock_robot --bind 0.0.0.0 --ctrl-port 47800 --discovery-port 47810 \
  --capability protocol/examples/capability.mock_quadruped.json \
  --secret-file /tmp/urc.secret [--no-camera] \
  [--drop pct] [--hold-next-ms ms] [--corrupt-aead pct] [--stale-state] [--stats-file path]
```

- 广播 `ANNOUNCE`；AUTH 5 次失败锁 30 s；单控制者；CTRL TTL 200 ms；看门狗 300 ms；
  ESTOP 锁存；TELEM 20 Hz；MODEL_STATE 30 Hz（16 关节正弦）；测试图 10 Hz（VIDEO 分片）。
- M0 mock 仅支持 **rgb888** capability：`streams[0].codecs` 必须含 `rgb888`，否则拒绝启动
  （避免 CAPS 声明 H.264/720p、实发 rgb888 160×120 的不一致）；H.264/FEC 在 M2 实现。
- 故障注入开关可组合，行为可断言（供 CTS F 组使用）。

### 4.2 最小参考 Agent（骨架，M0 只到“能连能控”）

```
urc-reference-agent --config /etc/urc/agent.yaml [--no-camera]
```

- 实现 Level 0–1（发现/配对/会话/控制/遥测/安全）+ 假 MODEL_STATE；
- 单形态（mock 四足）适配器；速度/动作命令直接映射到内部模拟状态；
- 视频（M1 接入 GStreamer 单相机）；M0 可只发测试图或 `--no-camera`；
- 提供 `reference/README.md` 说明“这是最小示例，不是生产 Agent”。

## 5. App 调试骨架（非产品 UI）

- 单 `DebugActivity`：发现列表（广播）→ 粘贴 `URCPAIR:` 秘密 → 连接 → 摇杆 CTRL 100 Hz →
  显示 TELEM 回显/看门狗事件/测试图（Bitmap 直显）。
- `core:protocol` JVM 单测吃 `vectors/*.json`；`check_kmp_ready` 保证无平台 API 引用。
- 仅 JVM 单测；M0 不写 instrumentation。

## 6. CI（lint / vectors / cts / mock-integration / asan / arch；Android 在 S4 加入）

| job | 内容 |
|---|---|
| `lint` | Markdown 链接、capability Schema、KMP-ready 检查 |
| `vectors` | Python 参考自测 + `gen_vectors.py --check` + **CTS 静态组** |
| `cts` | CTS 动态组（默认 Python ref）+ 报告校验 |
| `mock-integration` | C++ mock 构建 + per-test CTS + 报告/日志 artifact |
| `mock-asan` | ASAN/UBSAN + ctest + ASAN mock 动态 CTS |
| `mock-soak` | 30 min 浸泡（dispatch / main `[soak]` 触发） |
| `agent-x86_64` / `agent-aarch64` | 原生/QEMU 构建 + ctest；aarch64 `mock_robot --help` |

## 7. WBS（人日，2 人 3 周 ≈ 30 人日）

| ID | 任务 | 线 | 估 | 依赖 | DoD |
|---|---|---|---|---|---|
| T1.1 | 仓库骨架：CMake/Gradle/目录/third_party | C | 2 | — | 空目标可构建 |
| T1.2 | CI job + Schema + KMP-ready 检查 | T | 2 | T7 并行 | 故意坏 JSON 可阻断 |
| T1.3 | aarch64 交叉 + QEMU 向量（agent 矩阵） | C | 1.5 | T1.1,T2.1 | 交叉产物 + QEMU 向量绿 |
| T2.1 | `codec_ref` + `gen_vectors.py` | T | 3 | — | 4 份向量 ≥60 例 |
| T2.2 | **CTS 静态组 + 动态框架** | T | 3 | T2.1 | `cts-report.json` 生成；对 mock 可跑 |
| T3.1 | C++ frame+crc32c+frag | C | 3 | T2.1 | 向量全绿 |
| T3.2 | C++ crypto+session+replay | C | 3 | T3.1 | 向量全绿；`--no-encrypt` |
| T3.3 | C++ protobuf TELEM + capability 加载 | C | 2 | T3.1 | mock 发合法 TELEM |
| T4.1 | Kotlin frame+crc32c+frag（纯 JVM） | A | 3 | T2.1 | 同套向量全绿 |
| T4.2 | Kotlin crypto+session | A | 2 | T4.1 | 同套向量全绿 |
| T5.1 | mock_robot（发现/会话/CTRL/看门狗/ESTOP/注入/测试图） | C | 3 | T3.2,T3.3 | §4.1 行为可断言 |
| T5.2 | 最小参考 Agent 骨架（Level 0–1 + 假模型状态） | C | 2 | T3.3 | App 可连、可控、可看状态 |
| T6.1 | Android UDP 传输 + 广播发现 + LinkStats | A | 3 | T4.2 | 自动发现列表；RTT/丢包可见 |
| T6.2 | 调试骨架 UI（连接/摇杆/日志/测试图） | A | 3 | T6.1 | 真机 Wi-Fi 全链路 |
| T7 | 4 份 mock capability + Schema | T | 1.5 | — | 5 份 JSON 过 Schema |
| T8 | 差分测试 `difftest.py`（C++/Kotlin） | T | 2 | T3.2,T4.2 | 字节级一致 |
| T9 | 验收 Runbook + 报告 + 复盘 | 全员 | 2 | T5,T6,T8 | §9 全绿；`docs/reports/m0-report.md` |

> 关键路径：T2.1 → T2.2/T3.1/4.1 → T3.2/4.2 → T5.1/6.1 → T6.2 → T9。
> 总计约 **30 人日**（2 人 3 周；单人约 6 周）。
> 架构：机器人端目标 x86_64/ARM64；`agent-x86_64`/`agent-aarch64` CI job 分别构建。

## 8. 3 周排期（2 人）

| 周 | Android（A） | 协议/工具/C++（C/T） |
|---|---|---|
| W1 | 骨架、T4.1 协议内核 | T1.1 骨架、T2.1 参考实现/向量、T1.2 CI |
| W2 | T4.2 crypto、T6.1 传输/发现 | T3.1–T3.3 C++ 内核、T2.2 CTS 框架、T1.3 交叉构建 |
| W3 | T6.2 调试骨架 UI | T5.1 mock、T5.2 参考 Agent 骨架、T8 差分、T7 capability |
| W3 末 | 真机联调 | 联调 + 注入开关 + T9 Runbook/报告 |

## 9. M0 验收 Runbook

```bash
# 0) 静态
python tools/codec_ref/gen_vectors.py --check
python tools/codec_ref/check_caps.py
python tools/check_kmp_ready.py
python -m pytest conformance -m static -q      # 报告写入 artifacts/cts-*.json

# 1) 三端向量
cmake -S agent -B agent/build -DURC_BUILD_APPS=ON && cmake --build agent/build -j
ctest --test-dir agent/build --output-on-failure
cmake -S agent -B agent/build-arm64 -DURC_BUILD_APPS=ON   # CI 用 QEMU arm64 容器
cmake --build agent/build-arm64 -j
ctest --test-dir agent/build-arm64 --output-on-failure
./gradlew :core:protocol:test
python tools/codec_ref/difftest.py --all

# 2) 端到端（mock；同一 Wi-Fi 真机时把 --bind 改 0.0.0.0）
./agent/build/mock_robot --bind 0.0.0.0 --secret-file /tmp/urc.secret --discovery-port 47810 \
  --capability protocol/examples/capability.mock_quadruped.json
# 控制台打印 URCPAIR:<base64>；App 调试骨架：
# [ ] 自动发现列表出现 mock（广播）
# [ ] 配对成功；错误秘密 ×5 → 锁定 30 s
# [ ] 摇杆 CTRL 100 Hz；TELEM 回显；间隔 P99 ≤20 ms
# [ ] 杀 App → 300 ms 内 watchdog_fired 零速；重连需重新 arm
# [ ] ESTOP 锁存 + ack；release_estop 后需再 arm 才能运动
# [ ] 测试图 ≥5 fps；中片丢失整帧跳过
# [ ] MODEL_STATE 30 Hz；joint_order_hash 匹配
# [ ] --stale-state → 状态过期告警

# 3) CTS 动态组（P0 矩阵，skipped=0）
URC_CTS_MOCK_BIN=agent/build/mock_robot URC_CTS_REQUIRE_EXTERNAL=1 \
URC_CTS_REPORT=conformance/cts-mock-report.json \
  python -m pytest conformance -m dynamic -q
python tools/check_cts_report.py --suite dynamic --dynamic conformance/cts-mock-report.json
# [ ] 18 §6.2 全部 P0 用例全绿；报告归档

# 4) 参考 Agent
./agent/build/urc-reference-agent --config reference/agent.json --no-camera
# [ ] App 可发现/配对/控制/看 TELEM；按 Ctrl+C 安全退出

# 5) 故障注入 / 浸泡
./agent/build/mock_robot ... --drop 30 --hold-next-ms 250 --corrupt-aead 10 --seed 1
python tools/soak.py --bin agent/build/mock_robot --duration 1800 --rate 100 --drop 5 \
  --seed 1 --report artifacts/soak-report.json
# [ ] 控制降级不误触发急停；重放/TTL/坏 AEAD 计数正确；30 min 无 RSS/fd 泄漏；SIGTERM 退出码 0
```

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 三端 CRC/HKDF 不一致 | 向量驱动；difftest 字节级比对 |
| CTS 过早复杂化拖慢 M0 | M0 只做静态组 + 5–8 条 P0 动态；完整组随 M1 |
| protobuf 版本漂移 | 锁 proto；两端 pin 大版本；向量含编码字节 |
| Windows 开发机差异 | `.gitattributes`；C++ mock 仅 POSIX（Windows 用 Python ref server）；需要本地跑 C++ 用 WSL/容器 |
| aarch64 工具链配置困难 | M0 用 QEMU arm64 容器构建协议内核（无 GStreamer）；交叉工具链留 M2 |
| App 与 mock 时间线错位 | 协议内核先冻结；mock 优先于参考 Agent |
| 范围回摆到“全栈” | ADR-0014 + 本文 §1.2 不做清单；评审会对照 |
| 单人执行 | 序贯 M0≈6 周；先砍 T5.2 参考 Agent 与 T6.2 调试 UI（用 CLI 客户端验证） |

## 11. M1 预览

- 基础档补全：mDNS/二维码、手柄矩阵、视频（GStreamer/MediaCodec）、URDF 四类模型、CTS P0/P1 全绿。
- 参考 Agent：单相机 GStreamer 视频、x86_64/aarch64 目标板验证。
- 实现指南与接入 checklist 随 M1 完善，供第三方接入。

## 12. 完成判据

1. §9 Runbook 全绿，产出 `docs/reports/m0-report.md`。
2. CI job 全绿（lint/vectors/cts/mock-integration/asan/arch；Android 在 S4 后加入）。
3. C++/Kotlin/Python 通过同一套 ≥60 例向量；CTS 静态组 + 基础动态组 P0 全绿。
4. App 与 mock 真机 Wi-Fi 全链路（发现/配对/控制/遥测/看门狗/急停/测试图）。
5. 最小参考 Agent 可构建、可连接、可控制（`--no-camera` 模式）。
6. KMP-ready 检查通过；遗留问题开 Issue 挂 M1；LICENSE 处置有结论。
