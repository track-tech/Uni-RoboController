# 16 M0 实施计划（仓库骨架 · 协议内核 · Mock 机器人 · 调试骨架）

> 本文把 [10-roadmap.md](10-roadmap.md) 的 M0 展开为**可执行计划**：交付物清单、接口冻结项、
> 任务分解（WBS）、两周排期、验收 Runbook。M0 完成的判据是：
> **CI 全绿 + C++/Kotlin/Python 三方通过同一套测试向量 + 真实 Wi-Fi 上 Android 调试骨架
> 与 mock_robot 全链路跑通（配对→控制→遥测→看门狗→急停）**。
> 日期：2026-11-18。执行过程中本文是 M0 的唯一任务入口，变更须回写本文。

## 1. 目标与范围

### 1.1 目标（2 周，3 条并行工作线）

| 工作线 | 目标 |
|---|---|
| A（Android） | Kotlin 协议内核 + UDP 传输 + 最小调试骨架（能连 mock、发控制、收遥测/测试图） |
| C（C++/Linux） | Agent 协议内核（codec/frag/crypto/session）+ mock_robot + CMake/CTest |
| T（工具/测试） | Python 参考编解码、测试向量三端对齐、capability JSON Schema、CI、差分测试 |

### 1.2 M0 明确不做（防范围蔓延）

- GStreamer/MediaCodec 视频链路（M2；M0 用**原始 RGB888 测试图**走协议分片，先验证传输层）。
- 真实深度/点云/地图、`urdf_bundle` 完整版（M3；M0 仅交付 4 份示例 capability + 内置假关节模型）。
- rl_sar 补丁与实机（M5；但 **R0 补丁接口评审在第 2 周启动**，只评审不编码）。
- 产品级 Compose UI、前台服务、相机扫码（M1）。
- WebRTC、录制导出（M2 起分批引入）。
- 目标板（ARM 硬件编码/GStreamer/相机）验证（M2；M0 只做 aarch64 交叉构建 + QEMU 协议单测）。
- 对抗全量（14 文档）；M0 只做**故障注入冒烟**（丢包/重放/篡改各一轮）。

### 1.3 M0 期间做出的实现级决策（记录，避免反复）

| # | 决策 | 理由 |
|---|---|---|
| D1 | mock_robot 用 **C++ 复用 Agent 协议内核** `liburc_protocol` | 一套实现两用（mock 即内核的首个消费者），避免 Python/C++ 双实现漂移 |
| D2 | 另建 **Python 参考编解码** `tools/codec_ref` | 测试向量的唯一真源；供 C++/Kotlin 差分对齐 |
| D3 | M0 视频走**原始 RGB888 测试图帧**（320×240@10 Hz，走 VIDEO 分片路径） | 不背 MediaCodec/GStreamer 依赖，先把分片/重组/FEC/过期丢弃跑通 |
| D4 | TELEM 从 M0 起就用 **protobuf**（按 [03-protocol.md](03-protocol.md) §7.5） | 中途换线格式会让全部向量作废 |
| D5 | 加密第 1 天实现（OpenSSL 3 / `javax.crypto`）；提供 `--no-encrypt` 调试开关但**默认开启** | 认证/重放是安全地基，晚做返工全部向量 |
| D6 | 配对秘密 M0 用**控制台打印 + 手动粘贴**（`URCPAIR:<base64>`），相机扫码留 M1 | 调试骨架不背相机权限与 zxing 依赖 |
| D7 | 扫描/手动 IP 并存；mDNS 留 M1（M0 只做 UDP 广播发现 + 手动 IP） | NsdManager 与 MulticastLock 是真实的坑，M0 不引入 |
| D8 | **M0 引入 aarch64 交叉构建**（编译 + QEMU 协议向量单测）；ARM 硬件编码/目标板验证在 M2 | 机器人端目标为 x86_64 或 ARM64（见 07 文档 §10），双架构必须从 M0 起进入 CI，避免后期移植返工 |
| D9 | CRC32C 定为 **CRC-32/ISCSI**（见 03 文档 §2），加密 nonce/方向子密钥布局已冻结（02 文档 §5） | 本轮已回写协议文档，向量据此生成 |
| D10 | M0 起执行 **KMP-ready 边界**：`core:protocol` 禁止 `android.*`/`androidx.*`；crypto/transport/discovery 以接口隔离；加一条 CI 检查 | 为 v1.x iOS/桌面/Web 迁移零返工（见 17 文档） |

