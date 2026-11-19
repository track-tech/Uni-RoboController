# 06 客户端设计（Android 首发，跨平台演进）

> **范围说明（B 方案 / ADR-0014）**：v1 只做 Android **基础档**（发现/配对/控制/遥测/视频/URDF 状态/手柄/安全交互）；
> 深度/点云/地图/关节命令属于 v1.1 增强档，UI 与服务端按能力协商。
> 跨平台（iOS/桌面/Web）后置，见 [17-cross-platform.md](17-cross-platform.md)。
>
> 本文件同时定义平台适配层的接口边界：媒体解码、3D 渲染、手柄、传输、发现均为平台实现，
> 协议/会话/能力/命令映射/模型状态等共享逻辑不依赖 Android API（KMP-ready）。
>
> 技术基线：Kotlin + Jetpack Compose；原生 MediaCodec/Filament 保证低延迟；手柄与深度/点云渲染是核心差异点。

## 1. 平台与依赖

| 项 | 选择 |
|---|---|
| 语言/UI | Kotlin 2.x + Jetpack Compose（Material 3），Navigation Compose |
| minSdk / targetSdk | 26 / 36（跟随最新稳定） |
| 架构 | 单 Activity + 前台服务 + 模块化；ViewModel + StateFlow；Hilt；Coroutines/Flow |
| 视频解码 | `MediaCodec`（异步）+ `SurfaceView`；API 30+ 使用 `KEY_LOW_LATENCY`（需 `FEATURE_LowLatency`，否则回退） |
| 3D 渲染 | **Filament（主）**：URDF 模型（glTF）+ 点云（POINTS）+ 栅格同场景；GLES 自定义渲染器作为性能兜底（ADR-0011） |
| 协议/压缩 | 自研二进制（`core-protocol`）；zstd（`zstd-jni`，支持 Android AAR）；Protobuf-lite 用于遥测/配置 |
| 3D | Filament（`filament-android` + `gltfio-android`，Apache-2.0）；GLES 兜底 |
| 存储 | DataStore（设置）、Room（机器人与历史）、文件（地图瓦片缓存/日志导出） |
| 二维码 | ZXing（Android Embedded，Apache-2.0） |
| 发现 | `NsdManager`（mDNS）+ 广播 + 手动；`CHANGE_WIFI_MULTICAST_STATE` + MulticastLock |

## 2. 模块划分

```
:app                 入口 Activity、导航、权限、依赖注入
:core:protocol       帧编解码、消息模型、版本协商、会话状态机（纯 Kotlin/JVM，可单测）
:core:transport      UDP/WebRTC 后端、发现、配对、重连、统计
:core:media          视频/深度接收、抖动缓冲、MediaCodec 解码、Surface 管理
:core:render         Filament/GLES 渲染：URDF 模型、点云、栅格、深度；瓦片缓存、LOD/裁剪
:core:model          URDF 模型包下载/缓存/解析、关节树、状态插值、模型管理
:core:gamepad        InputDevice 采集、槽位、映射引擎、震动、虚拟手柄
:core:robot          能力模型、命令构建、遥测状态、安全状态镜像
:feature:connect     发现列表、扫码、手动连接、配对
:feature:control     全屏视频、摇杆/按钮、HUD、急停
:feature:map         点云/栅格/深度面板、测量、图层、保存
:feature:settings    视频/深度/地图/手柄/网络/日志
:feature:diagnostics 统计图表、日志导出、录屏/抓包
```

边界规则：`core:*` 不依赖 UI；`feature:*` 不直接操作 socket；媒体/渲染线程不阻塞 UI。

### 2.1 跨平台边界（KMP-ready）

- `core:protocol` 为纯 Kotlin/JVM：不引用 `android.*`、`androidx.*`，可在 JVM 单测与未来 KMP 目标编译。
- `core:transport`、`core:media`、`core:render`、`core:gamepad` 中的**平台实现**通过接口暴露：
  `ITransport`、`VideoDecoder`、`IRenderer`、`GamepadSource`、`CryptoProvider`、`Discovery`；
  共享层只依赖接口。
- 加解密：Android 用 `javax.crypto`（AES-GCM/HKDF 手写或 BouncyCastle），实现必须通过
  `protocol/vectors/crypto.json`；后续 iOS/桌面/Wasm 用各自系统库实现同一接口。
- 未来迁移路径：`core:protocol` → `shared/core-protocol`（KMP）→ Android/桌面/iOS 共用；
  详见 [17-cross-platform.md](17-cross-platform.md)。

## 3. 页面与交互

### 3.1 连接页
- 自动发现列表（名称/形态/状态/是否已配对）、二维码扫描、手动 IP:端口。
- 已配对机器人置顶；显示信号强度/最后连接时间；支持“仅查看（viewer）”。

