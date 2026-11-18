# 第三方代码清单

> 用于许可证合规与供应链追溯。新增依赖/复制代码必须更新本表。
> 详细许可证说明见 [12-open-source.md](12-open-source.md)。

| 名称 | 版本/来源 | 许可证 | 使用方式 | 修改 | 备注 |
|---|---|---|---|---|---|
| GStreamer 核心/base/good/bad | ≥1.22 | LGPL-2.1+ | 动态链接 | 否 | webrtcbin 需 ≥1.16（data channel） |
| gst-rkmpp | 待锁定 fork | LGPL-2.1（插件） | 动态链接 | 否 | 原仓库 404，需锁定可信 fork |
| Rockchip MPP | 待锁定 | Apache-2.0 / MIT | 动态链接 | 否 | gst-rkmpp 的底层库 |
| libwebrtc / webrtc-sdk | 插件启用时 | BSD-3 | 动态/AAR | 否 | WebRTC 插件 |
| librealsense | 2.5x | Apache-2.0 | 链接/进程 | 否 | 可选深度源 |
| zstd | 1.5.x | BSD-3（或 GPL-2 双许可） | 链接 | 否 | 按 BSD 使用 |
| protobuf | 3.x/4.x | BSD-3 | 链接/生成代码 | 否 | 遥测/配置 |
| cpp-httplib / spdlog / yaml-cpp | 最新稳定 | MIT | 链接 | 否 | 管理/日志/配置 |
| ZXing（android-embedded） | 最新 | Apache-2.0 | 链接 | 否 | 扫码 |
| rl_sar 补丁 | 036_frs/上游 | Apache-2.0 | 源码补丁 | 是（补丁） | 记录补丁文件与基线 commit |
| mock 机器人/工具 | 本项目 | Apache-2.0 | 源码 | — | — |

> 禁止：Sunshine/moonlight-android（GPL-3.0）、FAST-LIO2（GPL-2.0，仅独立进程可选）、
> octovis（GPL-2.0）链接进发布物；gst-plugins-ugly 默认不打包。