### 1.4 待项目发起人确认（阻塞项，不阻塞 M0 开工）

| # | 事项 | 影响 | 默认值（未确认时按此执行） |
|---|---|---|---|
| Q1 | LICENSE 文件（Apache-2.0？署名？） | 仓库无 LICENSE 不能发 Release | M0 只放 `LICENSE.tbd` 占位说明，v0.1 发布前必须定 |
| Q2 | CI 是否用 GitHub Actions 免费_runner | 排期按 GH Actions 写 | GH Actions |
| Q3 | 人力是否为 3 线并行（A/C/T） | 排期伸缩 | 按 3 线排；若单人，M0 拉长到 4–5 周 |

## 2. 交付物与文件清单（M0 结束时的仓库形态）

```
Uni-RoboController/
├── .github/workflows/ci.yml                 # lint / vectors / agent-build / android-build
├── .gitignore / .gitattributes              # 已存在
├── LICENSE.tbd                              # 占位（Q1 确认后替换为正式 LICENSE）
├── CONTRIBUTING.md                          # 精简版：构建入口 + 提交规范 + 文件头要求
├── docs/                                    # 已存在（本轮新增 16-m0-plan.md）
├── protocol/
│   ├── README.md                            # 已存在，更新构建说明
│   ├── schemas/capability.schema.json       # 能力描述 JSON Schema（草案 2020-12）
│   ├── examples/
│   │   ├── capability.l4w4.json             # 已存在，接 Schema 校验
│   │   ├── capability.mock_quadruped.json   # 新增：mock 四足（16 DOF 假关节）
│   │   ├── capability.mock_humanoid.json    # 新增：mock 人形（29 DOF）
│   │   ├── capability.mock_wheeled.json     # 新增：mock 轮足（与 l4w4 同构，含 height/pitch 通道）
│   │   └── capability.mock_arm.json         # 新增：mock 机械臂（7 DOF + 夹爪，joint_position 接口）
│   └── vectors/                             # 测试向量（三端共用的唯一真源）
│       ├── frames.json                      # 帧编解码 ~30 例（含非法/边界）
│       ├── crypto.json                      # HKDF/AES-GCM/重放窗口 ~15 例
│       ├── frag.json                        # 分片/重组/FEC ~15 例
│       └── session.json                     # 握手/认证/急停/看门狗场景 ~10 例
├── tools/
│   ├── codec_ref/                            # Python 参考实现（生成向量 + 差分驱动）
│   │   ├── urc_ref/（frame.py crc.py crypto.py messages.py）
│   │   ├── gen_vectors.py                   # 从场景描述生成 vectors/*.json
│   │   ├── difftest.py                      # 调 C++ CLI 与 Kotlin CLI 对比输出
│   │   └── check_caps.py                    # 用 jsonschema 校验全部 examples
│   └── mock_robot/                          # （二进制来自 agent/mock 目标，源码在 agent/ 内）
├── agent/                                   # C++20 库 + mock 可执行
│   ├── CMakeLists.txt
│   ├── include/urc/{frame.h,frag.h,crypto.h,session.h,messages.h,capability.h}
│   ├── src/{frame.cpp,crc32c.cpp,frag.cpp,crypto.cpp,session.cpp,messages.cpp}
│   ├── apps/mock_robot.cpp                  # mock_robot 主程序（复用 liburc_protocol）
│   ├── third_party/（FetchContent：OpenSSL 3、protobuf、yaml-cpp、spdlog、Catch2/GTest）
│   └── tests/                               # CTest：直接吃 protocol/vectors/*.json
└── android/
    ├── settings.gradle.kts / build.gradle.kts / gradle/wrapper/
    ├── core/protocol/                       # 纯 Kotlin/JVM，无 Android 依赖（可单测）
    │   └── src/…（Frame.kt Crc32c.kt Frag.kt Crypto.kt Messages.kt）
    ├── core/transport/                      # UDP + 协程（Android 依赖最小化）
    └── app/                                 # M0 调试骨架（单 Activity + Compose 调试屏）
        └── src/androidTest? → 否；仅 src/test（JVM）+ 一个 DebugActivity
```

