# 03 线上协议（Uni-RoboController Protocol v1）

> 本文件是 App 与 Agent 的**接口契约**。实现与本文不一致时以本文为准；修改协议必须同步更新本文 + ADR。
> 传输/端口/加密/会话的背景见 [02-transport.md](02-transport.md)。

## 1. 分层

```
应用层：CTRL / TELEM / FEEDBACK / VIDEO / DEPTH / MAP / CONFIG / LOG / EVENT
消息层：32 字节统一帧头 + 载荷（分片时见第 6 节）
安全层：AES-256-GCM（载荷加密，帧头为 AAD）+ 重放窗口
传输层：UDP 各流独立端口（默认）；WebRTC 插件映射为 data channel/轨
发现层：UDP 47810 广播/组播 + mDNS + 二维码（独立报文格式）
```

## 2. 统一帧头（32 B，小端）

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 4 | `magic` | `0x31435255`（ASCII `URC1`，小端） |
| 4 | 1 | `version` | 协议主版本，v1 = 1 |
| 5 | 1 | `type` | 消息类型，见第 3 节 |
| 6 | 1 | `flags` | bit0 加密；bit1 关键帧/关键块；bit2 FEC 校验包；bit3 末片；bit4 需 ACK；bit5 重发；bit6-7 保留 |
| 7 | 1 | `stream` | 流 ID（视频/深度/地图多流时区分） |
| 8 | 4 | `session_id` | 会话 ID（握手分配） |
| 12 | 4 | `seq` | 每流单调递增（u32，回绕处理见 §8） |
| 16 | 8 | `ts_us` | 发送端单调时钟（µs），用于延迟/对齐 |
| 24 | 2 | `payload_len` | 载荷长度（明文长度，≤1200） |
| 26 | 2 | `reserved` | 置 0，接收方忽略 |
| 28 | 4 | `crc32c` | 覆盖帧头（crc 置 0）+ 传输载荷（含 AEAD tag） |
| 32 | N | `payload` | 明文或密文（+16 B AEAD tag） |

规则：

- 加密时 `payload_len` 指明文长度；密文 = 明文 + 16 B GCM tag。
- 未知 `type` 丢弃并计数（不崩溃）；未知 `flags` 位忽略。
- 所有多字节整数小端；浮点 IEEE-754 小端；字符串 UTF-8（长度前缀 u8/u16）。
- 单包明文载荷 ≤ 1200 B；超长消息必须分片（见 §6）。

## 3. 消息类型

| 值 | 名称 | 方向 | 流 | 可靠性 |
|---|---|---|---|---|
| 0x01 | HELLO | App→Agent | ctrl | 可靠（重发） |
| 0x02 | HELLO_ACK | Agent→App | ctrl | 可靠 |
| 0x03 | AUTH | App→Agent | ctrl | 可靠 |
| 0x04 | AUTH_OK | Agent→App | ctrl | 可靠 |
| 0x05 | CAPS | Agent→App | ctrl | 可靠（分片） |
| 0x06 | CTRL | App→Agent | ctrl | 不可靠（重复发送） |
| 0x07 | TELEM | Agent→App | telemetry | 不可靠 |
| 0x08 | FEEDBACK | App→Agent | feedback | 不可靠 |
| 0x09 | PING | 双向 | ctrl | 不可靠 |
| 0x0A | PONG | 双向 | ctrl | 不可靠 |
| 0x0B | ESTOP | App→Agent | ctrl | 可靠（重复） |
| 0x0C | CONFIG | App→Agent | config | 可靠（ACK） |
| 0x0D | CONFIG_ACK | Agent→App | config | 可靠 |
| 0x0E | EVENT | Agent→App | telemetry | 不可靠（可重发） |
| 0x0F | ERROR | 双向 | ctrl | 不可靠 |
| 0x10 | VIDEO | Agent→App | video | 不可靠 + FEC |
| 0x11 | VIDEO_FEC | Agent→App | video | 不可靠 |
| 0x12 | DEPTH | Agent→App | depth | 不可靠 |
| 0x13 | MAP_META | Agent→App | map | 可靠 |
| 0x14 | MAP_REQUEST | App→Agent | map | 可靠 |
| 0x15 | MAP_TILE | Agent→App | map | 可靠（分块+重传） |
| 0x16 | MAP_ACK | App→Agent | map | 可靠 |
| 0x17 | SESSION_CTRL | App→Agent | ctrl | 可靠 |
| 0x18 | TIME_SYNC | 双向 | ctrl | 不可靠 |
| 0x19 | MODEL_STATE | Agent→App | telemetry | 不可靠（可分片） |
| 0x20 | DISCOVER | App→广播 | 发现 | 无会话（独立格式） |
| 0x21 | ANNOUNCE | Agent→App | 发现 | 无会话（独立格式） |

