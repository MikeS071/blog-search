from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from social_scheduler.core.token_vault import TokenVault


def test_token_vault_round_trip(tmp_path: Path, monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SOCIAL_ENCRYPTION_KEY", key)

    vault = TokenVault(file_path=tmp_path / "tokens.enc")
    vault.set_token("linkedin_access_token", "abc")
    assert vault.get_token("linkedin_access_token") == "abc"

    names = vault.list_tokens()
    assert names == ["linkedin_access_token"]

    assert vault.delete_token("linkedin_access_token")
    assert vault.get_token("linkedin_access_token") is None
