from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

from social_scheduler.core.paths import TOKENS_FILE


class TokenVault:
    """Encrypted local token storage using Fernet.

    Requires `SOCIAL_ENCRYPTION_KEY` env var (URL-safe base64-encoded 32-byte key).
    """

    def __init__(self, file_path: Path | None = None):
        self.file_path = file_path or TOKENS_FILE
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.fernet = Fernet(self._load_key())

    def set_token(self, name: str, value: str) -> None:
        data = self._read_all()
        data[name] = value
        self._write_all(data)

    def get_token(self, name: str) -> str | None:
        return self._read_all().get(name)

    def delete_token(self, name: str) -> bool:
        data = self._read_all()
        if name not in data:
            return False
        del data[name]
        self._write_all(data)
        return True

    def list_tokens(self) -> list[str]:
        return sorted(self._read_all().keys())

    def _read_all(self) -> dict[str, str]:
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            return {}
        ciphertext = self.file_path.read_bytes()
        plaintext = self.fernet.decrypt(ciphertext)
        data = json.loads(plaintext.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Token vault content is invalid")
        return {str(k): str(v) for k, v in data.items()}

    def _write_all(self, data: dict[str, str]) -> None:
        payload = json.dumps(data, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ciphertext = self.fernet.encrypt(payload)
        self.file_path.write_bytes(ciphertext)

    @staticmethod
    def _load_key() -> bytes:
        key = os.getenv("SOCIAL_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("Missing SOCIAL_ENCRYPTION_KEY environment variable")

        # Validate key format without exposing internals.
        try:
            raw = key.encode("utf-8")
            decoded = base64.urlsafe_b64decode(raw)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("SOCIAL_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if len(decoded) != 32:
            raise RuntimeError("SOCIAL_ENCRYPTION_KEY must decode to 32 bytes")
        return raw