> 每个源文件遵守工作区规范：SPDX 头（`SPDX-License-Identifier: Apache-2.0` 待 Q1）、
> 中文注释、英文日志。

## 3. 接口冻结清单（编码开始前不得再改，改动须走文档 + 向量再生成）

1. **帧头 32 B**：[03-protocol.md](03-protocol.md) §2（含 CRC32C 参数、AAD 规则）。
2. **消息枚举与方向**：03 §3（M0 实现 0x01–0x0F、0x19、0x20/0x21；0x10/0x11 的 H.264 路径
   留 M2，但分片头格式 M0 用 VIDEO 通道承载 RGB 测试图验证）。
3. **握手时序与字节布局**：03 §4（HELLO/AUTH/CAPS + 会话超时 + 认证锁定）。
4. **CTRL 载荷**：03 §5（mode/axes/buttons/deadman；TTL 200 ms；重复发送 2 次）。
5. **MODEL_STATE 载荷**：03 §7.8（joint_order_hash 必须与 capability 一致）。
6. **TELEM protobuf**：`protocol/telemetry.proto`（M0 新增文件，字段按 03 §7.5；`fault_flags`、
   `remote_age_ms` 必填，供看门狗观测）。
7. **加密布局**：02 §5（方向子密钥、12 B nonce、AAD、重放窗口 2048）。
8. **超时与限速数值**：[09-safety.md](09-safety.md)（TTL 200 ms / 看门狗 300 ms / 会话 5 s /
   认证失败锁定 5 次 30 s）。
9. **测试向量格式**：`protocol/vectors/*.json`，每例
   `{"name": "...", "given": {...字段或十六进制输入...}, "expect": {...或 "hex": "..."}}`；
   三端测试直接读取同一文件，禁止各自硬编码期望值。
10. **KMP-ready 边界**：`android/core/protocol` 只允许 Kotlin 标准库与协议自身类型；
   加密/网络/发现通过接口注入；任何 `android.*`/`androidx.*` 引用由 CI 拒绝合入。

## 4. mock_robot 行为规格（`agent/apps/mock_robot.cpp`）

### 4.1 启动与配置

```
mock_robot --bind 0.0.0.0 --ctrl-port 47800 --http-port 47880 \
           --capability protocol/examples/capability.mock_quadruped.json \
           --secret-file /tmp/urc.secret          # 不存在则生成并打印 URCPAIR:<base64>
           [--drop pct] [--delay ms] [--stale-state] [--corrupt crc|payload]
           [--no-encrypt]                          # 仅调试；默认加密开启
```

### 4.2 会话与安全行为（必须可测）

| 行为 | 规格 |
|---|---|
| 发现 | UDP 广播 `DISCOVER`→单播 `ANNOUNCE`（无 mDNS） |
| 配对 | 固定秘密文件；`AUTH` 校验 HMAC；错 5 次锁 30 s，回 ERROR 0x0101/0x0602 |
| 单控制者 | 第二个 `SESSION_CTRL(claim)` → ERROR 0x0103；已有会话 5 s 无包失效 |
| CTRL | 100 Hz 消费；TTL>200 ms 丢弃并计数；越界 axes 拒绝（ERROR 0x0301 限速日志） |
| 看门狗 | >300 ms 无 CTRL → TELEM 标记 `watchdog_fired`、假机器人“零速”；恢复需重新 arm |
| ESTOP | 锁存；只接受显式复位流程；EVENT(estop_acked) 回执 |
| 状态新鲜度 | `--stale-state` 模式：停发 MODEL_STATE，验证消费侧置灰/告警路径 |

### 4.3 数据流

- **TELEM**：20 Hz protobuf（FSM=mock、命令回显、`remote_age_ms`、丢包计数）。
- **MODEL_STATE**：30 Hz；16 关节正弦摆动 + 根位姿绕圈（无 URDF 也先发，M0 骨架只打印统计）。
- **测试图**：VIDEO 通道 320×240 RGB888 @10 Hz，按 03 §7.2 分片头走分片/FEC（XOR 1:8）；
  接收端丢中片→整帧丢弃；`--drop/--delay/--corrupt` 验证降级。

