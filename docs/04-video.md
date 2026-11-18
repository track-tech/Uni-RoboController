# 04 视频链路设计

> 目标：局域网、低延迟、可控可替换。视频是“看得见”的主链路，但**绝不能影响控制**。
> 线路格式见 [03-protocol.md](03-protocol.md) §7.2；网络基础见 [02-transport.md](02-transport.md)。

## 1. 指标

| 指标 | 目标 |
|---|---|
| 端到端（采集→App 显示） | 720p60 ≤ 100 ms（目标 80）；1080p30 ≤ 120 ms |
| 帧率 | 30/60（可选 120） |
| 码率 | 720p60 6–12 Mbps；1080p30 8–16 Mbps；1080p60 15–25 Mbps（可配） |
| 抗丢包 | 3% 丢包可恢复，关键帧 ≤ 2 s 内恢复 |
| CPU | 1080p30 硬编时机器人侧 ≤ 25%（4 核 ARM，不含其他负载） |
| 恢复 | 解码错误后 ≤ 1 s 自动恢复（请求关键帧/重启解码器） |

## 2. 机器人侧管线

```
相机源（V4L2 / RealSense / ROS 2 Image）
  → 格式转换/缩放（NV12）
  → 硬件编码（H.264 默认，HEVC 可选）
  → 分片（≤ MTU 1200）+ FEC + pacing
  → UDP 47801 / WebRTC 视频轨
```

### 2.1 编码器选择（按平台）

| 平台 | GStreamer 元素 | 说明 |
|---|---|---|
| x86 + Intel/AMD | `vah264enc` / `vah265enc` | VAAPI；低码率质量较好，功耗低 |
| x86 + NVIDIA | `nvh264enc` / `nvh265enc` | NVENC；延迟最低，推荐优先 |
| RK3588 / RK3576 | `mpph264enc` / `mpph265enc` | Rockchip MPP；**硬件编码不支持 B 帧**（每帧仅 1 个参考帧，仅 I/P），同画质需更高码率（+20–40%）；低延迟用 `rc-mode=cbr gop=<帧数> max-reenc=0 zero-copy-pkt=true header-mode=...`（插件未暴露 MPP 的 `low_delay` 键，以板端 `gst-inspect-1.0` 实测为准） |
| RK3566 | `mpph264enc` | 仅 1080p60 单路；CPU 需留余量 |
| Jetson（JetPack） | `nvv4l2h264enc` / `nvv4l2h265enc` | Jetson Multimedia API；需按 JetPack 版本验证 |
| Raspberry Pi 4 | `v4l2h264enc` | V4L2 M2M；1080p30 可用；Pi 5 无 H.264 硬编 |
| 无硬编 | `x264enc tune=zerolatency` | 仅 720p30 兜底；CPU 占用高，必须告警 |

### 2.2 编码参数（默认）

| 参数 | 值 | 说明 |
|---|---|---|
| 码率控制 | CBR | 局域网实时性优先 |
| 关键帧间隔 | 1–2 s（60–120 帧） | 兼顾恢复与带宽 |
| B 帧 | 0 | 降低延迟 |
| 前瞻/多遍 | 关闭 | 延迟 |
| SPS/PPS | 每个 IDR 重复（`config-interval=-1`） | 支持中途加入/恢复 |
| 参考帧失效 | 支持时开启（如 NVENC/VAAPI LTR） | 加速丢包恢复 |
| 色彩 | NV12 / BT.709 | 与手机解码链一致 |
| 旋转 | 在采集侧转正（不依赖客户端） | 避免手机端额外变换 |

示例（x86 NVIDIA）：

```bash
gst-launch-1.0 -v v4l2src device=/dev/video0 io-mode=dmabuf \
  ! video/x-raw,format=NV12,width=1280,height=720,framerate=60/1 \
  ! nvh264enc preset=low-latency-hq rc-mode=cbr bitrate=10000 gop-size=120 zerolatency=true \
  ! h264parse config-interval=-1 \
  ! video/x-h264,stream-format=byte-stream \
  ! urcpay mtu=1200 fec=8 \
  ! udpsink host=<app-ip> port=47801 sync=false
```

（`urcpay` 为本项目自研 GStreamer 元素：分片 + FEC + 协议头 + pacing。）

### 2.3 源与多相机

