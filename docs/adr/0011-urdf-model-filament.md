# ADR-0011 URDF 模型包 + Filament 渲染

- 状态：Accepted
- 日期：2026-11-18

## 背景

目标覆盖任意四足/人形/轮足/机械臂；App 需要显示机器人 3D 状态（关节、根位姿），
且已有深度点云/栅格渲染需求。直接在 App 内解析 URDF + STL/DAE 成本高、格式支持差。

## 决定

- 离线工具 `tools/urdf_bundle` 把 URDF/xacro + 网格转换为 `model.glb` + `model.json`
  （关节树/限位/视觉/坐标约定），打包为带 SHA-256 的 zip；Agent 通过 HTTP 下发，
  App 校验哈希后缓存。
- App 主渲染器采用 **Filament + gltfio**（Apache-2.0），URDF 模型、点云（POINTS）、栅格同场景；
  关节角/根位姿由 `MODEL_STATE` 驱动并插值。
- GLES 自定义渲染器保留为性能兜底；WebView + three.js/urdf-loader 仅用于离线预览/原型。
- 模型不参与安全控制：模型/关节顺序/状态不一致时禁止运动渲染与关节命令；机器人侧限位仍是最终保护。
- Agent 不在线执行 xacro（避免任意脚本执行）；离线转换或管理员上传校验后的模型包。

## 理由

- 转换一次、渲染端简单；glTF/Filament 成熟、支持骨骼/节点层级与 PBR，移动端性能可控。
- 点云与模型同场景避免多 Surface 叠加问题；模型包可缓存、版本化、可审计。
- 保持“模型仅显示”的安全边界，避免 URDF 错误影响控制。

## 后果

- 增加转换工具与模型包管理；网格格式（DAE/STL/OBJ）需转换/减面。
- Filament 引入 APK 体积与学习成本；点云性能需实测，不达标则退回“模型 Filament + 点云 GLES”。
- 模型资产授权需逐项确认（见 12 文档）。

## 备选

- 纯 GLES 自研 URDF/网格加载（工作量大、格式支持差）。
- WebView + three.js（快，但性能/集成差，仅原型）。
- 传参数化骨架而非模型（显示效果差，难以调试）。
