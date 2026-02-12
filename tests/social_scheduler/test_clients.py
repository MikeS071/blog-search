from __future__ import annotations

import pytest

from social_scheduler.integrations.linkedin_client import LinkedInClient
from social_scheduler.integrations.x_client import XClient


class _Vault:
    def __init__(self, token_map: dict[str, str]):
        self.token_map = token_map

    def get_token(self, name: str) -> str | None:
        return self.token_map.get(name)


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_linkedin_publish_live_success(monkeypatch):
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "cid")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "sec")
    monkeypatch.setenv("LINKEDIN_PUBLISH_URL", "https://example.test/li/publish")

    class _Client:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, headers):
            assert "Idempotency-Key" in headers
            assert url.endswith("/publish")
            assert "content" in json
            return _Resp(200, {"id": "li_123"})

    monkeypatch.setattr("social_scheduler.integrations.linkedin_client.httpx.Client", _Client)
    client = LinkedInClient(vault=_Vault({"linkedin_access_token": "tok"}))
    assert client.publish_article("hello", dry_run=False, idempotency_key="k1") == "li_123"


def test_x_verify_publish_returns_none_on_404(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "cid")
    monkeypatch.setenv("X_CLIENT_SECRET", "sec")
    monkeypatch.setenv("X_VERIFY_URL", "https://example.test/x/verify")

    class _Client:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params, headers):
            assert params.get("post_id") == "p1"
            return _Resp(404, {"posted": False})

    monkeypatch.setattr("social_scheduler.integrations.x_client.httpx.Client", _Client)
    client = XClient(vault=_Vault({"x_access_token": "tok"}))
    assert client.verify_publish("p1") is None


def test_x_publish_raises_on_missing_external_id(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "cid")
    monkeypatch.setenv("X_CLIENT_SECRET", "sec")
    monkeypatch.setenv("X_PUBLISH_URL", "https://example.test/x/publish")

    class _Client:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, headers):
            return _Resp(200, {"posted": True})

    monkeypatch.setattr("social_scheduler.integrations.x_client.httpx.Client", _Client)
    client = XClient(vault=_Vault({"x_access_token": "tok"}))
    with pytest.raises(RuntimeError, match="missing external post id"):
        client.publish_article("hello", dry_run=False, idempotency_key="k1")
