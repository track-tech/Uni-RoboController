# 02 传输层设计

> 目标：仅局域网、低延迟、多流复用、可插拔。v1 默认自研 UDP 传输；WebRTC 作为插件保留。
> 本文定义“传输层接口 + 线路行为”，具体报文格式见 [03-protocol.md](03-protocol.md)。

## 1. 设计取舍

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 自研 UDP | 最低开销/延迟、完全可控、深度/地图/遥测都可定制、LAN 无需 NAT | 需要自己做分片/FEC/拥塞/加密 | ✅ v1 默认 |
| WebRTC | 拥塞控制成熟、加密内建、公网/ICE 现成、生态好 | 依赖重、深度/地图需塞 DataChannel、改动媒体管线受限 | 插件（v1.1+） |
| TCP/HTTP 长连接 | 简单、可靠 | 队头阻塞，不适合实时控制/视频 | 仅管理/文件 |
| ROS 2 DDS | 与机器人栈天然集成 | 依赖 ROS、跨平台客户端重、QoS 复杂 | 仅 Agent 内部/可选桥接 |

## 2. 端口与通道

| 用途 | 端口 | 协议 | 说明 |
|---|---|---|---|
| 发现 | 47810 | UDP 广播/组播 + mDNS 5353 | 不加密；只暴露身份，不含秘密 |
| 控制 + 遥测 + 反馈 | 47800 | UDP | 小包、高频、加密 |
| 视频 | 47801 | UDP | 分片 + FEC，加密可选 |
| 深度 | 47802 | UDP | 分片，加密可选 |
| 地图 | 47803 | UDP | 请求/响应 + 分块，加密 |
| 管理/文件/日志 | 47880 | TCP HTTP | Token 认证，独立于实时路径 |

> 端口均可配置；Agent 与 App 在握手中交换实际端口。所有 UDP 载荷 ≤ 1200 B（留出 MTU 余量）。

## 3. 传输抽象

```
interface ITransport {
  connect(endpoint) / close()
  send(streamId, bytes, flags)        // 非阻塞，返回是否入队
  onDatagram(callback)                // 解析后的消息或原始分片
  onFeedback(callback)                // 接收统计/拥塞信号
  stats() -> {rtt, loss, jitter, bitrate, queue}
}
```

- **后端实现**：`UdpTransport`（默认）、`WebRtcTransport`（插件）、`LoopbackTransport`（测试/录放）。
- **流（stream）**：`ctrl`、`telemetry`、`feedback`、`video`、`depth`、`map`、`config`、`log`。
  每条流有独立的可靠性语义、优先级与缓冲策略；传输层按 `stream_id` 路由。
- **上层不直接碰 socket**：媒体/地图/控制模块只与 `ITransport`/消息回调交互，便于替换为 WebRTC 或注入故障。

## 4. 发现与配对

### 4.1 发现（三选一，可叠加）

1. **mDNS**：服务 `_urc._udp.local`，TXT 字段：
   `id`、`name`、`form`、`proto`、`web_port`、`caps_hash`、`pair_state`（paired/unpaired）。
   使用 Android `NsdManager`；需要 `CHANGE_WIFI_MULTICAST_STATE` + MulticastLock。
2. **UDP 广播**：App 向 `47810` 发 `DISCOVER`（带协议版本、app 随机数），机器人单播 `ANNOUNCE`。
   适用于 mDNS 被屏蔽的 AP/路由器。
3. **二维码/手动**：机器人界面/日志/说明书生成 QR：
   `{"v":1,"ip":"192.168.1.20","ctrl":47800,"web":47880,"sid":"...","secret":"base64(32B)"}`。
   适合无发现、多网段、机器人 AP 直连。

发现响应**不含密钥**；未配对设备连接后在 AUTH 阶段被拒绝。

### 4.2 配对

