import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SecureBlob:
    salt: bytes
    nonce: bytes
    ciphertext: bytes
    mac: bytes


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out += block
        counter += 1
    return out[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


class SecureTokenStore:
    def __init__(self, path: Path, passphrase: str) -> None:
        self.path = path
        self.passphrase = passphrase.encode("utf-8")

    def _derive(self, salt: bytes) -> tuple[bytes, bytes]:
        key_material = hashlib.pbkdf2_hmac("sha256", self.passphrase, salt, 200_000, dklen=64)
        return key_material[:32], key_material[32:]

    def save_token(self, token: str) -> None:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(16)
        enc_key, mac_key = self._derive(salt)

        raw = token.encode("utf-8")
        stream = _keystream(enc_key, nonce, len(raw))
        ciphertext = _xor(raw, stream)
        mac = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()

        payload = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "mac": base64.b64encode(mac).decode("ascii"),
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload))
        os.chmod(self.path, 0o600)

    def load_token(self) -> str | None:
        if not self.path.exists():
            return None

        payload = json.loads(self.path.read_text())
        blob = SecureBlob(
            salt=base64.b64decode(payload["salt"]),
            nonce=base64.b64decode(payload["nonce"]),
            ciphertext=base64.b64decode(payload["ciphertext"]),
            mac=base64.b64decode(payload["mac"]),
        )

        enc_key, mac_key = self._derive(blob.salt)
        expected = hmac.new(mac_key, blob.salt + blob.nonce + blob.ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, blob.mac):
            raise RuntimeError("Token store integrity verification failed")

        stream = _keystream(enc_key, blob.nonce, len(blob.ciphertext))
        return _xor(blob.ciphertext, stream).decode("utf-8")