### 4.4 故障注入开关（14 文档的冒烟子集）

`--drop 30 --delay 100 --corrupt payload --stale-state` 必须可独立/组合开启，行为可预测、可断言。

## 5. Android 调试骨架规格（`android/app`，非产品 UI）

- 单 `DebugActivity`（Compose）：日志区 + 连接区（IP:Port + 粘贴 `URCPAIR:` 秘密）+ 摇杆区 + 统计区。
- `core-protocol` 纯 JVM：吃 `vectors/*.json` 的单测必须全绿（与 C++ 同一套向量）。
- `core-transport`：协程 UDP；重连退避 0.5/1/2/4 s；`LinkStats`（RTT/丢包/间隔 P99）。
- 控制发送：屏幕双摇杆 → CTRL @100 Hz（deadman=按住才发 1）；显示 mock 回显与看门狗事件。
- 测试图：RGB 帧组装 → `Bitmap` 直显（约 5–10 fps 即可，验证分片重组）。
- 仅 JVM 单测（`src/test`）；M0 不写 instrumentation/emulator 测试。

## 6. CI 规格（`.github/workflows/ci.yml`，四 job）

| job | 触发 | 内容 |
|---|---|---|
| `lint` | 全部 PR/push | Markdown 相对链接检查；`check_caps.py` 校验 5 份 capability；向量 JSON 语法 |
| `vectors` | 全部 | `codec_ref` 自测（Python 吃自己生成的向量）；`gen_vectors.py --check` 确认向量与源同步 |
| `agent-build` | `agent/**` 变更 + 全部 push | ubuntu-latest：CMake 矩阵 **x86_64 原生 + aarch64 交叉**；构建 `liburc_protocol` + `mock_robot`；x86 直跑 CTest，aarch64 产物在 QEMU 下跑协议向量 |
| `android-build` | `android/**` 变更 + 全部 push | ubuntu-latest：JDK 17 + Android SDK，`./gradlew :core:protocol:test :app:assembleDebug` |

> Gradle wrapper 的 `gradle-wrapper.jar` 允许入库（`.gitattributes` 已标 binary）。
> 分支保护建议（网页操作）：`main` 要求 CI 绿 + squash merge；先由发起人在 GitHub 上开启。

## 7. WBS（工作分解，估算单位：人日）

| ID | 任务 | 线 | 估 | 依赖 | DoD |
|---|---|---|---|---|---|
| T1.1 | 仓库骨架：CMake/Gradle/目录/third_party FetchContent | C | 2 | — | 空目标可构建，`ctest`/`gradlew test` 空跑通过 |
| T1.2 | CI 四 job + `check_caps.py` + capability Schema | T | 2 | T7 并行 | 任一 job 失败可阻断；故意提交坏 JSON 验证 |
| T1.3 | aarch64 交叉构建 + QEMU 向量单测（agent-build 矩阵） | C | 1.5 | T1.1、T2.1 | 交叉产物生成；QEMU 下 frames/crypto 向量全绿 |
| T2.1 | `codec_ref` Python：frame/crc/crypto/messages + `gen_vectors.py` | T | 3 | — | 生成 4 份向量文件；Python 自测全绿 |
| T3.1 | C++ 内核：frame+crc32c+frag | C | 3 | T2.1 | CTest 消费 frames/frag 向量全绿 |
| T3.2 | C++ 内核：crypto(OpenSSL)+session+replay | C | 3 | T3.1 | crypto/session 向量全绿；`--no-encrypt` 可关 |
| T3.3 | C++ protobuf TELEM + capability 加载（yaml-cpp/json） | C | 2 | T3.1 | mock 能发合法 TELEM/加载 5 份 capability |
| T4.1 | Kotlin 内核：frame+crc32c+frag（纯 JVM） | A | 3 | T2.1 | 同套向量全绿 |
| T4.2 | Kotlin crypto(javax.crypto)+session | A | 2 | T4.1 | crypto/session 向量全绿 |
| T5.1 | mock_robot（会话/CTRL/看门狗/ESTOP/注入开关） | C | 3 | T3.2,T3.3 | §4 行为逐条可断言；含测试图发送 |
| T6.1 | Android UDP transport + LinkStats | A | 2 | T4.2 | 对 mock 的 RTT/丢包统计可见 |
| T6.2 | 调试骨架 UI（连接/摇杆/日志/统计/测试图直显） | A | 3 | T6.1 | 真机 Wi-Fi 全链路手动跑通 |
| T7 | 4 份 mock capability + Schema + 校验脚本 | T | 1.5 | — | 5 份 JSON 全部过 Schema |
| T8 | 差分测试 `difftest.py`（驱动 C++ CLI 与 Kotlin CLI） | T | 2 | T3.2,T4.2 | 三端同向量输出逐字节一致 |
| T9 | 验收 Runbook 执行 + 报告 + 复盘（含 R0 评审材料） | 全员 | 1.5 | T5,T6,T8 | §9 全绿；产出 `docs/reports/m0-report.md` |