- v1 支持：一路 RGB + 一路深度；多相机作为 `streams[]` 扩展（v1.1）。
- ROS 2 源：`image_transport` 订阅 → `appsrc`（零拷贝优先 `shm`）；注意 ROS 2 QoS 设为 best effort/小队列。
- RealSense：直接 `v4l2src` 或 `realsense2` 插件；USB3 必须，USB2 会降帧率（D400 在 USB2 下大量模式不可用）。
- 分辨率/帧率切换：走“重启媒体管线”流程，避免编码器动态重配的不确定性；客户端显示降级提示。

## 3. 分片、FEC 与 pacing

- 分片 1200 B；每帧独立 `frame_id`；末尾片置 `END`。
- FEC：默认 XOR 1:8（每 8 数据片 1 校验）；可配 1:4–1:16；高丢包时由 Agent 自动提高。
- 关键帧请求：接收端丢帧/解码错误 → `FEEDBACK.flags.keyframe_req` → Agent 尽快产生 IDR。
- pacing：按 1 ms 粒度分散发包，目标峰值不超过链路预算的 70%；避免 Wi-Fi 队列突发。
- 不做视频重传（过期即弃）；只重传关键帧请求本身。

## 4. 自适应码率

接收端 50 Hz 反馈：帧完整率、丢包、抖动、RTT、解码 FPS、目标码率建议。

发送端控制律（简化）：

```
if loss > 5% or jitter > 30ms:  bitrate *= 0.85
elif loss < 1% and jitter < 10ms: bitrate *= 1.05   (上限附近减速)
bitrate = clamp(bitrate, 1.5Mbps, 25Mbps)
```

降级顺序：码率 → 帧率（60→30）→ 分辨率（1080→720）；每次降级需冷却 2 s，避免抖动。
升级顺序相反，且需持续 3 s 好状态才升。

## 5. 延迟预算（局域网，参考值）

| 环节 | 估算 |
|---|---|
| 相机曝光 + ISP | 15–33 ms（30 fps 一帧周期） |
| 采集/转换 | 2–5 ms |
| 编码 | 3–10 ms（硬编） |
| 网络 | 2–10 ms（好 Wi-Fi）/ 20–100 ms（差信道） |
| App 解码 | 5–15 ms（硬解；实测 ~10 ms） |
| 渲染/合成 | 16–33 ms（60 Hz 排队） |
| **合计** | **40–100 ms（好链路）** |

注意：相机曝光/帧周期已决定下限；不要用“降低编码延迟”掩盖采集侧延迟。

## 6. App 解码与渲染

- `MediaCodec` 异步模式 + `SurfaceView`（`Surface` 直接输出，零拷贝到合成器；不要用 TextureView，多一次拷贝）。
- 低延迟配置：API 30+ 可用 `KEY_LOW_LATENCY=1`；设置 `KEY_PRIORITY=0`（实时）；限制输入缓冲队列。
- 抖动缓冲：目标 0–2 帧自适应；帧龄 > 150 ms 丢弃；只解最新帧（drop-stale）。
- 解码错误/尺寸变化：`release` + 重建解码器；请求关键帧；重试指数退避。
- 渲染线程独立；Surface 丢失（切后台/旋转/分屏）后可恢复；EGL/MediaCodec 资源全量重建。
- 统计：解码 FPS、帧龄、丢帧数、码率、RTT；显示在 HUD（可开关）。

## 7. 故障与恢复

| 故障 | 行为 |
|---|---|
| 视频迟到/丢帧 | 丢弃过期帧，继续；不影响控制 |
| 解码器错误 | 释放重建，请求 IDR；≤1 s 恢复 |
| 编码器挂死 | Agent 重启媒体管线；控制独立；上报 EVENT |
| 带宽骤降 | 自适应降码率/帧率；必要时关闭深度/地图 |
| 手机热降频 | 降帧率/分辨率（App 请求）；提示用户 |
| 分辨率变更 | 重启管线 + 客户端重建解码器；期间黑屏 ≤ 500 ms |

## 8. 验收

- 720p60 / 1080p30 在目标局域网测得端到端 P50/P95 延迟与丢包恢复数据；
- 3% 丢包 + 50 ms 抖动下画面可恢复且控制不受影响；
- 30 min 连续运行无泄漏、无过热降频导致的中断（或明确降级策略生效）；
- 编码器 CPU 占用、手机解码功耗/温度记录。
