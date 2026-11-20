# Copyright (c) 2026-2027 zbc
"""URC 参考服务端（Python），实现 S1 冻结语义。

内容：
    发现、配对（fail-closed 认证门）、HELLO/AUTH、claim/arm 状态机、CTRL/TTL、
    TELEM/MODEL_STATE/VIDEO、看门狗、两步急停、per-来源锁定、全局 seq/重放窗口、
    故障注入与统计文件。仅用于 App/CTS 开发，不是生产实现。

用法：
    python tools/codec_ref/ref_server.py --capability protocol/examples/capability.mock_quadruped.json
    python tools/codec_ref/ref_server.py --secret-file /tmp/urc.secret --no-camera \
        --stats-file /tmp/urc-stats.json --watchdog-ms 300 --ctrl-ttl-ms 200
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import select
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from urc_ref import crypto, frame, frag, messages  # noqa: E402
from urc_ref.capability import canonical_json, caps_hash, joint_order_hash  # noqa: E402

# 会话动作（03 §3.1）
ACT_CLAIM, ACT_RELEASE, ACT_VIEWER, ACT_ARM, ACT_RELEASE_ESTOP = range(5)
# 事件码
EVT_ESTOP_ACKED, EVT_WATCHDOG, EVT_ARMED, EVT_SESSION_EXPIRED, EVT_ESTOP_RELEASED = (
    0x0001, 0x0002, 0x0003, 0x0004, 0x0005)
# 错误码
ERR_AUTH, ERR_SESSION, ERR_ROLE, ERR_RANGE, ERR_ESTOP, ERR_LOCKED = (
    0x0101, 0x0102, 0x0103, 0x0301, 0x0302, 0x0602)


def now_us() -> int:
    return time.monotonic_ns() // 1000


class ReferenceServer:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)
        self.cap = json.loads(Path(args.capability).read_text(encoding="utf-8"))
        self.cap_bytes = canonical_json(self.cap)
        self.caps_hash = caps_hash(self.cap)
        self.joint_order = (self.cap.get("model") or {}).get("joint_order") or []
        self.joint_hash = joint_order_hash(self.joint_order) if self.joint_order else 0
        self.modes = {m["id"]: m for m in self.cap["control"]["modes"]}
        self.channels = self.cap["control"]["modes"][0].get("channels", [])
        self.video_w, self.video_h, self.video_fps = 160, 120, 10
        streams = self.cap.get("streams") or []
        if not streams or "rgb888" not in (streams[0].get("codecs") or []):
            raise SystemExit("S1 ref server requires a capability with a rgb888 stream")
        res = streams[0].get("res") or [160, 120]
        self.video_w, self.video_h = int(res[0]), int(res[1])
        fps = streams[0].get("fps") or [10]
        self.video_fps = int(fps[0])
        self.hello_times: dict[tuple, list[float]] = {}
        self.announce_times: list[float] = []
        self.secret = self._load_secret()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((args.bind, args.ctrl_port))
        self.sock.setblocking(False)
        self.disc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.disc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.disc.bind((args.bind, args.discovery_port))
        self.disc.setblocking(False)

        # 会话/安全状态
        self.peer = None
        self.pending = False
        self.authenticated = False
        self.claimed = False
        self.armed = False
        self.estop_latched = False
        self.session_id = 0
        self.app_nonce = b""
        self.robot_nonce = os.urandom(16)
        self.ctx: crypto.CryptoContext | None = None
        self.pending_since = 0.0
        self.last_rx = 0.0
        self.last_valid_ctrl = 0.0
        self.auth_failures: dict[tuple, int] = {}
        self.lock_until: dict[tuple, float] = {}
        self.error_times: dict[tuple, list[float]] = {}
        self.client_replay = crypto.ReplayWindow(2048)
        self.tx_seq = 0

        # 控制/媒体状态
        self.axes = [0.0] * len(self.channels)
        self.buttons = [0, 0]
        self.watchdog_fired = False
        self.next_telem = 0.0
        self.next_model = 0.0
        self.next_video = 0.0
        self.telem_seq = 0
        self.model_seq = 0
        self.video_frame_id = 0
        self.next_stats = 0.0
        self.next_flush = 0.0

        # 注入
        self.hold_next_ms = args.hold_next_ms

        # 统计
        self.stats = {
            "rx_frames": 0, "tx_frames": 0, "rx_drop": 0, "gate_drop": 0,
            "auth_fail": 0, "lockout": 0, "replay_drop": 0, "aead_fail": 0,
            "ttl_dropped": 0, "invalid_ctrl": 0, "watchdog": 0, "estop": 0,
            "sessions_expired": 0, "dropped_tx": 0, "corrupt_tx": 0,
        }

    # ---------- secret / stats ----------

    def _load_secret(self) -> bytes:
        path = self.args.secret_file
        if path and Path(path).exists():
            raw = Path(path).read_bytes()
            if len(raw) != 32:
                raise SystemExit("secret file must be 32 bytes")
            print(f"[server] loaded secret from {path}", flush=True)
            return raw
        secret = os.urandom(32)
        if path:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(secret)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        print(f"URCPAIR:{base64.b64encode(secret).decode()}", flush=True)
        return secret

    def write_stats(self) -> None:
        if not self.args.stats_file:
            return
        path = Path(self.args.stats_file)
        tmp = path.with_suffix(path.suffix + ".tmp")
        data = dict(self.stats)
        data["session"] = {
            "authenticated": self.authenticated, "claimed": self.claimed,
            "armed": self.armed, "estop_latched": self.estop_latched,
            "pending": self.pending,
        }
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    # ---------- send helpers ----------

    def _drop_or_corrupt(self, raw: bytes) -> bytes | None:
        if self.args.drop and self.rng.random() * 100 < self.args.drop:
            self.stats["dropped_tx"] += 1
            return None
        if self.args.corrupt_aead and self.ctx and self.rng.random() * 100 < self.args.corrupt_aead:
            # 翻转密文中一个字节，并重算 CRC，强制对端 AEAD 失败
            body = bytearray(raw[32:])
            if len(body) > 16:
                idx = self.rng.randrange(len(body) - 16)
                body[idx] ^= 0xFF
                header = bytearray(raw[:32])
                header[28:32] = b"\x00\x00\x00\x00"
                from urc_ref.crc import crc32c_final
                header[28:32] = struct.pack("<I", crc32c_final(bytes(header) + bytes(body)))
                raw = bytes(header) + bytes(body)
                self.stats["corrupt_tx"] += 1
        return raw

    def send(self, ftype: int, payload: bytes, flags: int = 0, stream: int = frame.S_CTRL,
             addr=None, encrypt: bool = True) -> None:
        target = addr or self.peer
        if target is None:
            return
        self.tx_seq = (self.tx_seq + 1) & 0xFFFFFFFF
        f = frame.Frame(ftype, payload, flags=flags, stream=stream,
                        session_id=self.session_id, seq=self.tx_seq, ts_us=now_us())
        use_ctx = self.ctx if (encrypt and self.ctx) else None
        raw = frame.pack(f, use_ctx, to_robot=False)
        raw = self._drop_or_corrupt(raw)
        if raw is None:
            return
        self.sock.sendto(raw, target)
        self.stats["tx_frames"] += 1

    def send_error(self, code: int, msg: str, addr=None, rate_limit: bool = True) -> None:
        target = addr or self.peer
        if target is None:
            return
        # 认证前/后都限速 2/s/来源，避免放大；AUTH 失败本身不计入限速
        if rate_limit:
            now = time.monotonic()
            times = [t for t in self.error_times.get(target, []) if now - t < 1.0]
            if len(times) >= 2:
                return
            times.append(now)
            self.error_times[target] = times
        encrypt = target == self.peer and self.authenticated and self.ctx is not None
        self.send(frame.T_ERROR, messages.pack_error(code, msg), addr=target, encrypt=encrypt)

    def send_event(self, code: int, level: int, msg: str) -> None:
        if not self.authenticated:
            return
        self.send(frame.T_EVENT, messages.pack_event(code, level, msg))

    # ---------- discovery ----------

    def handle_discovery(self) -> None:
        while True:
            try:
                data, addr = self.disc.recvfrom(2048)
            except BlockingIOError:
                return
            try:
                messages.unpack_discover(data)
            except ValueError:
                continue
            now = time.monotonic()
            self.announce_times = [t for t in self.announce_times if now - t < 1.0]
            if len(self.announce_times) >= 20:
                continue  # ANNOUNCE ≤20/s（全局）
            self.announce_times.append(now)
            ann = messages.Announce(
                self.cap["robot_id"], self.cap.get("name", "robot"), self.cap["form"],
                self.args.ctrl_port, 0, 0, 0, self.args.web_port,
                self.caps_hash, 1 if self.authenticated else 0)
            self.disc.sendto(messages.pack_announce(ann), addr)

    # ---------- session reset / timeout ----------

    def reset_session(self, keep_estop: bool = True) -> None:
        self.peer = None
        self.pending = False
        self.authenticated = False
        self.claimed = False
        self.armed = False
        self.session_id = 0
        self.app_nonce = b""
        self.robot_nonce = os.urandom(16)
        self.ctx = None
        self.client_replay = crypto.ReplayWindow(2048)
        self.axes = [0.0] * len(self.channels)
        if not keep_estop:
            self.estop_latched = False

    def on_hello(self, f: frame.Frame, addr) -> None:
        now = time.monotonic()
        times = [t for t in self.hello_times.get(addr, []) if now - t < 1.0]
        if len(times) >= 10:
            return  # HELLO_ACK ≤10/s/来源
        times.append(now)
        self.hello_times[addr] = times
        if self.claimed and self.peer != addr:
            self.send_error(ERR_ROLE, "controller occupied", addr=addr)
            return
        hello = messages.unpack_hello(f.payload)
        if not (1 == hello["proto_major"]):
            self.send_error(0x0201, "protocol major mismatch", addr=addr)
            return
        # 新 HELLO：旧会话立即失效；急停锁存保留
        self.reset_session(keep_estop=True)
        self.peer = addr
        self.pending = True
        self.pending_since = time.monotonic()
        self.session_id = struct.unpack("<I", os.urandom(4))[0]
        self.app_nonce = hello["app_nonce"]
        self.robot_nonce = os.urandom(16)
        self.ctx = crypto.CryptoContext(self.secret, self.app_nonce, self.robot_nonce)
        ack = messages.HelloAck(1, 0, self.session_id, self.cap["robot_id"],
                                self.cap.get("name", "robot"), self.cap["form"],
                                self.robot_nonce, self.caps_hash,
                                self.args.ctrl_port, 0, 0, 0, self.args.web_port, 1)
        self.send(frame.T_HELLO_ACK, messages.pack_hello_ack(ack), addr=addr, encrypt=False)

    def on_auth(self, f: frame.Frame, addr) -> None:
        now = time.monotonic()
        if now < self.lock_until.get(addr, 0):
            self.send_error(ERR_LOCKED, "auth locked", addr=addr)
            return
        if not self.pending or self.peer != addr or f.session_id != self.session_id:
            # 无 pending / 来源不符 / 会话不符：静默丢弃并计数（明文例外集只允许指定错误码）
            self.stats["gate_drop"] += 1
            return
        auth = messages.unpack_auth(f.payload)
        want = crypto.auth_proof(self.secret, self.app_nonce, self.robot_nonce, self.session_id)
        if auth["proof"] != want:
            self.stats["auth_fail"] += 1
            failures = self.auth_failures.get(addr, 0) + 1
            self.auth_failures[addr] = failures
            if failures >= 5:
                self.lock_until[addr] = now + 30
                self.stats["lockout"] += 1
            self.send_error(ERR_AUTH, "auth failed", addr=addr, rate_limit=False)
            return
        self.authenticated = True
        self.pending = False
        self.auth_failures.pop(addr, None)
        self.last_rx = now
        self.send(frame.T_AUTH_OK, messages.pack_auth_ok(0, self.ctx.key_confirm, now_us()),
                  addr=addr, encrypt=False)

    # ---------- frame handling ----------

    def handle_datagram(self, data: bytes, addr) -> None:
        self.stats["rx_frames"] += 1
        if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != frame.MAGIC:
            self.stats["rx_drop"] += 1
            return
        flags = data[6]
        encrypted = bool(flags & frame.F_ENCRYPTED)
        try:
            if not encrypted:
                f = frame.unpack(data, from_robot=False)
                if f.type == frame.T_HELLO:
                    self.on_hello(f, addr)
                elif f.type == frame.T_AUTH:
                    self.on_auth(f, addr)
                else:
                    # 未认证的非握手包一律丢弃
                    self.stats["gate_drop"] += 1
                return
            if not self.authenticated or self.ctx is None:
                self.stats["gate_drop"] += 1
                return
            if struct.unpack_from("<I", data, 8)[0] != self.session_id:
                self.stats["gate_drop"] += 1
                return
            f = frame.unpack(data, self.ctx, from_robot=False)
        except Exception:
            if encrypted:
                self.stats["aead_fail"] += 1
            else:
                self.stats["rx_drop"] += 1
            return
        if not self.client_replay.accept(f.seq):
            self.stats["replay_drop"] += 1
            return
        self.last_rx = time.monotonic()
        # 一次性 TTL 注入：只命中下一帧 CTRL
        if f.type == frame.T_CTRL and self.hold_next_ms > 0:
            recv_ts = time.monotonic()
            time.sleep(self.hold_next_ms / 1000.0)
            self.hold_next_ms = 0
            age_ms = (time.monotonic() - recv_ts) * 1000.0
            if age_ms > self.args.ctrl_ttl_ms:
                self.stats["ttl_dropped"] += 1
                return
        self.dispatch(f, addr)

    def dispatch(self, f: frame.Frame, addr) -> None:
        if f.type == frame.T_SESSION_CTRL:
            self.on_session_ctrl(f, addr)
        elif f.type == frame.T_CTRL:
            self.on_ctrl(f, addr)
        elif f.type == frame.T_ESTOP:
            self.on_estop(f, addr)
        elif f.type == frame.T_PING:
            self.on_ping(f, addr)
        elif f.type == frame.T_FEEDBACK:
            pass
        else:
            self.stats["invalid_ctrl"] += 1

    def is_controller(self, addr) -> bool:
        return self.claimed and self.peer == addr

    def on_session_ctrl(self, f: frame.Frame, addr) -> None:
        action = messages.unpack_session_ctrl(f.payload)["action"]
        if action == ACT_CLAIM:
            if self.claimed and self.peer != addr:
                self.send_error(ERR_ROLE, "controller occupied")
                return
            self.claimed = True
            self.peer = addr
            self.armed = False
            self.send_caps()
        elif action == ACT_RELEASE:
            if not self.is_controller(addr):
                return
            self.claimed = False
            self.armed = False
            self.axes = [0.0] * len(self.channels)
        elif action == ACT_VIEWER:
            self.send_error(ERR_ROLE, "viewer not implemented")
        elif action == ACT_ARM:
            if not self.is_controller(addr):
                self.send_error(ERR_ROLE, "claim required")
                return
            if self.estop_latched:
                self.send_error(ERR_ESTOP, "estop latched")
                return
            self.armed = True
            self.watchdog_fired = False
            self.last_valid_ctrl = time.monotonic()
            self.send_event(EVT_ARMED, 0, "armed")
        elif action == ACT_RELEASE_ESTOP:
            if not self.estop_latched:
                return  # 未锁存时 no-op
            self.estop_latched = False
            self.armed = False
            self.watchdog_fired = False
            self.axes = [0.0] * len(self.channels)
            self.send_event(EVT_ESTOP_RELEASED, 0, "estop released")
        else:
            self.send_error(ERR_RANGE, "bad session action")

    def on_ctrl(self, f: frame.Frame, addr) -> None:
        if not self.is_controller(addr) or not self.armed or self.estop_latched:
            self.stats["invalid_ctrl"] += 1
            self.axes = [0.0] * len(self.channels)
            return
        ctrl = messages.unpack_ctrl(f.payload)
        if ctrl["mode"] not in self.modes:
            self.stats["invalid_ctrl"] += 1
            self.send_error(ERR_RANGE, "bad mode")
            return
        if len(ctrl["axes"]) != len(self.channels):
            self.stats["invalid_ctrl"] += 1
            self.send_error(ERR_RANGE, "bad axis count")
            return
        if not (ctrl["flags"] & 0x01):  # 死手未按下 -> 零速，但仍是有效控制帧
            self.axes = [0.0] * len(self.channels)
            self.last_valid_ctrl = time.monotonic()
            return
        values = []
        for v, ch in zip(ctrl["axes"], self.channels):
            lo, hi = ch["range"]
            scale = ch.get("scale", max(abs(lo), abs(hi)))
            physical = v / 32767.0 * scale if scale else 0.0
            if physical < lo - 1e-3 or physical > hi + 1e-3:
                self.stats["invalid_ctrl"] += 1
                self.send_error(ERR_RANGE, f"axis {ch['id']} out of range")
                return
            values.append(physical)
        self.axes = values
        self.buttons = ctrl["buttons"]
        self.last_valid_ctrl = time.monotonic()
        self.watchdog_fired = False

    def on_estop(self, f: frame.Frame, addr) -> None:
        estop = messages.unpack_estop(f.payload)
        if estop["reason"] == 0:
            return  # 不清锁存、不 arm
        self.estop_latched = True
        self.stats["estop"] += 1
        self.armed = False
        self.watchdog_fired = False
        self.axes = [0.0] * len(self.channels)
        self.send_event(EVT_ESTOP_ACKED, 0, "estop acked")

    def on_ping(self, f: frame.Frame, addr) -> None:
        echo = struct.unpack("<Q", f.payload)[0]
        self.send(frame.T_PONG, struct.pack("<Q", echo))

    # ---------- periodic sends ----------

    def send_caps(self) -> None:
        payload = messages.pack_caps(self.cap_bytes)
        parts = frag.fragment(payload, 1190, 0x1000)
        for idx, part in enumerate(parts):
            flags = frame.F_LAST_FRAG if idx == len(parts) - 1 else 0
            self.send(frame.T_CAPS, part, flags=flags)

    def send_telem(self) -> None:
        self.telem_seq = (self.telem_seq + 1) & 0xFFFFFFFF
        fault = (1 if self.watchdog_fired else 0) | (2 if self.estop_latched else 0)
        t = messages.Telemetry(
            seq=self.telem_seq, ts_us=now_us(),
            fsm_state=2 if self.estop_latched else (1 if self.armed else 0),
            fault_flags=fault, battery_pct=88,
            x=self.axes[0] if len(self.axes) > 0 else 0.0,
            y=self.axes[1] if len(self.axes) > 1 else 0.0,
            yaw=self.axes[2] if len(self.axes) > 2 else 0.0,
            policy_name="mock",
            remote_age_ms=int((time.monotonic() - self.last_valid_ctrl) * 1000)
            if self.last_valid_ctrl else 9999,
            queue_depth=0, link_rtt_us=0, link_loss_pct=0, map_revision=0)
        self.send(frame.T_TELEM, messages.pack_telem(t), stream=frame.S_TELEMETRY)

    def send_model(self) -> None:
        count = len(self.joint_order)
        if count == 0:
            return
        self.model_seq = (self.model_seq + 1) & 0xFFFFFFFF
        t = time.monotonic()
        pos = [0.2 * math.sin(t * 2 + i) for i in range(count)]
        state = messages.pack_model_state(
            self.model_seq, now_us(), self.joint_hash, count,
            0x04, 0, (0.0, 0.0, 0.3), (1.0, 0.0, 0.0, 0.0), pos)
        self.send(frame.T_MODEL_STATE, state, stream=frame.S_TELEMETRY)

    def send_video(self) -> None:
        w, h = self.video_w, self.video_h
        data = bytearray(w * h * 3)
        for y in range(h):
            row = y * w * 3
            for x in range(w):
                o = row + x * 3
                data[o] = (x * 255 // w) & 0xFF
                data[o + 1] = (y * 255 // h) & 0xFF
                data[o + 2] = 128
        self.video_frame_id = (self.video_frame_id + 1) & 0xFFFFFFFF
        chunk = 1190 - 23
        count = (len(data) + chunk - 1) // chunk
        ts = now_us()
        for idx in range(count):
            part = bytes(data[idx * chunk:(idx + 1) * chunk])
            media_flags = 0x01 | (0x04 if idx == count - 1 else 0)
            payload = messages.pack_video(self.video_frame_id, ts, len(data), idx,
                                          count, 0, media_flags, part)
            self.send(frame.T_VIDEO, payload, flags=frame.F_KEYFRAME, stream=frame.S_VIDEO)

    # ---------- timers ----------

    def loop_timers(self) -> None:
        now = time.monotonic()
        if self.pending and now - self.pending_since > self.args.session_timeout_ms / 1000.0:
            self.pending = False
            if self.peer:
                self.peer = None
            self.session_id = 0
            self.ctx = None
        if self.authenticated and now - self.last_rx > self.args.session_timeout_ms / 1000.0:
            self.send_event(EVT_SESSION_EXPIRED, 1, "session expired")
            self.stats["sessions_expired"] += 1
            self.reset_session(keep_estop=True)
            self.next_telem = 0.0
        if self.armed and now - self.last_valid_ctrl > self.args.watchdog_ms / 1000.0:
            self.armed = False
            self.watchdog_fired = True
            self.stats["watchdog"] += 1
            self.axes = [0.0] * len(self.channels)
            self.send_event(EVT_WATCHDOG, 1, "watchdog: zero speed")
        if self.authenticated:
            if now >= self.next_telem:
                self.next_telem = now + 0.05
                self.send_telem()
            if now >= self.next_model and not self.args.stale_state:
                self.next_model = now + 1.0 / 30.0
                self.send_model()
            if now >= self.next_video and not self.args.no_camera:
                self.next_video = now + 1.0 / max(1, self.video_fps)
                self.send_video()
        if self.args.stats_file and now >= self.next_flush:
            self.next_flush = now + 0.5
            self.write_stats()

    # ---------- main ----------

    def run(self) -> None:
        print(f"[server] ctrl={self.args.bind}:{self.args.ctrl_port} "
              f"discovery={self.args.discovery_port} caps_hash=0x{self.caps_hash:08x}",
              flush=True)
        self.write_stats()
        try:
            while True:
                readable, _, _ = select.select([self.sock, self.disc], [], [], 0.002)
                if self.sock in readable:
                    while True:
                        try:
                            data, addr = self.sock.recvfrom(4096)
                        except BlockingIOError:
                            break
                        self.handle_datagram(data, addr)
                if self.disc in readable:
                    self.handle_discovery()
                self.loop_timers()
        except KeyboardInterrupt:
            pass
        finally:
            self.write_stats()
            print("[server] bye", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--ctrl-port", type=int, default=47800)
    parser.add_argument("--discovery-port", type=int, default=47810)
    parser.add_argument("--web-port", type=int, default=47880)
    parser.add_argument("--capability", default=str(ROOT / "protocol" / "examples" / "capability.mock_quadruped.json"))
    parser.add_argument("--secret-file", default=None)
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--stale-state", action="store_true")
    parser.add_argument("--drop", type=float, default=0.0)
    parser.add_argument("--hold-next-ms", type=int, default=0)
    parser.add_argument("--corrupt-aead", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--stats-file", default=None)
    parser.add_argument("--watchdog-ms", type=int, default=300)
    parser.add_argument("--ctrl-ttl-ms", type=int, default=200)
    parser.add_argument("--session-timeout-ms", type=int, default=5000)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    ReferenceServer(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
