# ADR-0008 Apache-2.0 + GPL 隔离

- 状态：Accepted
- 日期：2026-11-18

## 背景

项目开源，希望商业与社区共用；依赖中包含 LGPL（GStreamer）、GPL（Sunshine/Moonlight、
FAST-LIO2）、MPL（Foxglove）等不同许可证。

## 决定

- 项目采用 Apache-2.0；贡献用 DCO。
- GPL 代码不进入发布物：Sunshine/Moonlight 不链接、不复制；FAST-LIO2 仅可作为独立外部进程
  （可选），或用 BSD 许可替代；octovis（GPL-2.0）不链接。
- LGPL（GStreamer/gst-rkmpp）动态链接；不分发修改版。
- 发布生成 SBOM，CI 做许可证允许列表扫描，例外需 ADR 记录。

## 理由

- Apache-2.0 与机器人/Android 主流依赖兼容，含专利授权。
- GPL 隔离保护项目的许可证一致性与商业采用可能性。

## 后果

- 不能直接复用 Moonlight/Sunshine 代码（参考思路可以）。
- 编解码专利仍需使用者自行评估（软件许可证不覆盖专利）。

## 备选

- GPL-3.0（与部分依赖兼容，但限制商业采用）。
- MIT（缺少专利条款）。
