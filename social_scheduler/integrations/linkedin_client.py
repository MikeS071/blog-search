from __future__ import annotations

import os
import uuid

from social_scheduler.core.token_vault import TokenVault


class LinkedInClient:
    def __init__(self, vault: TokenVault | None = None) -> None:
        self.client_id = os.getenv("LINKEDIN_CLIENT_ID")
        self.client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
        self.vault = vault

    def publish_article(self, content: str, dry_run: bool = True) -> str:
        if dry_run:
            return f"li_dry_{uuid.uuid4().hex[:10]}"
        if not self.client_id or not self.client_secret:
            raise RuntimeError("LinkedIn app credentials not configured")
        access_token = self.vault.get_token("linkedin_access_token") if self.vault else None
        if not access_token:
            raise RuntimeError("LinkedIn access token missing from encrypted vault")
        # Placeholder for real API call integration.
        return f"li_live_{uuid.uuid4().hex[:10]}"
