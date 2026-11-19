# 协议测试向量（规划）

本目录存放语言无关的协议测试向量，是 C++/Kotlin/Python 三端实现与 CTS 的共同真源。
规范见 [../../docs/03-protocol.md](../../docs/03-protocol.md) 与
[../../docs/18-protocol-implementation-guide.md](../../docs/18-protocol-implementation-guide.md)。

## 规划文件

| 文件 | 内容 | 目标数量 |
|---|---|---|
| `frames.json` | 帧编解码/CRC/边界/非法输入 | ≥30 |
| `crypto.json` | HKDF 方向子密钥/AES-GCM/重放窗口 | ≥15 |
| `frag.json` | 分片/重组/FEC/超时 | ≥15 |
| `session.json` | 握手/认证/锁定/急停/看门狗场景 | ≥10 |

## 格式

```json
{
  "name": "frame/ctrl/basic",
  "given": {"hex": "..."},
  "expect": {"ok": true, "type": "ctrl", "hex": "..."}
}
```

- 由 `tools/codec_ref/gen_vectors.py` 生成；禁止手写期望值绕过参考实现。
- 三端（C++/Kotlin/Python）必须全部通过；CTS 的跨架构组会重复校验（见 14 文档 X-01）。
