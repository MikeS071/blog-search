from __future__ import annotations

import os
import uuid

from social_scheduler.core.token_vault import TokenVault


class XClient:
    def __init__(self, vault: TokenVault | None = None) -> None:
        self.client_id = os.getenv("X_CLIENT_ID")
        self.client_secret = os.getenv("X_CLIENT_SECRET")
        self.vault = vault

    def publish_article(self, content: str, dry_run: bool = True) -> str:
        if dry_run:
            return f"x_dry_{uuid.uuid4().hex[:10]}"
        if not self.client_id or not self.client_secret:
            raise RuntimeError("X app credentials not configured")
        access_token = self.vault.get_token("x_access_token") if self.vault else None
        if not access_token:
            raise RuntimeError("X access token missing from encrypted vault")
        # Placeholder for real API call integration.
        return f"x_live_{uuid.uuid4().hex[:10]}"
