# 一致性测试（CTS）

本目录存放 Uni-RoboController 的一致性测试套件（Conformance Test Suite），规范见
[../docs/18-protocol-implementation-guide.md](../docs/18-protocol-implementation-guide.md) §6。

## 计划结构

```
conformance/
├── cts/                 # 测试用例（Python/pytest）
│   ├── discovery.py     # 发现（广播/mDNS）
│   ├── pairing.py       # 配对/认证/锁定
│   ├── session.py       # 会话/单控制者/重连
│   ├── control.py       # CTRL/TTL/死手/越界
│   ├── security.py      # 看门狗/急停/重放拒绝
│   ├── telemetry.py     # TELEM
│   ├── video.py         # 视频分片/FEC/关键帧
│   └── model.py         # MODEL_STATE/模型包
├── static/              # Schema/向量/文档一致性
├── report.py            # cts-report.json + Markdown
└── pyproject.toml
```

## 运行（M0 起逐步实现）

```bash
pytest conformance -m static
pytest conformance -m dynamic --target 127.0.0.1:47800 --secret-file /tmp/urc.secret
```

- P0 组（发现/配对/会话/控制/看门狗/急停/重放拒绝/跨架构向量）是接实机与兼容登记的门槛；
- 涉及运动的用例必须显式 `--allow-motion`；
- 测试向量来自 [../protocol/vectors/](../protocol/vectors/)（实现阶段加入）。