- **QR 一次性/可见秘密**：机器人生成 32 B 随机秘密，二维码展示；App 扫码后保存为客户端凭据。
  机器人存储秘密的 **SHA-256 哈希**；可随时“撤销全部配对”轮换。
- **PIN 兜底**：机器人屏/日志显示 6 位 PIN（有效期 60 s，最多 5 次尝试，失败锁定 30 s）。
  App 用 PIN + 双方随机数派生出与 QR 等价的秘密（PBKDF2-HMAC-SHA256，≥100k 迭代）。
- 配对成功后，握手使用 HMAC 证明身份；会话密钥由 HKDF-SHA256 派生，不直接使用秘密。
- 安全边界：局域网被旁路时依赖加密与认证；**禁止把端口暴露到公网**。

### 4.3 会话

- 单控制者：`CONTROL` 角色唯一；第二个控制请求被拒绝，可加入 `VIEWER`（只读）。
- 会话超时：控制 5 s 无有效帧 → 会话失效；重连窗口 10 s（可恢复会话，密钥不重协商）。
- IP 变化不自动迁移（v1）；AP 切换/重连走全新握手。
- 会话 ID 在握手时生成（u32），后续所有包携带；防止跨会话重放。

## 5. 加密与完整性

| 项 | 设计 |
|---|---|
| 算法 | AES-256-GCM（AEAD，12 B nonce + 16 B tag） |
| 主密钥 PRK | `HKDF-Extract(SHA-256, salt=app_nonce(16B)\|\|robot_nonce(16B), ikm=secret(32B))` |
| 方向子密钥 | `HKDF-Expand(PRK, info="urc/session/v1/app2robot", L=32)` 与 `HKDF-Expand(PRK, info="urc/session/v1/robot2app", L=32)`；双方各持两把，方向不同即密钥不同，天然规避 nonce 冲突 |
| Nonce（12 B） | `dir(1B：0x01=App→Agent，0x02=Agent→App) \|\| 保留(3B=0) \|\| seq(u64 小端)`；同一方向内 seq 单调不重复即 nonce 不重复 |
| AAD | 线上 32 B 帧头**原样**（crc 字段取实际传输值）；任何头部比特被改都会导致 GCM 认证失败 |
| 重放 | 每流滑动窗口 2048，旧包丢弃；窗口外触发计数告警 |
| 密钥轮换 | 长会话（>4 h）或显式请求时重协商 |
| 媒体加密 | 默认开启；弱 CPU 可配置关闭（仅局域网、明确提示风险） |
| 管理 HTTP | Bearer Token（配对时下发，可轮换）+ TLS 可选（自签证书指纹固定） |
| 失败处理 | 认证/解密失败不降级、不重试明文；连续失败锁定来源 |

渗透要点：不记录密钥/秘密到日志；QR 秘密只显示一次；撤销配对立即失效；App 侧使用 Android Keystore 保存密钥。

## 6. 可靠性与流语义

| 流 | 可靠性 | 冗余 | 统计 |
|---|---|---|---|
| control | 不可靠 + 每帧重复 2 次（间隔 2 ms） | 可选 1:8 FEC | 发送间隔、丢帧、迟到 |
| telemetry | 不可靠（周期快照，允许丢） | 带关键字段重复 | 到达率、延迟 |
| feedback | 不可靠（周期报告，丢了下周期再报） | — | 丢包/RTT/解码 FPS |
| video | 不可靠 + 帧内 FEC + 关键帧请求 | XOR 1:8..1:4 | 帧完整率、卡顿 |
| depth | 不可靠 + 分片重组 | 可选 FEC | 帧完整率 |
| map | 请求/响应可靠（块级 ACK + 重传） | 按需 | 请求命中、重传 |
| config/log | 可靠（带 ACK，重传有限次） | — | 成功率 |

原则：**不为实时流做重传排队**；实时流过期即丢，保证“最新态优先”。可靠流（地图/配置）单独窗口，不阻塞实时流。

## 7. 分片与重组

