# Copyright (c) 2026-2027 zbc
"""URC 参考服务端（Python），用于 App/CTS 联调。

内容：
    实现发现、配对、HELLO/AUTH、会话、CTRL、TELEM、ESTOP、看门狗、
    CAPS 分片、MODEL_STATE、测试图 VIDEO 与故障注入；便于无机器人时开发与验收。
    这不是生产实现，仅用于协议验证。

用法：
    python tools/codec_ref/ref_server.py --capability protocol/examples/capability.mock_quadruped.json
    python tools/codec_ref/ref_server.py --secret-file /tmp/urc.secret --no-camera
"""

from __future__ import annotations

import argparse
import json
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

# 事件/错误码
EVENT_ESTOP_ACKED = 0x0001
EVENT_WATCHDOG = 0x0002
EVENT_ARMED = 0x0003
ERR_AUTH = 0x0101
ERR_SESSION = 0x0102
ERR_ROLE = 0x0103
ERR_RANGE = 0x0301
ERR_ESTOP = 0x0302
ERR_LOCKED = 0x0602

# SESSION_CTRL 动作
ACT_CLAIM = 0
ACT_RELEASE = 1
ACT_VIEWER = 2
ACT_ARM = 3
ACT_RELEASE_ESTOP = 4


def now_us() -> int:
    return time.monotonic_ns() // 1000


