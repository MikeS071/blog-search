from social_scheduler.core.redaction import redact_secrets


def test_redact_bearer_and_token_pairs():
    text = "Authorization: Bearer abc123 token=xyz refresh_token: rrr"
    out = redact_secrets(text)
    assert out is not None
    assert "abc123" not in out
    assert "xyz" not in out
    assert "rrr" not in out
    assert "[REDACTED]" in out