## 4. 握手与能力

### 4.1 时序

```
App                                   Agent
 │── HELLO(proto, app_nonce, role) ───▶│
 │◀── HELLO_ACK(robot_nonce, session, ports, caps_hash)
 │── AUTH(HMAC(secret, nonces+session)) ▶│
 │◀── AUTH_OK(role, key_confirm)        │
 │── SESSION_CTRL(claim) ──────────────▶│
 │◀── CAPS(zstd capability JSON) ───────│
 │◀───────── TELEM 20Hz ────────────────│
 │───────── CTRL 100Hz ────────────────▶│
 │◀─────── FEEDBACK 50Hz ───────────────│   （视频/深度开始后）
```

- HELLO 前不允许发送任何控制消息；未认证的 CTRL 丢弃并计数。
- `HELLO_ACK` 中的 `ports` 允许 Agent 使用非默认端口。
- `caps_hash = SHA-256(capability_json)[0:4]`；App 收到 CAPS 后校验并缓存（按 robot_id + hash）。
- `AUTH` 失败返回 ERROR(code=0x0101)，连续 5 次失败锁定 30 s。
- 会话超时：5 s 无任何有效包 → 断开；重连窗口 10 s。

### 4.2 HELLO / HELLO_ACK 载荷

| 消息 | 字段 |
|---|---|
| HELLO | `proto_major u16, proto_minor u16, role u8, flags u16, app_id[16], app_nonce[16], app_version_len u8 + utf8` |
| HELLO_ACK | `proto_major u16, proto_minor u16, session_id u32, robot_id_len u8 + utf8, robot_name_len u8 + utf8, form_len u8 + utf8, robot_nonce[16], caps_hash u32, ctrl_port u16, video_port u16, depth_port u16, map_port u16, web_port u16, auth_required u8` |

### 4.3 AUTH / AUTH_OK

- `proof = HMAC-SHA256(secret, "urc/auth/v1" || app_nonce || robot_nonce || session_id)`
- AUTH 载荷：`proof[32], client_id[16], client_name_len u8 + utf8`
- AUTH_OK 载荷：`role u8, key_confirm[8] = HKDF(session_key, "confirm")[0:8], server_ts_us u64`
- 会话密钥：`HKDF-SHA256(secret, salt=app_nonce||robot_nonce, info="urc/session/v1")`。

### 4.4 CAPS 载荷

- `caps_len u32, caps_crc32c u32, zstd(capability_json)`，分片传输（flags bit3 标记末片）。
- capability JSON schema 见 [08-robot-abstraction.md](08-robot-abstraction.md) 与 §5 节示例。
- capability 中 `model` 字段声明 URDF 模型包：`bundle_hash`、下载 `url`、`joint_order`、
  `joint_order_hash`、`base_link`、`root_frame`、`dof`（详见 [15-urdf-model.md](15-urdf-model.md)）。
  模型包通过 HTTP 下载，不走实时通道。
- Agent 在配置变更后发送新的 CAPS（flags bit1 标记 update），App 需重新拉取并确认。

## 5. 控制帧（CTRL）

载荷（明文，按 capability 的 `control_layout` 解释）：

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 1 | `mode` | 控制模式 ID（capability.control.modes[].id） |
| 1 | 1 | `axis_count` | ≤16 |
| 2 | 1 | `button_words` | 1 或 2（u32 字数） |
| 3 | 1 | `flags` | bit0 死手；bit1 急停；bit2 模式切换；bit3 保留 |
| 4 | 2×N | `axes[i16]` | 按 capability 的 `channels[]` 顺序 |
| 4+2N | 4×W | `buttons[u32]` | 按 capability 的 `buttons[].bit` 位定义 |

