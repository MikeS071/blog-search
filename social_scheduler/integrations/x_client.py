from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

from social_scheduler.core.token_vault import TokenVault


class XClient:
    def __init__(self, vault: TokenVault | None = None) -> None:
        self.client_id = os.getenv("X_CLIENT_ID")
        self.client_secret = os.getenv("X_CLIENT_SECRET")
        self.publish_url = os.getenv("X_PUBLISH_URL")
        self.verify_url = os.getenv("X_VERIFY_URL")
        self.vault = vault

    def publish_article(
        self,
        content: str,
        dry_run: bool = True,
        idempotency_key: str | None = None,
    ) -> str:
        if dry_run:
            return f"x_dry_{uuid.uuid4().hex[:10]}"
        if not self.client_id or not self.client_secret:
            raise RuntimeError("X app credentials not configured")
        if not self.publish_url:
            raise RuntimeError("X_PUBLISH_URL not configured")
        access_token = self.vault.get_token("x_access_token") if self.vault else None
        if not access_token:
            raise RuntimeError("X access token missing from encrypted vault")
        headers = {"Authorization": f"Bearer {access_token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        payload = {"content": content}
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(self.publish_url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"X publish failed: status={resp.status_code}")
        data = self._safe_json(resp)
        external_id = str(data.get("external_post_id") or data.get("id") or "").strip()
        if not external_id:
            raise RuntimeError("X publish response missing external post id")
        return external_id

    def verify_publish(self, post_id: str) -> str | None:
        """
        Resolve ambiguous publish outcomes by checking whether a post already exists.
        Returns the external post id when confirmed, otherwise None.
        """
        if not self.verify_url:
            return None
        access_token = self.vault.get_token("x_access_token") if self.vault else None
        if not access_token:
            return None
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(self.verify_url, params={"post_id": post_id}, headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        data = self._safe_json(resp)
        posted = bool(data.get("posted", True))
        if not posted:
            return None
        external_id = str(data.get("external_post_id") or data.get("id") or "").strip()
        return external_id or None

    def _safe_json(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError("X API returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("X API returned invalid JSON payload")
        return payload
