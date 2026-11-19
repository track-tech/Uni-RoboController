# Copyright (c) 2026-2027 zbc
"""会话密钥派生、认证与 AES-256-GCM。

内容：
    HKDF-SHA256 方向子密钥、AUTH 证明、key_confirm、12 B nonce、AEAD 加解密。
    规范见 docs/02-transport.md §5 与 docs/03-protocol.md §4.3。
"""

from __future__ import annotations

import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AUTH_INFO = b"urc/auth/v1"
SESSION_PREFIX = b"urc/session/v1/"


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    out = b""
    t = b""
    counter = 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def derive_session(secret: bytes, app_nonce: bytes, robot_nonce: bytes) -> dict:
    """返回 PRK 与方向子密钥。"""
    if len(secret) != 32 or len(app_nonce) != 16 or len(robot_nonce) != 16:
        raise ValueError("bad input length")
    prk = hkdf_extract(app_nonce + robot_nonce, secret)
    app2robot = hkdf_expand(prk, SESSION_PREFIX + b"app2robot", 32)
    robot2app = hkdf_expand(prk, SESSION_PREFIX + b"robot2app", 32)
    confirm = hkdf_expand(prk, SESSION_PREFIX + b"confirm", 8)
    return {"prk": prk, "app2robot": app2robot, "robot2app": robot2app, "confirm": confirm}


def auth_proof(secret: bytes, app_nonce: bytes, robot_nonce: bytes, session_id: int) -> bytes:
    msg = AUTH_INFO + app_nonce + robot_nonce + struct.pack("<I", session_id)
    return hmac.new(secret, msg, hashlib.sha256).digest()


class CryptoContext:
    """与对端共享的会话加密上下文（一对方向密钥）。"""

    def __init__(self, secret: bytes, app_nonce: bytes, robot_nonce: bytes):
        keys = derive_session(secret, app_nonce, robot_nonce)
        self.app_nonce = app_nonce
        self.robot_nonce = robot_nonce
        self.app2robot_key = keys["app2robot"]
        self.robot2app_key = keys["robot2app"]
        self.key_confirm = keys["confirm"]

    @staticmethod
    def make_nonce(seq: int, to_robot: bool) -> bytes:
        return bytes([0x01 if to_robot else 0x02, 0, 0, 0]) + struct.pack("<Q", seq)

    @staticmethod
    def encrypt(key: bytes, nonce: bytes, aad: bytes, plaintext: bytes) -> bytes:
        return AESGCM(key).encrypt(nonce, plaintext, aad)

    @staticmethod
    def decrypt(key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)


if __name__ == "__main__":
    secret = bytes(range(32))
    an = bytes(range(16))
    rn = bytes(reversed(range(16)))
    ctx = CryptoContext(secret, an, rn)
    proof = auth_proof(secret, an, rn, 7)
    print("app2robot", ctx.app2robot_key.hex())
    print("proof", proof.hex())
