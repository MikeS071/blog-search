from __future__ import annotations

import re
from dataclasses import dataclass

from social_scheduler.core.models import SocialPost


@dataclass
class PreflightResult:
    ok: bool
    errors: list[str]


_MAX_LENGTH = {
    "linkedin": 120_000,
    "x": 25_000,
}


def validate_post(post: SocialPost, stage: str) -> PreflightResult:
    errors: list[str] = []
    content = post.content.strip()

    if not content:
        errors.append("content is empty")
        return PreflightResult(False, errors)

    if len(content) > _MAX_LENGTH.get(post.platform, 25_000):
        errors.append(f"content exceeds max length for {post.platform}")

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if len(lines) < 2:
        errors.append("content must include title and body")
    else:
        if len(lines[0]) < 5:
            errors.append("title line too short")
        body_words = len(" ".join(lines[1:]).split())
        if body_words < 20:
            errors.append("body too short")

    if re.search(r"\{\{[^}]+\}\}", content):
        errors.append("unresolved template placeholders detected")

    if stage == "pre_publish":
        if not post.approved_content_hash:
            errors.append("approved_content_hash missing")

    return PreflightResult(len(errors) == 0, errors)

