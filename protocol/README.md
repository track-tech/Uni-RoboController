# 协议定义与示例

本目录存放线上协议的机器可读定义、示例与测试向量。协议规范见
[../docs/03-protocol.md](../docs/03-protocol.md)；能力描述见
[../docs/08-robot-abstraction.md](../docs/08-robot-abstraction.md)。

## 目录规划

```
protocol/
├── README.md
├── proto/                  # Protobuf：telemetry.proto、config.proto（实现阶段加入）
├── examples/
│   ├── capability.l4w4.json   # rl_sar 036 能力描述示例
│   └── capability.mock.json   # mock 机器人示例（实现阶段加入）
├── test-vectors/           # 帧编解码/加密/分片的固定测试向量（实现阶段加入）
└── compat/                 # 协议兼容性冒烟脚本（实现阶段加入）
```

## 规则

- 协议版本 `major.minor`；major 变更必须同步更新 [../docs/03-protocol.md](../docs/03-protocol.md)
  与 [../docs/protocol-compat.md](../docs/protocol-compat.md)。
- 示例 JSON 必须与文档字段一致；CI 校验 schema。
- 测试向量用于 App/Agent 双方实现的差分测试，任何实现都必须通过。
- **跨平台**：向量是语言无关真源，C++ Agent 与各客户端（Kotlin/JVM、iOS-Native、Wasm）必须
  通过同一套向量（见 [../docs/17-cross-platform.md](../docs/17-cross-platform.md)）。