> 关键路径：T2.1 → T3.1/4.1 → T3.2/4.2 → T5.1/6.1 → T6.2 → T9。
> 总计约 **33.5 人日**（3 线并行 ≈ 2 周；单人 ≈ 6.5–7 周按 D 序贯执行）。
> **架构矩阵**：机器人端目标为 x86_64 或 ARM64（见 07 文档 §10），`agent-build` 必须同时产出两种架构。

## 8. 两周排期（3 线并行）

| 周 | A（Android） | C（C++） | T（工具/测试） |
|---|---|---|---|
| W1 前半 | — | T1.1 骨架 | T1.2 CI 起步、T7 capability+Schema、T2.1 参考实现 |
| W1 后半 | T4.1 Kotlin frame/frag | T3.1 C++ frame/frag | T2.1 收尾出向量 |
| W2 前半 | T4.2 crypto/session | T3.2 crypto/session、T3.3 TELEM/capability | T8 差分框架 |
| W2 后半 | T6.1 transport、T6.2 骨架 UI | T5.1 mock_robot | T1.2 CI 收尾、T8 三端对齐 |
| W2 末 | 联调（真实 Wi-Fi） | 联调 + 注入开关 | T9 Runbook + 报告 + R0 评审会（rl_sar 补丁接口，只评审） |

## 9. M0 验收 Runbook（全部通过才算 M0 完成）

```bash
# 0) 本地静态
python tools/codec_ref/gen_vectors.py --check        # 向量与源同步
python tools/codec_ref/check_caps.py                 # 5 份 capability 过 Schema
python tools/check_kmp_ready.py                      # core:protocol 不得引用 android.*/androidx.*

# 1) 三端向量
cmake -S agent -B agent/build && cmake --build agent/build -j
ctest --test-dir agent/build --output-on-failure     # C++ x86_64 吃 vectors/*.json
cmake -S agent -B agent/build-arm64 -DCMAKE_TOOLCHAIN_FILE=toolchains/aarch64-linux-gnu.cmake
cmake --build agent/build-arm64 -j                   # aarch64 交叉产物
qemu-aarch64 -L /usr/aarch64-linux-gnu ./agent/build-arm64/tests/urc_vectors  # QEMU 跑向量
./gradlew :core:protocol:test                        # Kotlin 吃同一套 vectors
python tools/codec_ref/difftest.py --all             # 三端逐字节一致

# 2) 端到端（同一 Wi-Fi，手机真机）
#   机器人侧（或同机回环 127.0.0.1）
./agent/build/mock_robot --secret-file /tmp/urc.secret \
    --capability protocol/examples/capability.mock_quadruped.json
#   → 控制台打印 URCPAIR:<base64>；Android 调试骨架粘贴连接
#   手动断言清单：
#   [ ] 配对成功；错误秘密 ×5 → 锁定 30 s（0x0602）
#   [ ] 摇杆 CTRL 100 Hz；mock 回显正确；间隔 P99 ≤ 20 ms
#   [ ] 杀掉 App → 300 ms 内 mock watchdog_fired、零速；重连需重新 arm
#   [ ] ESTOP → 锁存 + estop_acked；复位流程生效
#   [ ] 测试图 ≥5 fps 显示；中片丢弃时整帧跳过不花屏
#   [ ] MODEL_STATE 统计：30 Hz、joint_order_hash 匹配
#   [ ] --stale-state → 骨架状态过期告警路径生效

# 3) 故障注入冒烟（对抗子集，M0 只做行为可预测）
./agent/build/mock_robot ... --drop 30 --delay 100 --corrupt payload
#   [ ] 控制降级但看门狗不误触发急停；恢复后自动继续
#   [ ] 重放录制包（difftest 的 replay 样本）→ 100% 拒绝并计数
#   [ ] 无崩溃、无内存增长（30 min 浸泡）

# 4) CI
#   [ ] 四 job 全绿；README 挂 badge
#   [ ] agent-build 同时产出 x86_64 与 aarch64；QEMU 下协议向量一致
```

