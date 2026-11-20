# Copyright (c) 2026-2027 zbc
"""CTS 用 URC 客户端。

内容：
    HELLO/AUTH/claim/arm、加密收发、CAPS 重组、TELEM/MODEL/VIDEO 解析、
    Agent→App 序号单调性跟踪、错误帧处理与原始帧发送（重放/篡改用例）。
"""

from __future__ import annotations

import json
import os
import socket
import struct
import time

from urc_ref import crypto, frame, frag, messages

DEFAULT_APP_ID = b"cts-client-00001"


class UrcError(RuntimeError):
    def __init__(self, code: int, message: str = ""):
        super().__init__(f"urc error 0x{code:04x}: {message}")
        self.code = code


class UrcClient:
    def __init__(self, secret: bytes, server: tuple[str, int], app_id: bytes = DEFAULT_APP_ID):
        self.secret = secret
        self.server = server
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.5)
        self.app_id = app_id
        self.app_nonce = os.urandom(16)
        self.session_id = 0
        self.robot_nonce = None
        self.ctx = None
        self.tx_seq = 0
        self.caps = None
        self.last_error = None
        self.last_agent_seq = None
        self.agent_seq_ok = True

    # ---------- low level ----------

    def _send(self, ftype: int, payload: bytes, flags: int = 0, stream: int = frame.S_CTRL,
              encrypt: bool | None = None, session_id: int | None = None, seq: int | None = None) -> None:
        if encrypt is None:
            encrypt = self.ctx is not None
        if seq is None:
            self.tx_seq = (self.tx_seq + 1) & 0xFFFFFFFF
            seq = self.tx_seq
        f = frame.Frame(ftype, payload, flags=flags, stream=stream,
                        session_id=session_id if session_id is not None else self.session_id,
                        seq=seq, ts_us=time.monotonic_ns() // 1000)
        self.sock.sendto(frame.pack(f, self.ctx if encrypt else None, to_robot=True), self.server)

    def send_raw(self, raw: bytes) -> None:
        self.sock.sendto(raw, self.server)

    def recv(self, timeout: float = 0.5) -> frame.Frame | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.sock.settimeout(max(0.01, end - time.monotonic()))
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                return None
            except ConnectionResetError:
                # Windows UDP 在服务端端口关闭/重置时会报 10054；视作无数据继续等
                time.sleep(0.005)
                continue
            except OSError:
                return None
            try:
                use_ctx = self.ctx if (len(data) > 6 and data[6] & frame.F_ENCRYPTED) else None
                f = frame.unpack(data, use_ctx, from_robot=True)
            except Exception:  # noqa: BLE001
                continue
            # Agent→App 全局 seq 单调性（同方向跨流）
            if self.last_agent_seq is not None:
                diff = ((f.seq - self.last_agent_seq + 0x80000000) & 0xFFFFFFFF) - 0x80000000
                if diff <= 0:
                    self.agent_seq_ok = False
            self.last_agent_seq = f.seq
            if f.type == frame.T_ERROR:
                err = messages.unpack_error(f.payload)
                self.last_error = err
                raise UrcError(err["code"], err["message"])
            return f
        return None

    def recv_type(self, ftype: int, timeout: float = 2.0) -> frame.Frame:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            f = self.recv(timeout=end - time.monotonic())
            if f is None:
                break
            if f.type == ftype:
                return f
        raise TimeoutError(f"timeout waiting type 0x{ftype:02x}")

    # ---------- handshake ----------

    def hello(self) -> messages.HelloAck:
        hello = messages.pack_hello(1, 0, 0, 0, self.app_id, self.app_nonce, "cts/0.2")
        self._send(frame.T_HELLO, hello, encrypt=False, session_id=0)
        f = self.recv_type(frame.T_HELLO_ACK)
        ack = messages.unpack_hello_ack(f.payload)
        self.session_id = ack.session_id
        self.robot_nonce = ack.robot_nonce
        self.ctx = crypto.CryptoContext(self.secret, self.app_nonce, self.robot_nonce)
        return ack

    def auth(self) -> dict:
        proof = crypto.auth_proof(self.secret, self.app_nonce, self.robot_nonce, self.session_id)
        auth = messages.pack_auth(proof, b"cts-client-00001", "cts")
        self._send(frame.T_AUTH, auth, encrypt=False)
        f = self.recv_type(frame.T_AUTH_OK)
        return messages.unpack_auth_ok(f.payload)

    def claim(self) -> dict:
        self._send(frame.T_SESSION_CTRL, messages.pack_session_ctrl(0))
        self.caps = self.read_caps()
        return self.caps

    def arm(self) -> None:
        self._send(frame.T_SESSION_CTRL, messages.pack_session_ctrl(3))

    def release_estop(self) -> None:
        self._send(frame.T_SESSION_CTRL, messages.pack_session_ctrl(4))

    def connect(self) -> messages.HelloAck:
        ack = self.hello()
        self.auth()
        self.claim()
        self.arm()
        return ack

    def read_caps(self, timeout: float = 3.0) -> dict:
        reassembler = frag.Reassembler()
        end = time.monotonic() + timeout
        raw = None
        while time.monotonic() < end:
            f = self.recv(timeout=end - time.monotonic())
            if f is None:
                break
            if f.type == frame.T_CAPS:
                raw = reassembler.add(f.payload)
                if raw is not None:
                    break
        if raw is None:
            raise TimeoutError("caps not received")
        return json.loads(messages.unpack_caps(raw)["raw"].decode("utf-8"))

    # ---------- send ----------

    def send_ctrl(self, axes: list[int], buttons: list[int] | None = None, mode: int = 0,
                  flags: int = 1) -> None:
        self._send(frame.T_CTRL, messages.pack_ctrl(mode, axes, buttons or [0], flags))

    def send_feedback(self, flags: int = 0) -> None:
        payload = messages.pack_feedback(0, 0, 0, 0, 0, 0, 0, 0, 0, flags)
        self._send(frame.T_FEEDBACK, payload, stream=frame.S_FEEDBACK)

    def send_estop(self, reason: int = 1, ack: bool = True) -> None:
        self._send(frame.T_ESTOP, messages.pack_estop(reason, time.monotonic_ns() // 1000),
                   flags=frame.F_ACK_REQ if ack else 0)

    def send_ping(self) -> int:
        ts = time.monotonic_ns() // 1000
        self._send(frame.T_PING, struct.pack("<Q", ts))
        f = self.recv_type(frame.T_PONG)
        return struct.unpack("<Q", f.payload)[0]

    def close(self) -> None:
        self.sock.close()


class VideoAssembler:
    """按 frame_id 重组 VIDEO 分片（视频头自带 pkt_idx/pkt_cnt）。"""

    def __init__(self):
        self.frames: dict[int, dict] = {}

    def add(self, payload: bytes) -> tuple[dict, bytes] | None:
        v = messages.unpack_video(payload)
        slot = self.frames.setdefault(v["frame_id"], {"cnt": v["pkt_cnt"], "parts": {}, "meta": v})
        slot["parts"][v["pkt_idx"]] = v["data"]
        slot["meta"] = v
        if len(slot["parts"]) == slot["cnt"]:
            data = b"".join(slot["parts"][i] for i in range(slot["cnt"]))
            meta = slot["meta"]
            self.frames.pop(v["frame_id"], None)
            return meta, data
        return None