- 发送频率 50–250 Hz（默认 100 Hz）；每帧重复 2 次（`flags bit5`），间隔 2 ms。
- 机器人侧对 `mode`、`axis_count`、范围做校验；越界拒绝并上报 ERROR/EVENT。
- **死手**：`flags.bit0` 为 0 时所有运动通道视为 0（App 在手指离开/失焦/断连时置 0）。
- **急停**：通过独立 ESTOP 消息（不依赖 CTRL），见 §7.1。
- 轴单位：线性 m/s、角度 rad/s；整数缩放由 capability 的 `scale` 定义（如 i16 满量程 = 2.0）。

### 5.1 L4W4 的通道映射示例

| channel | 范围 | 缩放 | rl_sar 对应 |
|---|---|---|---|
| `body.linear_x` | [-1.5, 1.5] | 1.5 | `control.x = joy.ly * 1.5` |
| `body.linear_y` | [-1.5, 1.5] | 1.5 | `control.y = -joy.lx * 1.5` |
| `body.angular_z` | [-2.0, 2.0] | 2.0 | `control.yaw = -joy.rx * 2.0` |
| 按钮 bit0 | — | — | `A`（GetUp） |
| 按钮 bit1 | — | — | `B`（GetDown） |
| 按钮 bit2 | — | — | `LB_X`（Passive） |
| 按钮 bit3 | — | — | `RB_DPadUp`（RLLocomotion） |
| 按钮 bit4 | — | — | `PATCH_ESTOP`（补丁实现；未打补丁时映射到 Passive） |

## 6. 分片与重组

- 需要分片的消息（CAPS/VIDEO/DEPTH/MAP_TILE/CONFIG）：分片头在载荷前附加
  `msg_id u32, pkt_idx u16, pkt_cnt u16, payload_bytes u16`（8 B），余下为有效负载。
- 视频/深度使用专用帧头（见 §7.2/§7.3），不复用通用分片头。
- 重组器上限：64 个并发消息、单消息 ≤ 8 MB（CAPS/CONFIG ≤ 256 KB）、超时 200 ms（视频/深度）
  或 5 s（地图块/CAPS）。
- 重叠/乱序分片按 `pkt_idx` 放入数组；重复分片丢弃；末片到达且全齐才交付。

## 7. 媒体与控制细节

### 7.1 ESTOP（急停）

- 载荷：`reason u8, ts_us u64`；flags bit4（需 ACK），重复发送 3 次、间隔 20 ms。
- Agent 收到后：立刻锁存急停、置零控制、调用适配器 `safe_stop()`；回发 EVENT(estop_acked)。
- 急停期间允许的唯一控制消息是 `ESTOP(reason=0)` + `SESSION_CTRL(release_estop)` 的显式复位流程
  （App 需二次确认）；复位前 CTRL 一律忽略。
- 视频/App 存活不影响急停：Agent 本地看门狗独立于网络。

### 7.2 视频（VIDEO）

载荷 = 视频分片头（23 B）+ H.264/HEVC 字节：

| 偏移 | 长度 | 字段 |
|---|---|---|
| 0 | 4 | `frame_id` u32（回绕处理） |
| 4 | 8 | `frame_ts_us` u64（采集时间，Agent 单调时钟） |
| 12 | 4 | `frame_bytes` u32（整帧字节数） |
| 16 | 2 | `pkt_idx` u16 |
| 18 | 2 | `pkt_cnt` u16 |
| 20 | 2 | `group_id` u16（FEC 组） |
| 22 | 1 | `media_flags` bit0 IDR、bit1 SPS/PPS、bit2 帧结束、bit3 关键帧请求响应 |

- 同一帧的所有分片共享 `frame_id/group_id`；`media_flags.bit2` 在最后一片置位。
- `VIDEO_FEC` 载荷：`group_id u16, group_size u16, parity_idx u8, parity_len u16, data`，
  为组内数据片的 XOR 校验（等长填充）；默认每 8 片 1 片校验（可配 1:4–1:16）。
- 关键帧：收到 `FEEDBACK(flags.keyframe_req)` 后尽快产生 IDR；SPS/PPS 随 IDR 重复发送。
- 解码端在帧超时/不完整时丢弃并请求关键帧；不等待缺失分片。