### 3.2 控制页（横屏、沉浸式）
- 全屏视频（SurfaceView）；可切换“视频 + 地图”分屏或画中画地图。
- 左侧悬浮摇杆（线性 x/y）、右侧摇杆（yaw 或云台），可按能力切换布局；
- 动作按钮：站立/趴下/被动/运动/策略选择/模式切换（长按确认高风险动作）；
- 急停按钮常驻（红色，二次确认；显示机器人侧确认状态）；
- HUD：电量、FSM/模式、策略、链路（RTT/丢包/码率）、视频 FPS、深度/地图状态、故障；
- 手柄连接状态与槽位；录制按钮；全屏/退出；通知栏常驻（前台服务）。

### 3.3 地图页
- 3D 点云（可旋转/缩放/平移）、2D 占据栅格、机器人位姿与轨迹；
- 图层开关；点大小/密度；深度面板；测量工具；地图保存/加载；性能档位。

### 3.4 模型/状态视图
- 加载并显示 URDF 模型（机器人 3D 状态），关节随遥测实时运动；
- 叠加模式：视频画中画/分屏；可切换“视频优先/模型优先”；
- 关节面板：按 URDF 树分组（腿/臂/手/腰/头），显示角度与 URDF 限位，超限高亮；
- 模型管理：自动下载/更新（按哈希）、本地导入 URDF/zip、删除缓存、查看来源；
- 诊断：模型哈希、关节顺序、状态延迟/过期、坐标系警告；
- 详细设计见 [15-urdf-model.md](15-urdf-model.md)。

### 3.4 手柄页
- 已连接手柄列表（名称/VID/PID/槽位/电量）；槽位分配（主控/云台/机械臂）；
- 映射编辑（按键→动作、轴→通道、死区/反向/曲线/组合键）；
- 震动测试；屏幕虚拟手柄布局编辑；配置导入/导出；恢复默认。

### 3.5 设置/诊断
- 视频：分辨率/帧率/码率/编码/传输模式/FEC/加密；深度：开关/档位/编码；地图：限流/显示；
- 网络：发现方式、端口、静态 IP；日志级别；清缓存；导出诊断包（脱敏）。

## 4. 手柄子系统（多型号 + 多手柄）

### 4.1 统一模型

```kotlin
data class GamepadState(
  val seq: Long, val tsUs: Long, val slot: Int,
  val buttons: Long,          // 64 位位掩码，按能力映射
  val axes: IntArray,         // i16，按通道顺序
  val hat: Int,
  val gyro: FloatArray?, val accel: FloatArray?,  // 手柄 IMU（若可用）
  val deviceId: Int, val vendorId: Int, val productId: Int
)
```

### 4.2 采集

- `InputManager.getInputDeviceIds()` + `registerInputDeviceListener` 跟踪热插拔；
  只处理 `SOURCE_GAMEPAD`/`SOURCE_JOYSTICK` 设备。
- 按键：`Activity.dispatchKeyEvent` / `View.onKeyDown/onKeyUp`（注意焦点与返回键拦截）；
- 轴：`onGenericMotionEvent`（`AXIS_X/Y/Z/RZ`、`AXIS_LTRIGGER/RTRIGGER`、`AXIS_HAT_X/Y`、`AXIS_BRAKE/GAS`）；
- 多手柄：以 `deviceId` 区分，分配槽位；`InputDevice.getControllerNumber()`（API 33+）作为辅助；
- 手柄 IMU：Android 12+ 通过 `InputDevice.getSensorManager()` 等 API 获取（能力探测，不可用则关闭）；
- 震动：`InputDevice.getVibrator()`（API 31+）/`VibratorManager`；映射碰撞/低电/急停提示；
- 屏幕虚拟手柄：自绘双摇杆/扳机/按钮，作为默认兜底，输出同一 `GamepadState`。

### 4.3 映射引擎

- Profile = `(VID/PID 或通用) × 机器人形态`；内置默认 profile（reference 见 08 文档）；
- 规则：`axis → channel`（可反向、缩放、死区、指数曲线）、`button → action`（tap/hold/combo）、
  `combo → action`（如 LB+X）；支持“按一下自动识别”的映射向导；
- 死亡区默认 5–8%，输出做斜率限制（避免阶跃）；
- 配置 JSON 导入/导出（SAF），云端分享留 v2。

### 4.4 已知坑（必须在设计/测试中覆盖）