class ReferenceServer:
    def __init__(self, args):
        self.args = args
        self.cap = json.loads(Path(args.capability).read_text(encoding="utf-8"))
        self.cap_bytes = canonical_json(self.cap)
        self.caps_hash = caps_hash(self.cap)
        self.joint_order = (self.cap.get("model") or {}).get("joint_order") or []
        self.joint_hash = joint_order_hash(self.joint_order) if self.joint_order else 0
        self.channels = self.cap["control"]["modes"][0].get("channels", [])
        self.mode_ids = [m["id"] for m in self.cap["control"]["modes"]]

        self.secret = self._load_secret(args)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((args.bind, args.ctrl_port))
        self.sock.setblocking(False)
        self.disc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.disc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.disc.bind((args.bind, args.discovery_port))
        self.disc.setblocking(False)

        # 会话状态
        self.session_id = 0
        self.app_nonce = b""
        self.robot_nonce = os.urandom(16)
        self.ctx = None
        self.authenticated = False
        self.claimed = False
        self.peer = None
        self.tx_seq = 0
        self.client_replay = crypto.ReplayWindow(2048)
        self.auth_failures = 0
        self.locked_until = 0.0

        # 控制状态
        self.axis_values = [0.0] * len(self.channels)
        self.buttons = [0, 0]
        self.last_ctrl = 0.0
        self.armed = False
        self.estop_latched = False
        self.watchdog_fired = False

        # 定时器
        self.next_telem = 0.0
        self.next_model = 0.0
        self.next_video = 0.0
        self.video_frame_id = 0
        self.model_seq = 0
        self.telem_seq = 0
        self.dropped = 0
        self.replayed = 0
        self.rejected = 0

    def _load_secret(self, args) -> bytes:
        if args.secret_file and Path(args.secret_file).exists():
            raw = Path(args.secret_file).read_bytes()
            if len(raw) == 32:
                print(f"[server] loaded secret from {args.secret_file}", flush=True)
                return raw
        secret = os.urandom(32)
        if args.secret_file:
            Path(args.secret_file).parent.mkdir(parents=True, exist_ok=True)
            Path(args.secret_file).write_bytes(secret)
        import base64
        print(f"URCPAIR:{base64.b64encode(secret).decode()}", flush=True)
        return secret

    # ---------- send ----------

    def send(self, ftype: int, payload: bytes, flags: int = 0, stream: int = frame.S_CTRL,
             addr=None, encrypt: bool = True) -> None:
        target = addr or self.peer
        if target is None:
            return
        self.tx_seq += 1
        f = frame.Frame(ftype, payload, flags=flags, stream=stream,
                        session_id=self.session_id, seq=self.tx_seq, ts_us=now_us())
        use_ctx = self.ctx if (encrypt and self.ctx) else None
        try:
            raw = frame.pack(f, use_ctx, to_robot=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[server] pack error: {exc}", flush=True)
            return
        if self.args.drop and random.random() * 100 < self.args.drop:
            self.dropped += 1
            return
        if self.args.corrupt and random.random() * 100 < self.args.corrupt:
            raw = bytes([raw[0] ^ 0xFF]) + raw[1:]
        self.sock.sendto(raw, target)

    def send_error(self, code: int, message: str, addr=None) -> None:
        self.send(frame.T_ERROR, messages.pack_error(code, message), addr=addr, encrypt=False)

    def send_event(self, code: int, level: int, message: str) -> None:
        self.send(frame.T_EVENT, messages.pack_event(code, level, message))

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
            ann = messages.Announce(
                self.cap["robot_id"], self.cap.get("name", "robot"), self.cap["form"],
                self.args.ctrl_port, self.args.video_port, self.args.depth_port,
                self.args.map_port, self.args.web_port, self.caps_hash,
                1 if self.authenticated else 0)
            self.disc.sendto(messages.pack_announce(ann), addr)

    # ---------- recv ----------

    def handle_ctrl_socket(self) -> None:
        while True:
            try:
                data, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                return
            try:
                from_robot = False
                # 先用无会话解包；加密帧需要 ctx
                try:
                    f = frame.unpack(data, from_robot=False)
                except ValueError:
                    if self.ctx is None:
                        raise
                    f = frame.unpack(data, self.ctx, from_robot=False)
                if f.encrypted:
                    if self.ctx is None or f.session_id != self.session_id:
                        continue
                    if not self.client_replay.accept(f.seq):
                        self.replayed += 1
                        continue
                self.dispatch(f, addr)
            except Exception as exc:  # noqa: BLE001
                self.rejected += 1
                if self.args.verbose:
                    print(f"[server] drop packet: {exc}", flush=True)

    def dispatch(self, f: frame.Frame, addr) -> None:
        handlers = {
            frame.T_HELLO: self.on_hello,
            frame.T_AUTH: self.on_auth,
            frame.T_SESSION_CTRL: self.on_session_ctrl,
            frame.T_CTRL: self.on_ctrl,
            frame.T_ESTOP: self.on_estop,
            frame.T_PING: self.on_ping,
            frame.T_FEEDBACK: self.on_feedback,
        }
        handler = handlers.get(f.type)
        if handler:
            handler(f, addr)

    def on_hello(self, f: frame.Frame, addr) -> None:
        if self.claimed and self.peer != addr:
            self.send_error(ERR_ROLE, "controller occupied", addr=addr)
            return
        hello = messages.unpack_hello(f.payload)
        self.session_id = struct.unpack("<I", os.urandom(4))[0]
        self.app_nonce = hello["app_nonce"]
        self.robot_nonce = os.urandom(16)
        self.ctx = crypto.CryptoContext(self.secret, self.app_nonce, self.robot_nonce)
        self.authenticated = False
        self.claimed = False
        self.client_replay = crypto.ReplayWindow(2048)
        ack = messages.HelloAck(1, 0, self.session_id, self.cap["robot_id"],
                                self.cap.get("name", "robot"), self.cap["form"],
                                self.robot_nonce, self.caps_hash,
                                self.args.ctrl_port, self.args.video_port, self.args.depth_port,
                                self.args.map_port, self.args.web_port, 1)
        self.send(frame.T_HELLO_ACK, messages.pack_hello_ack(ack), addr=addr, encrypt=False)

    def on_auth(self, f: frame.Frame, addr) -> None:
        now = time.monotonic()
        if now < self.locked_until:
            self.send_error(ERR_LOCKED, "auth locked", addr=addr)
            return
        auth = messages.unpack_auth(f.payload)
        if not self.app_nonce or f.session_id != self.session_id:
            self.send_error(ERR_SESSION, "no pending session", addr=addr)
            return
        want = crypto.auth_proof(self.secret, self.app_nonce, self.robot_nonce, self.session_id)
        if auth["proof"] != want:
            self.auth_failures += 1
            self.send_error(ERR_AUTH, "auth failed", addr=addr)
            if self.auth_failures >= 5:
                self.locked_until = now + 30
            return
        self.authenticated = True
        self.peer = addr
        self.auth_failures = 0
        self.send(frame.T_AUTH_OK, messages.pack_auth_ok(0, self.ctx.key_confirm, now_us()),
                  addr=addr, encrypt=False)

    def on_session_ctrl(self, f: frame.Frame, addr) -> None:
        action = messages.unpack_session_ctrl(f.payload)["action"]
        if action == ACT_CLAIM:
            if self.claimed and self.peer != addr:
                self.send_error(ERR_ROLE, "controller occupied")
                return
            self.claimed = True
            self.peer = addr
            self.last_ctrl = time.monotonic()
            self.send_caps()
            if not self.armed:
                self.armed = True
                self.send_event(EVENT_ARMED, 0, "armed")
        elif action == ACT_RELEASE:
            self.claimed = False
            self.armed = False
        elif action == ACT_VIEWER:
            self.send_error(ERR_ROLE, "viewer not implemented")
        elif action == ACT_ARM:
            self.armed = True
            self.watchdog_fired = False
            self.last_ctrl = time.monotonic()
            self.send_event(EVENT_ARMED, 0, "armed")
        elif action == ACT_RELEASE_ESTOP:
            self.estop_latched = False
            self.armed = True
            self.watchdog_fired = False
            self.last_ctrl = time.monotonic()
            self.send_event(EVENT_ARMED, 0, "estop released")

    def on_ctrl(self, f: frame.Frame, addr) -> None:
        if not self.claimed or self.peer != addr:
            self.rejected += 1
            return
        if self.estop_latched:
            self.rejected += 1
            return
        ctrl = messages.unpack_ctrl(f.payload)
        if ctrl["mode"] not in self.mode_ids:
            self.send_error(ERR_RANGE, "bad mode")
            return
        if len(ctrl["axes"]) != len(self.channels):
            self.send_error(ERR_RANGE, "bad axis count")
            return
        if not (ctrl["flags"] & 0x01):  # 死手未按下
            self.axis_values = [0.0] * len(self.channels)
            self.last_ctrl = time.monotonic()
            return
        values = []
        for v, ch in zip(ctrl["axes"], self.channels):
            lo, hi = ch["range"]
            scale = abs(lo) if abs(lo) > abs(hi) else abs(hi)
            physical = v / 32767.0 * scale if scale else 0.0
            if physical < lo - 1e-3 or physical > hi + 1e-3:
                self.send_error(ERR_RANGE, f"axis {ch['id']} out of range")
                self.rejected += 1
                return
            values.append(physical)
        self.axis_values = values
        self.buttons = ctrl["buttons"]
        self.last_ctrl = time.monotonic()
        self.watchdog_fired = False
        self.armed = True

    def on_estop(self, f: frame.Frame, addr) -> None:
        estop = messages.unpack_estop(f.payload)
        if estop["reason"] == 0:
            self.estop_latched = False
            self.armed = False
            return
        self.estop_latched = True
        self.axis_values = [0.0] * len(self.channels)
        self.armed = False
        self.send_event(EVENT_ESTOP_ACKED, 0, "estop acked")

    def on_ping(self, f: frame.Frame, addr) -> None:
        echo = struct.unpack("<Q", f.payload)[0]
        self.send(frame.T_PONG, struct.pack("<Q", echo))

    def on_feedback(self, f: frame.Frame, addr) -> None:
        pass

    # ---------- periodic ----------

    def send_caps(self) -> None:
        payload = messages.pack_caps(self.cap_bytes)
        parts = frag.fragment(payload, 1190, 0x1000)
        for idx, part in enumerate(parts):
            flags = frame.F_LAST_FRAG if idx == len(parts) - 1 else 0
            self.send(frame.T_CAPS, part, flags=flags)

    def loop_timers(self) -> None:
        now = time.monotonic()
        if self.watchdog_fired is False and self.claimed and self.armed and (now - self.last_ctrl) > 0.3:
            self.watchdog_fired = True
            self.armed = False
            self.axis_values = [0.0] * len(self.channels)
            self.send_event(EVENT_WATCHDOG, 1, "watchdog: zero speed")
        if self.authenticated:
            if now >= self.next_telem:
                self.next_telem = now + 0.05
                self.send_telem()
            if now >= self.next_model and not self.args.stale_state:
                self.next_model = now + 1.0 / 30.0
                self.send_model()
            if now >= self.next_video and not self.args.no_camera:
                self.next_video = now + 0.1
                self.send_video()
        else:
            self.next_telem = now

    def send_telem(self) -> None:
        self.telem_seq += 1
        axes = self.axis_values
        fault = (1 if self.watchdog_fired else 0) | (2 if self.estop_latched else 0)
        t = messages.Telemetry(
            seq=self.telem_seq, ts_us=now_us(), fsm_state=1 if self.armed else 0,
            fault_flags=fault, battery_pct=88,
            x=axes[0] if len(axes) > 0 else 0.0,
            y=axes[1] if len(axes) > 1 else 0.0,
            yaw=axes[2] if len(axes) > 2 else 0.0,
            policy_name="mock", remote_age_ms=int((time.monotonic() - self.last_ctrl) * 1000) if self.last_ctrl else 9999,
            queue_depth=0, link_rtt_us=0, link_loss_pct=0, map_revision=0)
        self.send(frame.T_TELEM, messages.pack_telem(t), stream=frame.S_TELEMETRY)

    def send_model(self) -> None:
        self.model_seq += 1
        count = len(self.joint_order)
        if count == 0:
            return
        t = time.monotonic()
        pos = [0.2 * __import__("math").sin(t * 2 + i) for i in range(count)]
        state = messages.pack_model_state(
            self.model_seq, now_us(), self.joint_hash, count, 0, 0,
            (0.0, 0.0, 0.3), (1.0, 0.0, 0.0, 0.0), pos)
        self.send(frame.T_MODEL_STATE, state, stream=frame.S_TELEMETRY)

    def send_video(self) -> None:
        w, h = 160, 120
        # 简单渐变图：RGB888
        data = bytearray(w * h * 3)
        for y in range(h):
            for x in range(w):
                o = (y * w + x) * 3
                data[o] = (x * 255 // w) & 0xFF
                data[o + 1] = (y * 255 // h) & 0xFF
                data[o + 2] = 128
        self.video_frame_id += 1
        fid = self.video_frame_id
        chunk = 1190 - 23
        total = len(data)
        count = (total + chunk - 1) // chunk
        ts = now_us()
        for idx in range(count):
            part = bytes(data[idx * chunk:(idx + 1) * chunk])
            media_flags = 0x01 | (0x04 if idx == count - 1 else 0)
            payload = messages.pack_video(fid, ts, total, idx, count, 0, media_flags, part)
            self.send(frame.T_VIDEO, payload, flags=frame.F_KEYFRAME, stream=frame.S_VIDEO)

    # ---------- main ----------

    def run(self) -> None:
        print(f"[server] control={self.args.bind}:{self.args.ctrl_port} "
              f"discovery={self.args.discovery_port} caps_hash=0x{self.caps_hash:08x}", flush=True)
        while True:
            try:
                readable, _, _ = select.select([self.sock, self.disc], [], [], 0.002)
                if self.sock in readable:
                    self.handle_ctrl_socket()
                if self.disc in readable:
                    self.handle_discovery()
                self.loop_timers()
            except KeyboardInterrupt:
                print("[server] bye", flush=True)
                return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--ctrl-port", type=int, default=47800)
    parser.add_argument("--discovery-port", type=int, default=47810)
    parser.add_argument("--video-port", type=int, default=47801)
    parser.add_argument("--depth-port", type=int, default=47802)
    parser.add_argument("--map-port", type=int, default=47803)
    parser.add_argument("--web-port", type=int, default=47880)
    parser.add_argument("--capability", default=str(ROOT / "protocol" / "examples" / "capability.mock_quadruped.json"))
    parser.add_argument("--secret-file", default=None)
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--stale-state", action="store_true")
    parser.add_argument("--drop", type=int, default=0)
    parser.add_argument("--delay", type=int, default=0)
    parser.add_argument("--corrupt", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    ReferenceServer(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