### 7.3 深度（DEPTH）

载荷 = 深度帧头（48 B）+ 数据：

| 偏移 | 长度 | 字段 |
|---|---|---|
| 0 | 4 | `frame_id` u32 |
| 4 | 8 | `frame_ts_us` u64 |
| 12 | 2 | `width` u16 |
| 14 | 2 | `height` u16 |
| 16 | 1 | `format`（0=Z16，1=RGB8 伪彩，2=Z16 降采样） |
| 17 | 1 | `encoding`（0=raw，1=zstd，2=rle） |
| 18 | 4 | `depth_scale` f32（米/单位） |
| 22 | 16 | `fx, fy, cx, cy` f32 |
| 38 | 2 | `chunk_idx` u16 |
| 40 | 2 | `chunk_cnt` u16 |
| 42 | 1 | `flags`（bit0 末片） |
| 43 | 5 | 保留（置 0） |

- 建议默认 320×240@10 Hz + zstd；原始 640×480@10–15 Hz 作为可选高码率配置。
- 坐标约定：Z16 单位 mm → `depth_scale=0.001`；App 反投影使用 `x=(u-cx)*d/fx` 等。
- 深度帧不重传；缺失时 App 显示上一帧并标记延迟（UI 明确）。

### 7.4 地图

| 消息 | 载荷 |
|---|---|
| MAP_META | `map_id u32, revision u32, tile_size f32, voxel_size f32, origin[3]f32, bounds[6]f32, tile_count u32, frame_id_len u8 + 字符串（如 "map"）` |
| MAP_REQUEST | `req_seq u32, count u8(≤64), tile_id u32[count]` |
| MAP_TILE | `req_seq u32, tile_id u32, revision u32, origin[3]f32, voxel_size f32, point_count u32, encoding u8(0=量化+zstd), chunk_idx u16, chunk_cnt u16, uncompressed_len u32, payload` |
| MAP_ACK | `req_seq u32, tile_id u32, status u8(0=ok,1=retry,2=reject)` |

- 瓦片实体编码见 [05-depth-pointcloud.md](05-depth-pointcloud.md) §5。
- App 根据视锥/距离请求瓦片；Agent 限流（默认 ≤ 8 个在途请求、≤ 200 KB/s）。
- 重传：块级 ACK + 超时 300 ms，最多 3 次；失败标记为“不可用”并允许后续重试。
- 地图 revision 变化时 App 清空对应瓦片缓存；`map_id` 变化表示新地图（需确认）。

### 7.5 遥测（TELEM）

使用 protobuf-lite（`telemetry.proto`），关键字段：

```proto
message Telemetry {
  uint32 seq = 1;
  uint64 ts_us = 2;
  uint32 fsm_state = 3;          // 与 capability.actions/状态表对应
  uint32 fault_flags = 4;
  uint8  battery_pct = 5;
  float  x = 6; float y = 7; float yaw = 8;  // 机器人位姿（map 系）或命令回显
  repeated float joint_q = 9;
  repeated float joint_dq = 10;
  repeated float joint_tau = 11;
  float  imu_quat[4] = 12; float imu_gyro[3] = 13;
  string policy_name = 14;
  uint32 inference_us = 15;
  uint32 episode_len = 16;
  uint32 queue_depth = 17;
  uint32 link_rtt_us = 18;
  uint32 link_loss_pct = 19;
  uint32 remote_age_ms = 20;
  uint32 map_revision = 21;
}
```

- 频率默认 20 Hz（可配 10–50 Hz）；单包 ≤ 1200 B，超长则分片。
- App 用 `ts_us` 做延迟估计；跨设备绝对时间不做强保证。

### 7.6 反馈（FEEDBACK）

| 字段 | 说明 |
|---|---|
| `video_ok, video_lost` | 最近窗口帧完整/丢失数 |
| `packets_lost, recv_kbps` | 视频流统计 |
| `decode_fps, decode_ms` | App 解码性能 |
| `rtt_us, jitter_us` | 由 PING/PONG 或时间戳估计 |
| `target_kbps` | App 建议码率（0 表示不调整） |
| `flags` | bit0 请求关键帧；bit1 拥塞；bit2 深度请求降级 |

频率 50 Hz，丢了下发周期再报，不重传。

