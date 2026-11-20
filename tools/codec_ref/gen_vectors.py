# Copyright (c) 2026-2027 zbc
"""生成 URC 协议测试向量。

内容：
    用 Python 参考实现生成 protocol/vectors/{frames,crypto,frag,session}.json，
    供 C++/Kotlin 与 CTS 做字节级对齐。禁止手写期望值。

用法：
    python tools/codec_ref/gen_vectors.py            # 生成/覆盖
    python tools/codec_ref/gen_vectors.py --check    # 校验向量与实现同步
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from urc_ref import crypto, frag, frame, messages  # noqa: E402
from urc_ref.crc import crc32c_final  # noqa: E402

VECTORS = ROOT / "protocol" / "vectors"
SECRET = bytes(range(32))
APP_NONCE = bytes(range(16))
ROBOT_NONCE = bytes(range(16, 32))
SESSION_ID = 0x12345678


def hx(b: bytes) -> str:
    return b.hex()


def frame_case(name: str, f: frame.Frame, to_robot: bool = True, aead=None) -> dict:
    return {
        "name": name,
        "mode": "encode",
        "given": {
            "type": f.type, "flags": f.flags, "stream": f.stream,
            "session_id": f.session_id, "seq": f.seq, "ts_us": f.ts_us,
            "payload_hex": hx(f.payload),
            "to_robot": to_robot,
        },
        "expect": {"hex": hx(frame.pack(f, aead, to_robot))},
    }


def decode_case(name: str, raw: bytes, expect: dict, from_robot: bool = False, extra: dict | None = None) -> dict:
    given = {"hex": hx(raw), "from_robot": from_robot}
    if extra:
        given.update(extra)
    return {
        "name": name,
        "mode": "decode",
        "given": given,
        "expect": expect,
    }


def build_frames() -> dict:
    ctx = crypto.CryptoContext(SECRET, APP_NONCE, ROBOT_NONCE)
    cases = []
    base = dict(session_id=SESSION_ID, seq=1, ts_us=1_700_000_000_000_000)
    frames = [
        ("ctrl", frame.Frame(frame.T_CTRL, messages.pack_ctrl(0, [100, -50, 0, 25], [0b101]), **base)),
        ("telem", frame.Frame(frame.T_TELEM, messages.pack_telem(messages.Telemetry(
            seq=2, ts_us=1_700_000_000_000_001, fsm_state=1, battery_pct=88,
            x=1.0, y=-2.0, yaw=0.5, joint_q=(0.5, -0.25), policy_name="default")),
            seq=2, ts_us=1_700_000_000_000_001, session_id=SESSION_ID, stream=frame.S_TELEMETRY)),
        ("ping", frame.Frame(frame.T_PING, struct.pack("<Q", 123456789), session_id=SESSION_ID, seq=3, ts_us=123456789)),
        ("estop", frame.Frame(frame.T_ESTOP, messages.pack_estop(1, 123456789), flags=frame.F_ACK_REQ,
                              session_id=SESSION_ID, seq=4, ts_us=123456789)),
        ("caps", frame.Frame(frame.T_CAPS, messages.pack_caps(b'{"schema":"urc-capability/v1"}'),
                             session_id=SESSION_ID, seq=5, ts_us=1000)),
        ("video", frame.Frame(frame.T_VIDEO, messages.pack_video(7, 1000, 5, 0, 1, 0, 0, b"abcde"),
                              flags=frame.F_KEYFRAME, stream=frame.S_VIDEO, session_id=SESSION_ID, seq=6, ts_us=1000)),
        ("model_state", frame.Frame(frame.T_MODEL_STATE, messages.pack_model_state(
            1, 2000, 12345, 2, 0, 0, (1.0, 2.0, 3.0), (1.0, 0.0, 0.0, 0.0), (0.5, -0.5)),
            stream=frame.S_TELEMETRY, session_id=SESSION_ID, seq=7, ts_us=2000)),
        ("max_payload", frame.Frame(frame.T_CONFIG, bytes(i & 0xFF for i in range(1200)), session_id=SESSION_ID, seq=8, ts_us=3000)),
        ("empty_payload", frame.Frame(frame.T_PING, b"", session_id=SESSION_ID, seq=9, ts_us=4000)),
        ("unknown_type", frame.Frame(0x7E, b"\x01\x02", session_id=SESSION_ID, seq=10, ts_us=5000)),
    ]
    for name, f in frames:
        cases.append(frame_case(f"encode/{name}", f))
        cases.append(decode_case(f"decode/{name}", frame.pack(f), {
            "ok": True, "type": f.type, "flags": f.flags, "stream": f.stream,
            "session_id": f.session_id, "seq": f.seq, "ts_us": f.ts_us,
            "payload_hex": hx(f.payload),
        }))
    # 加密帧（双向）
    enc_ctrl = frame.Frame(frame.T_CTRL, messages.pack_ctrl(0, [1, 2, 3], [1]), session_id=SESSION_ID, seq=100, ts_us=9000)
    raw = frame.pack(enc_ctrl, ctx, to_robot=True)
    cases.append({
        "name": "encode/encrypted_ctrl", "mode": "encode",
        "given": {"type": enc_ctrl.type, "flags": 0, "stream": enc_ctrl.stream,
                  "session_id": SESSION_ID, "seq": 100, "ts_us": 9000,
                  "payload_hex": hx(enc_ctrl.payload), "to_robot": True,
                  "secret_hex": hx(SECRET), "app_nonce_hex": hx(APP_NONCE), "robot_nonce_hex": hx(ROBOT_NONCE)},
        "expect": {"hex": hx(raw)},
    })
    cases.append(decode_case("decode/encrypted_ctrl", raw, {
        "ok": True, "type": enc_ctrl.type, "flags": enc_ctrl.flags | frame.F_ENCRYPTED,
        "stream": enc_ctrl.stream, "session_id": SESSION_ID, "seq": 100, "ts_us": 9000,
        "payload_hex": hx(enc_ctrl.payload),
    }, extra={"secret_hex": hx(SECRET), "app_nonce_hex": hx(APP_NONCE), "robot_nonce_hex": hx(ROBOT_NONCE)}))
    # 负例
    good = frame.pack(frames[0][1])
    bad_magic = bytearray(good); bad_magic[0] ^= 0xFF
    bad_crc = bytearray(good); bad_crc[-1] ^= 0xFF
    short = good[:16]
    bad_len = bytearray(good); bad_len[24:26] = struct.pack("<H", 99)
    cases.append(decode_case("decode/bad_magic", bytes(bad_magic), {"ok": False}))
    cases.append(decode_case("decode/bad_crc", bytes(bad_crc), {"ok": False}))
    cases.append(decode_case("decode/short", short, {"ok": False}))
    cases.append(decode_case("decode/bad_len", bytes(bad_len), {"ok": False}))
    return {"meta": {"protocol": "urc/1", "crc": "CRC-32/ISCSI"}, "cases": cases}


def build_crypto() -> dict:
    cases = []
    for name, secret, an, rn in [
        ("sequential", SECRET, APP_NONCE, ROBOT_NONCE),
        ("zeros", bytes(32), bytes(16), bytes(16)),
        ("ones", b"\x01" * 32, b"\x02" * 16, b"\x03" * 16),
    ]:
        keys = crypto.derive_session(secret, an, rn)
        cases.append({
            "name": f"derive/{name}", "kind": "derive",
            "given": {"secret_hex": hx(secret), "app_nonce_hex": hx(an), "robot_nonce_hex": hx(rn)},
            "expect": {"app2robot_hex": hx(keys["app2robot"]), "robot2app_hex": hx(keys["robot2app"]),
                       "confirm_hex": hx(keys["confirm"])},
        })
    for name, secret, an, rn, sid in [
        ("basic", SECRET, APP_NONCE, ROBOT_NONCE, SESSION_ID),
        ("sid0", SECRET, APP_NONCE, ROBOT_NONCE, 0),
    ]:
        cases.append({
            "name": f"auth/{name}", "kind": "auth",
            "given": {"secret_hex": hx(secret), "app_nonce_hex": hx(an), "robot_nonce_hex": hx(rn), "session_id": sid},
            "expect": {"proof_hex": hx(crypto.auth_proof(secret, an, rn, sid))},
        })
    ctx = crypto.CryptoContext(SECRET, APP_NONCE, ROBOT_NONCE)
    for name, key, seq, to_robot, aad, plain in [
        ("app2robot/short", ctx.app2robot_key, 1, True, b"header", b"x"),
        ("app2robot/16b", ctx.app2robot_key, 0xFFFFFFFF, True, b"A" * 32, bytes(range(16))),
        ("robot2app/64b", ctx.robot2app_key, 42, False, b"hdr2", bytes(range(64))),
        ("app2robot/empty", ctx.app2robot_key, 7, True, b"", b""),
    ]:
        nonce = crypto.CryptoContext.make_nonce(seq, to_robot)
        cipher = crypto.CryptoContext.encrypt(key, nonce, aad, plain)
        cases.append({
            "name": f"aead/{name}", "kind": "aead",
            "given": {"key_hex": hx(key), "nonce_hex": hx(nonce), "aad_hex": hx(aad), "plaintext_hex": hx(plain)},
            "expect": {"ciphertext_hex": hx(cipher)},
        })
    for name, seq, to_robot in [("app2robot", 1, True), ("robot2app", 42, False),
                                ("wrap", 0x0102030405060708, True)]:
        nonce = crypto.CryptoContext.make_nonce(seq, to_robot)
        cases.append({"name": f"nonce/{name}", "kind": "nonce",
                      "given": {"seq": seq, "to_robot": to_robot},
                      "expect": {"nonce_hex": hx(nonce)}})
    for name, aad, bad_aad, plain in [
        ("wrong_aad", b"header-ok", b"header-bad", b"payload"),
        ("wrong_aad_empty", b"", b"x", b"abc"),
    ]:
        nonce = crypto.CryptoContext.make_nonce(9, True)
        cipher = crypto.CryptoContext.encrypt(ctx.app2robot_key, nonce, aad, plain)
        cases.append({"name": f"aead_bad_aad/{name}", "kind": "aead_bad_aad",
                      "given": {"key_hex": hx(ctx.app2robot_key), "nonce_hex": hx(nonce),
                                "bad_aad_hex": hx(bad_aad), "ciphertext_hex": hx(cipher)},
                      "expect": {"decrypt_failed": True}})
    replay = [
        ("in_window_first", 8, [100, 101, 102], 101, False),
        ("new_high", 8, [100, 101, 102], 103, True),
        ("old_out_window", 8, [100, 101, 102], 90, False),
        ("duplicate", 8, [100, 101, 102], 102, False),
        ("gap_ok", 8, [100, 102], 101, True),
        ("window_edge", 8, [100, 101, 102, 103, 104, 105, 106, 107], 100, False),
        ("window_edge_plus", 8, [100, 101, 102, 103, 104, 105, 106, 107], 99, False),
    ]
    for name, window, previous, incoming, accept in replay:
        cases.append({
            "name": f"replay/{name}", "kind": "replay",
            "given": {"window": window, "previous": previous, "incoming": incoming},
            "expect": {"accept": accept},
        })
    return {"meta": {"protocol": "urc/1"}, "cases": cases}


def build_frag() -> dict:
    cases = []
    for size in (0, 1, 100, 1192, 1193, 5000):
        payload = bytes((i * 37) & 0xFF for i in range(size))
        parts = frag.fragment(payload, 1200, 42)
        cases.append({
            "name": f"fragment/size_{size}", "mode": "fragment",
            "given": {"payload_hex": hx(payload), "mtu": 1200, "msg_id": 42},
            "expect": {"fragments": [hx(p) for p in parts]},
        })
        r = frag.Reassembler()
        delivered = None
        for p in parts:
            out = r.add(p)
            if out is not None:
                delivered = out
        assert delivered == payload
    # 乱序 + 重复重组
    payload = bytes(range(200))
    parts = frag.fragment(payload, 1200, 7)
    order = [parts[-1]] + parts[:-1] + [parts[0]]
    cases.append({
        "name": "reassemble/out_of_order_dup", "mode": "reassemble",
        "given": {"fragments": [hx(p) for p in order]},
        "expect": {"payload_hex": hx(payload)},
    })
    # 缺片（payload 跨多个分片，缺少中间片）
    big_payload = bytes(range(256)) * 20  # 5120 B → 5 片
    big_parts = frag.fragment(big_payload, 1200, 11)
    cases.append({
        "name": "reassemble/missing", "mode": "reassemble",
        "given": {"fragments": [hx(big_parts[0]), hx(big_parts[-1])]},
        "expect": {"payload_hex": None},
    })
    # 单分片空 payload
    single = frag.fragment(b"", 1200, 9)
    cases.append({
        "name": "fragment/empty", "mode": "fragment",
        "given": {"payload_hex": "", "mtu": 1200, "msg_id": 9},
        "expect": {"fragments": [hx(p) for p in single]},
    })
    return {"meta": {"protocol": "urc/1"}, "cases": cases}


def build_session() -> dict:
    cases = []
    hello = messages.pack_hello(1, 0, 0, 0, b"app-id-000000001", APP_NONCE, "0.1.0")
    cases.append({"name": "hello/basic", "kind": "hello", "given": {
        "proto_major": 1, "proto_minor": 0, "role": 0, "flags": 0,
        "app_id_hex": hx(b"app-id-000000001"), "app_nonce_hex": hx(APP_NONCE), "app_version": "0.1.0"},
        "expect": {"hex": hx(hello)}})
    ack = messages.HelloAck(1, 0, SESSION_ID, "mock-quadruped", "Mock Quad", "quadruped",
                            ROBOT_NONCE, 0xDEADBEEF, 47800, 47801, 47802, 47803, 47880, 1)
    cases.append({"name": "hello_ack/basic", "kind": "hello_ack", "given": {
        "proto_major": 1, "proto_minor": 0, "session_id": SESSION_ID,
        "robot_id": "mock-quadruped", "robot_name": "Mock Quad", "form": "quadruped",
        "robot_nonce_hex": hx(ROBOT_NONCE), "caps_hash": 0xDEADBEEF,
        "ctrl_port": 47800, "video_port": 47801, "depth_port": 47802, "map_port": 47803, "web_port": 47880,
        "auth_required": 1}, "expect": {"hex": hx(messages.pack_hello_ack(ack))}})
    proof = crypto.auth_proof(SECRET, APP_NONCE, ROBOT_NONCE, SESSION_ID)
    auth = messages.pack_auth(proof, b"client-id-000001", "Phone")
    cases.append({"name": "auth/basic", "kind": "auth", "given": {
        "proof_hex": hx(proof), "client_id_hex": hx(b"client-id-000001"), "client_name": "Phone"},
        "expect": {"hex": hx(auth)}})
    confirm = crypto.derive_session(SECRET, APP_NONCE, ROBOT_NONCE)["confirm"]
    auth_ok = messages.pack_auth_ok(0, confirm, 1_700_000_000_000_000)
    cases.append({"name": "auth_ok/basic", "kind": "auth_ok", "given": {
        "role": 0, "key_confirm_hex": hx(confirm), "server_ts_us": 1_700_000_000_000_000},
        "expect": {"hex": hx(auth_ok)}})
    caps = messages.pack_caps(b'{"schema":"urc-capability/v1"}')
    cases.append({"name": "caps/raw", "kind": "caps", "given": {
        "json_hex": hx(b'{"schema":"urc-capability/v1"}'), "encoding": 0}, "expect": {"hex": hx(caps)}})
    telem = messages.pack_telem(messages.Telemetry(
        seq=5, ts_us=123456789, fsm_state=2, fault_flags=0, battery_pct=77,
        x=1.0, y=-2.0, yaw=0.5, joint_q=(0.5, -0.25), joint_dq=(0.1, 0.2),
        imu_quat=(1.0, 0.0, 0.0, 0.0), policy_name="default", inference_us=8000,
        queue_depth=2, link_rtt_us=1500, link_loss_pct=1, remote_age_ms=12))
    cases.append({"name": "telem/basic", "kind": "telem", "given": {
        "seq": 5, "ts_us": 123456789, "fsm_state": 2, "fault_flags": 0, "battery_pct": 77,
        "x": 1.0, "y": -2.0, "yaw": 0.5, "joint_q": [0.5, -0.25], "joint_dq": [0.1, 0.2],
        "imu_quat": [1.0, 0.0, 0.0, 0.0], "policy_name": "default", "inference_us": 8000,
        "queue_depth": 2, "link_rtt_us": 1500, "link_loss_pct": 1, "remote_age_ms": 12},
        "expect": {"hex": hx(telem)}})
    model = messages.pack_model_state(9, 123456789, 12345, 3, 0, 0,
                                      (1.0, 2.0, 3.0), (1.0, 0.0, 0.0, 0.0), (0.5, -0.5, 0.25))
    cases.append({"name": "model_state/basic", "kind": "model_state", "given": {
        "seq": 9, "ts_us": 123456789, "joint_order_hash": 12345, "joint_count": 3,
        "flags": 0, "frame_id": 0, "root_pos": [1.0, 2.0, 3.0], "root_quat": [1.0, 0.0, 0.0, 0.0],
        "joint_pos": [0.5, -0.5, 0.25]}, "expect": {"hex": hx(model)}})
    disc = messages.pack_discover(APP_NONCE, b"app-id-000000001")
    cases.append({"name": "discover/basic", "kind": "discover", "given": {
        "app_nonce_hex": hx(APP_NONCE), "app_id_hex": hx(b"app-id-000000001")},
        "expect": {"hex": hx(disc)}})
    ann = messages.Announce("mock-quadruped", "Mock Quad", "quadruped", 47800, 0, 0, 0, 47880, 0xDEADBEEF, 1)
    cases.append({"name": "announce/basic", "kind": "announce", "given": {
        "robot_id": "mock-quadruped", "robot_name": "Mock Quad", "form": "quadruped",
        "ctrl_port": 47800, "video_port": 0, "depth_port": 0, "map_port": 0,
        "web_port": 47880, "caps_hash": 0xDEADBEEF, "pair_state": 1},
        "expect": {"hex": hx(messages.pack_announce(ann))}})
    # 新增消息：SESSION_CTRL/EVENT/ERROR/PING/PONG/FEEDBACK/VIDEO 头
    for action in range(5):
        payload = messages.pack_session_ctrl(action)
        cases.append({"name": f"session_ctrl/action_{action}", "kind": "session_ctrl",
                      "given": {"action": action}, "expect": {"hex": hx(payload)}})
    for code, level, text in [(0x0001, 0, "estop acked"), (0x0002, 1, "watchdog"), (0x0003, 0, "armed")]:
        cases.append({"name": f"event/code_{code:04x}", "kind": "event",
                      "given": {"code": code, "level": level, "message": text},
                      "expect": {"hex": hx(messages.pack_event(code, level, text))}})
    cases.append({"name": "error/basic", "kind": "error",
                  "given": {"code": 0x0101, "message": "auth failed"},
                  "expect": {"hex": hx(messages.pack_error(0x0101, "auth failed"))}})
    cases.append({"name": "ping/basic", "kind": "ping", "given": {"ts_us": 123456789},
                  "expect": {"hex": hx(struct.pack("<Q", 123456789))}})
    cases.append({"name": "pong/basic", "kind": "pong", "given": {"ts_us": 987654321},
                  "expect": {"hex": hx(struct.pack("<Q", 987654321))}})
    feedback = messages.pack_feedback(10, 1, 2, 5000, 60, 3, 1500, 200, 4000, 0b101)
    cases.append({"name": "feedback/basic", "kind": "feedback",
                  "given": {"video_ok": 10, "video_lost": 1, "packets_lost": 2, "recv_kbps": 5000,
                            "decode_fps": 60, "decode_ms": 3, "rtt_us": 1500, "jitter_us": 200,
                            "target_kbps": 4000, "flags": 0b101},
                  "expect": {"hex": hx(feedback)}})
    video_payload = messages.pack_video(1, 1000, 5, 0, 1, 0, 0x05, b"abcde")
    cases.append({"name": "video/header", "kind": "video",
                  "given": {"frame_id": 1, "frame_ts_us": 1000, "frame_bytes": 5, "pkt_idx": 0,
                            "pkt_cnt": 1, "group_id": 0, "media_flags": 0x05, "data_hex": "6162636465"},
                  "expect": {"hex": hx(video_payload)}})
    return {"meta": {"protocol": "urc/1"}, "cases": cases}


def build_replay() -> dict:
    """帧级重放向量：每方向全局窗口，跨流同 seq 必须拒绝。"""
    cases = []

    def frame_hex(ftype: int, stream: int, session_id: int, seq: int, payload: bytes = b"") -> str:
        return hx(frame.pack(frame.Frame(ftype, payload, stream=stream, session_id=session_id,
                                         seq=seq, ts_us=1000)))

    cases.append({"name": "replay/global_monotonic", "frames": [
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 100),
        frame_hex(frame.T_TELEM, frame.S_TELEMETRY, 1, 101),
        frame_hex(frame.T_VIDEO, frame.S_VIDEO, 1, 102),
    ], "expect": ["accept", "accept", "accept"]})
    cases.append({"name": "replay/duplicate", "frames": [
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 200),
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 200),
    ], "expect": ["accept", "reject"]})
    cases.append({"name": "replay/cross_stream_same_seq", "frames": [
        frame_hex(frame.T_CTRL, frame.S_CTRL, 1, 300),
        frame_hex(frame.T_FEEDBACK, frame.S_FEEDBACK, 1, 300),
    ], "expect": ["accept", "reject"]})
    cases.append({"name": "replay/old_out_of_window", "frames": [
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 500),
        frame_hex(frame.T_PING, frame.S_CTRL, 1, (500 - 3000) & 0xFFFFFFFF),
    ], "expect": ["accept", "reject"]})
    cases.append({"name": "replay/u32_wrap", "frames": [
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 0xFFFFFFFE),
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 0xFFFFFFFF),
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 0),
        frame_hex(frame.T_PING, frame.S_CTRL, 1, 1),
    ], "expect": ["accept", "accept", "accept", "accept"]})
    return {"meta": {"protocol": "urc/1", "note": "seq 每方向全局，跨流共享"}, "cases": cases}


def write_or_check(name: str, obj: dict, check: bool) -> int:
    path = VECTORS / f"{name}.json"
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if check:
        if not path.exists():
            print(f"[FAIL] missing {path}")
            return 1
        if path.read_text(encoding="utf-8") != text:
            print(f"[FAIL] out of date: {path}")
            return 1
        print(f"[OK]   {path.name}")
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"[GEN]  {path.name} ({len(obj['cases'])} cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    VECTORS.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, builder in (("frames", build_frames), ("crypto", build_crypto),
                          ("frag", build_frag), ("session", build_session),
                          ("replay", build_replay)):
        failed += write_or_check(name, builder(), args.check)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