| 坑 | 对策 |
|---|---|
| 手柄“Android 模式 vs XInput/DInput 模式”键位完全不同 | profile 记录模式；映射向导提示切换；UI 显示原始键值 |
| 不同厂商轴编号/名称不一致 | 按 `AXIS_*` 常量 + `getMotionRange` 探测；不要硬编码 index |
| 蓝牙延迟/断连/重连 | 超时清零、重连后重新绑定槽位、提示用户 |
| 多手柄同时连接 | 槽位锁；主控唯一；切换需显式操作 |
| 返回键/通知抢焦点 | 控制页拦截必要按键；失焦时清零输入并提示 |
| 震动 API 碎片化 | 能力探测 + 失败静默降级 |

## 5. 视频/深度/地图渲染

### 5.1 视频
- `SurfaceView` + MediaCodec 异步；`releaseOutputBuffer(index, true)` 立即渲染；不攒帧。
- 低延迟：`KEY_LOW_LATENCY=1`（API 30+，先查 `FEATURE_LowLatency`）、`KEY_OPERATING_RATE=目标帧率`、
  `KEY_PRIORITY=0`（realtime）；`SurfaceHolder.setFixedSize` 固定尺寸，减少重配。
- 抖动缓冲：0–2 帧自适应；帧龄 >150 ms 丢；解码错误→重建+请求 IDR。
- Surface 生命周期（切后台/旋转/分屏）与 codec 释放/重建；避免黑屏累积。

### 5.2 深度与点云
- 深度纹理上传（Z16）+ 顶点着色器反投影（详见 05 文档）；
- `GL_POINTS` 前查询 `GL_ALIASED_POINT_SIZE_RANGE`，上限不足用实例化四边形；
- 环形 VBO（3–4 个）+ orphaning，避免 `glBufferSubData` 隐式同步；
- 渲染 60 Hz、数据 10–15 Hz，只取最新快照；视锥裁剪 + 距离 LOD；
- 热降频监测（`PowerManager`/`thermal`）→ 自动降点密度/帧率并提示。

### 5.3 地图瓦片
- `MapRepository` 管理请求队列（视锥/优先级/限流）、内存 LRU、磁盘缓存；
- 解码后按块上传 GPU；revision 变化丢弃旧块；
- 3D 地图与视频分层显示（视频层在下、点云透明层在上），避免遮挡操作信息。

### 5.4 URDF 模型
- 模型包下载（HTTP）→ 哈希校验 → 解压到缓存；解析 `model.json` 建关节树；
- `MODEL_STATE` 按 `joint_order` 更新关节角/根位姿；20–50 Hz 数据、60 Hz 渲染，线性/slerp 插值；
- 状态过期（>500 ms）置灰并提示；关节顺序/数量不匹配不渲染运动；
- 关节限位高亮；模型/点云/栅格可同场景或分层显示；性能档位（减面模型、关闭阴影）。

## 6. 会话与生命周期

- `RobotControlService`（前台服务，`connectedDevice` 类型）持有连接与流；
  权限：`FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_CONNECTED_DEVICE`（Android 14+），
  并满足运行前提（如 `CHANGE_WIFI_STATE`/`CHANGE_NETWORK_STATE`/`CHANGE_WIFI_MULTICAST_STATE` 之一）。
- Activity 重建不影响服务；屏幕常亮（控制页 `FLAG_KEEP_SCREEN_ON`）；横屏锁定（控制页）；
- 进程被杀/来电/切后台：输入清零 + 提示；恢复后重新握手（或复用重连窗口）；
- 网络变化（Wi-Fi 断/切网）→ `ConnectivityManager.NetworkCallback` 触发重连；
- 电量/温度策略：低电提示、可配置降码率；高温降档。

## 7. 安全与隐私（App 侧）

- 配对秘密/会话密钥保存在 Android Keystore（不落日志、不明文导出）；
- 协议层加密由 `core-transport` 实现；App 不做“明文降级”；
- 日志脱敏（IP/密钥/机器人序列号可配置）；导出诊断包需用户确认；
- 屏幕截屏/录屏允许（操作需要），但不在后台偷偷录；权限按最小化原则；
- 依赖 SBOM 与许可证检查（见 12 文档）。

## 8. 性能目标与测试

| 指标 | 目标 |
|---|---|
| 冷启动到可连接 | ≤ 2 s |
| 视频端到端 | 720p60 ≤ 100 ms；1080p30 ≤ 120 ms（见 04） |
| 点云 | 50 万点 ≥ 30 FPS（目标 60）；100 万点需裁剪/LOD |
| 内存 | 地图缓存 + 解码 ≤ 400 MB（中端机） |
| 功耗/热 | 30 min 连续使用不因降频导致断流（可降档） |

测试：JVM 单测（协议/映射/状态机）、instrumentation（服务/解码/GL）、mock 机器人端到端、
`Macrobenchmark`（启动/帧率）、手柄矩阵（6–8 款 × 蓝牙/USB）、多设备矩阵（Android 10–16）。