- 每个大消息切成 ≤ 1200 B 的片；片头携带 `msg_type, msg_id, pkt_idx, pkt_cnt, flags(last)`。
- 重组缓冲以 `msg_id` 为键，容量与超时受控（如 64 个未完成消息、200 ms 超时），防内存放大。
- 视频帧：一个帧的所有片共享 `frame_id`；帧超时（>150 ms 或已渲染更新帧）立即丢弃，不等待补齐。
- 深度帧同理；地图块允许更长时间（秒级）与重传。

## 8. 拥塞控制与自适应

接收端每 50 ms 发送 `Feedback`：
`帧完整率/丢包、到达抖动、接收码率、解码 FPS、RTT 估计、目标码率建议、关键帧请求`。

发送端策略：

```
目标码率 = clamp(上一码率 × (1 + α·(1 - 2·loss) - β·jitter_penalty), 下限, 上限)
```

- 视频码率主调节，分辨率/帧率作为二级降级（需管线重启，频率受控）。
- 分优先级：控制 > 视频 > 深度 > 地图；带宽不足时先降地图/深度，再降视频，控制不降频。
- 发送 pacing：按 1 ms 粒度分散发送，避免突发填满 Wi-Fi 队列（bufferbloat）。
- 快速恢复：关键帧请求 + 参考帧失效（如支持），不允许长时间花屏。

参考预算（详见 [04-video.md](04-video.md)）：720p60 6–12 Mbps、1080p30 8–16 Mbps、1080p60 15–25 Mbps；
深度 2–8 Mbps；地图几十 KB/s；控制/遥测 < 200 kbps。

## 9. WebRTC 插件（预留）

- 技术前提：**GStreamer 1.16+ 的 `webrtcbin` 支持 DataChannel**（基于 `sctp`/usrsctp 插件）；
  Android 可使用维护中的 `io.github.webrtc-sdk:android`（libwebrtc 的 BSD-3 构建）。
- 同样的逻辑流映射为：
  - 视频轨：RGB（H.264）；深度伪彩可作为第二视频轨（可选）；
  - DataChannel：control（unreliable/unordered）、telemetry、feedback、map（reliable）、config；
  - 原始深度/地图走 DataChannel 分块。
- 信令：复用 HTTP 管理口（POST /webrtc/offer），SDP/ICE；局域网关闭 STUN/TURN。
- 优点：NAT/公网扩展、加密内建、拥塞控制成熟；代价：深度/地图通道需分块与限速，Android libwebrtc 体积增加。
- 与 UDP 后端共享同一套 `IProtocolCodec`，仅替换传输实现，降低双栈成本。

## 10. 网络部署建议（验收前提）

- 机器人/操作端使用 **5 GHz 或 6 GHz**；关闭 AP 省电/节能模式；固定信道；避免 2.4 GHz 蓝牙/USB3 干扰。
- 机器人与操作端尽量同一 AP；有条件用有线回程。
- 局域网内禁用客户端隔离；如 AP 支持，给控制流量 DSCP EF 标记（可选）。
- App 端 `SO_RCVBUF` 建议 ≥ 2 MB；Agent 端 ≥ 4 MB。
- 目标：Wi-Fi 空口延迟抖动 P99 < 20 ms；若实测抖动大，按 [14-adversarial-verification.md](14-adversarial-verification.md) 跑网络损伤矩阵。

## 11. 统计与故障处理

- 统一 `LinkStats`：`rtt_ms, loss_pct, jitter_ms, recv_kbps, send_kbps, frames_ok, frames_lost, reconnects`。
- 告警阈值：丢包 > 5%、RTT > 50 ms、控制帧间隔 > 2×周期、视频卡顿 > 500 ms。
- 断线重连：指数退避（0.5/1/2/4 s，上限 5 s），期间机器人侧看门狗独立生效。
- 记录每次会话的统计快照，进入对抗验证报告。