### 7.7 配置（CONFIG）与管理 HTTP

- CONFIG 载荷：`request_id u32 + protobuf ConfigPatch`（视频码率/帧率、深度开关、地图限流、日志级别等）；
  Agent 校验范围后 CONFIG_ACK（含 request_id 与 status）。
- HTTP（47880）：
  - `GET /api/v1/info`、`/capabilities`、`/config`、`/logs`、`/files`、`/health`
  - `GET /api/v1/model/<hash>.zip`（下载 URDF 模型包）
  - `POST /api/v1/model`（管理员上传模型包，校验哈希/格式/大小）
  - `PUT /api/v1/config`（JSON Patch 子集）
  - `POST /api/v1/record/start|stop`、`/api/v1/map/save|load`、`/api/v1/reboot`
  - `Authorization: Bearer <token>`（配对时下发；可轮换）；默认只绑定局域网地址。

### 7.8 模型状态（MODEL_STATE）

用于驱动 URDF 模型，20–50 Hz，不可靠；超过 1200 B 时按通用分片规则拆分。

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 4 | `seq` u32 | 采样序号 |
| 4 | 8 | `ts_us` u64 | 机器人采样时间（单调时钟） |
| 12 | 4 | `joint_order_hash` u32 | CRC32(capability.model.joint_order) |
| 16 | 2 | `joint_count` u16 | = len(joint_order) |
| 18 | 1 | `flags` u8 | bit0 含速度、bit1 含力矩、bit2 根位姿有效 |
| 19 | 1 | `frame_id` u8 | 0=odom，1=map，2=base |
| 20 | 4×3 | `root_pos` f32[3] | 根位置（m） |
| 32 | 4×4 | `root_quat` f32[4] | 四元数 `(w,x,y,z)` |
| 48 | 4×N | `joint_pos` f32[N] | 关节位置（rad/m） |
| 48+4N | 4×N | `joint_vel` f32[N] | 可选（flags.bit0） |
| 48+8N | 4×N | `joint_eff` f32[N] | 可选（flags.bit1） |

- `joint_order` 必须与 capability 一致；不匹配时 App 不渲染运动并提示（安全相关）。
- 50 关节时约 670 B（含位置/速度），人形 50+ 关节需分片；带宽 10 KB/s 级。
- 状态过期（>500 ms）→ App 置灰模型；Agent 侧状态新鲜度看门狗另见 09 文档。

## 8. 序号、时间与回绕

- `seq` 每流独立，u32 回绕：接收端用“回绕窗口”比较（例如 RFC 1982 序列号比较）。
- 控制帧过期判定：`now - ts_us > 200 ms` 丢弃（不执行迟到命令）。
- 视频帧过期：`now - frame_ts_us > 150 ms` 丢弃（渲染最新帧）。
- 录制/回放：保留原始 `ts_us` 与到达时间 `recv_ts_us`，便于离线对齐。

## 9. 错误码

| 码 | 含义 | 处置 |
|---|---|---|
| 0x0101 | 认证失败 | 拒绝并限速 |
| 0x0102 | 会话不存在/过期 | 断开重连 |
| 0x0103 | 角色冲突（已有控制者） | 降级只读或拒绝 |
| 0x0201 | 协议版本不兼容 | 提示升级 |
| 0x0202 | 能力哈希不匹配 | 重新拉取 CAPS |
| 0x0301 | 控制越界/非法模式 | 拒绝并计数 |
| 0x0302 | 急停锁存中 | 忽略控制，提示复位 |
| 0x0401 | 媒体配置不支持 | 回退默认配置 |
| 0x0501 | 地图请求限流 | 稍后重试 |
| 0x0601 | 内部错误 | 记录日志，允许重试 |
| 0x0602 | 认证锁定 | 等待锁定结束 |

## 10. 版本化

- 协议版本 `major.minor`：major 不兼容；minor 向后兼容（新增可选字段/消息）。
- 能力 schema 独立版本（`urc-capability/v1`）；不兼容变更升 v2。
- Agent 与 App 的兼容矩阵写入 `docs/protocol-compat.md` 并在 CI 校验。
- 老版本 App 连接新 Agent：Agent 按 minor 降级发送；不支持的必需特性则返回 ERROR 0x0201。
