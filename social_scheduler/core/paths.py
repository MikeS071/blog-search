from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("SOCIAL_SCHEDULER_ROOT", Path.cwd() / ".social_scheduler"))
DATA_DIR = DATA_ROOT / "data"
LOG_DIR = DATA_ROOT / "logs"
SECRETS_DIR = DATA_ROOT / "secrets"
TOKENS_FILE = SECRETS_DIR / "tokens.enc"

CAMPAIGNS_FILE = DATA_DIR / "campaigns.jsonl"
POSTS_FILE = DATA_DIR / "posts.jsonl"
ATTEMPTS_FILE = DATA_DIR / "post_attempts.jsonl"
RULES_FILE = DATA_DIR / "approval_rules.jsonl"
TELEGRAM_AUDIT_FILE = DATA_DIR / "telegram_decision_audit.jsonl"
TELEGRAM_RATE_LIMIT_FILE = DATA_DIR / "telegram_rate_limit_events.jsonl"
HEALTH_FILE = DATA_DIR / "health_checks.jsonl"
MANUAL_OVERRIDE_FILE = DATA_DIR / "manual_override_audit.jsonl"
SYSTEM_CONTROLS_FILE = DATA_DIR / "system_controls.jsonl"
TELEGRAM_DECISIONS_FILE = DATA_DIR / "telegram_decisions.jsonl"
CONFIRM_TOKENS_FILE = DATA_DIR / "confirmation_tokens.jsonl"

ALL_FILES = [
    CAMPAIGNS_FILE,
    POSTS_FILE,
    ATTEMPTS_FILE,
    RULES_FILE,
    TELEGRAM_AUDIT_FILE,
    TELEGRAM_RATE_LIMIT_FILE,
    HEALTH_FILE,
    MANUAL_OVERRIDE_FILE,
    SYSTEM_CONTROLS_FILE,
    TELEGRAM_DECISIONS_FILE,
    CONFIRM_TOKENS_FILE,
]


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    for file_path in ALL_FILES:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch(exist_ok=True)
