from __future__ import annotations

from social_scheduler.integrations.telegram_runtime import TelegramRuntime


def test_runtime_build_application_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    runtime = TelegramRuntime()
    try:
        runtime.build_application()
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "TELEGRAM_BOT_TOKEN" in str(exc)


def test_confirm_token_from_message_parses_token():
    msg = "Confirm override with /confirm tok_123"
    assert TelegramRuntime._confirm_token_from_message(msg) == "tok_123"


def test_confirm_token_from_message_returns_none_when_absent():
    assert TelegramRuntime._confirm_token_from_message("Health=pass") is None