## 10. 风险与缓解（M0 特有）

| 风险 | 缓解 |
|---|---|
| 三端 CRC32C/HKDF 细节不一致 | 向量驱动开发（T2.1 先行）；`difftest` 逐字节比对 |
| protobuf 版本漂移（C++/Kotlin 生成代码不一致） | 锁 `telemetry.proto` 版本注释；两端 pin 大版本；向量含编码字节 |
| Windows 开发机差异（换行/路径） | `.gitattributes` 已定；CI 以 ubuntu 为准；本地 Windows 用 WSL 跑 agent |
| 真机 Wi-Fi 不可控抖动影响调试 | 联调优先 5 GHz 同 AP；`LinkStats` 可视；必要时用模拟器 `10.0.2.2`（注意 **adb reverse 仅支持 TCP，UDP 不可用**） |
| Gradle wrapper 二进制入库争议 | 官方推荐方式（wrapper jar 入库）；`.gitattributes` 标 binary |
| 范围蔓延到 UI/视频 | §1.2 不做清单 + 评审会每末尾对照 |
| 单人执行导致排期爆炸 | Q3：按 A→C→T 序贯重排为 4–5 周，砍 T6.2 为命令行 CLI 客户端 |
| aarch64 交叉工具链/sysroot 依赖（OpenSSL/protobuf/GStreamer）配置困难 | M0 只交叉协议内核（无 GStreamer）；用容器镜像预装工具链；QEMU 跑向量；媒体依赖留 M2 目标板 |

## 11. M1 预览（M0 完成即开工）

- 产品 UI 壳（导航/连接页/控制页横屏）、前台服务（`connectedDevice`）、相机扫码、mDNS 发现。
- 手柄子系统第一批（`InputDevice` 采集 + Xbox/DualSense 默认 profile + 屏幕虚拟手柄正式版）。
- rl_sar：R0 评审通过后进入 R1（补丁接口 + 036 仿真回放，见 [13-rl-sar-bridge.md](13-rl-sar-bridge.md) §9）。
- 对抗：协议 fuzz 常驻 CI（每日 1 h 档）+ 会话状态机属性测试（[14-adversarial-verification.md](14-adversarial-verification.md) §7）。

## 12. 完成判据（DoD 汇总）

1. §9 Runbook 全绿，产出 `docs/reports/m0-report.md`（含截图/日志/统计）。
2. CI 四 job 全绿且挂在 `main`；README 徽章更新。
3. 三端（C++/Kotlin/Python）通过同一套 ≥60 例向量，含 seq 回绕、重放窗口、TTL 过期、
   未知 type、CRC 篡改、分片丢中片、HKDF/AEAD 边界。
4. `--drop 30 --delay 100` 下无崩溃、看门狗语义正确；30 min 浸泡无泄漏。
5. 遗留问题全部开 Issue 并挂到 M1；`LICENSE.tbd` 的处置（Q1）有明确结论或时间点。
6. **KMP-ready 检查通过**：`core:protocol` 无平台 API 引用，CI 的 `check_kmp_ready` 全绿；
   为 M7（iOS/桌面）与 M8（Web）迁移预留。
7. **双架构构建通过**：`agent-build` 同时产出 x86_64 与 aarch64 产物，两架构协议向量一致
   （机器人端目标为 x86_64 或 ARM64，见 07 文档 §10）。
