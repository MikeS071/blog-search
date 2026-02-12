# Pre-Implementation Checklist: Social Scheduler

Planning artifact only. No implementation has started.

## 1. Build Start Gate

All items must be `DONE` before coding:

- [x] PRD approved decisions finalized (`PRD - Automated Social Scheduling and Posting.md`)
- [x] Technical stack choices finalized
- [x] Telegram-first control model finalized
- [x] Safety model finalized (kill-switch, health gate, override, retries)
- [ ] Implementation start approval explicitly granted for Phase 1

## 2. Approved Stack (Locked)

- Language/runtime: `Python 3.10+`
- CLI: `Typer`
- Telegram: `python-telegram-bot`
- HTTP client: `httpx`
- Validation: `pydantic`
- Encryption: `cryptography`
- Storage: JSONL append + compaction (`filelock` for write safety)
- Tests: `pytest`, `pytest-mock`, `respx`, `freezegun`

## 3. Dependency Plan (Add to `pyproject.toml` on implementation start)

Production dependencies:

- `typer`
- `python-telegram-bot`
- `httpx`
- `pydantic`
- `cryptography`
- `filelock`

Dev/test dependencies:

- `pytest`
- `pytest-mock`
- `respx`
- `freezegun`

Note:

- Add minimum pinned versions during implementation for reproducibility.

## 4. Package Scaffold Plan (No Files Created Yet)

```text
social_scheduler/
  __init__.py
  cli/
    __init__.py
    app.py
  core/
    __init__.py
    models.py
    state_machine.py
    storage_jsonl.py
    hashing.py
    timing_engine.py
    approval_rules.py
  integrations/
    __init__.py
    linkedin_client.py
    x_client.py
    telegram_bot.py
  worker/
    __init__.py
    runner.py
    retry_policy.py
    kill_switch.py
    health_gate.py
  reports/
    __init__.py
    digest.py
tests/
  social_scheduler/
```

## 5. Config and Secrets Plan

Environment variables (planned):

- `SOCIAL_ENCRYPTION_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID`
- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REDIRECT_URI`
- `X_CLIENT_ID`
- `X_CLIENT_SECRET`
- `X_REDIRECT_URI`

Storage paths (planned):

- `.social_scheduler/` (runtime data root)
- `.social_scheduler/data/` (JSONL files)
- `.social_scheduler/secrets/` (encrypted token blob)
- `.social_scheduler/logs/` (structured logs)

## 6. JSONL Files to Define in Phase 1

- `campaigns.jsonl`
- `posts.jsonl`
- `post_attempts.jsonl`
- `approval_rules.jsonl`
- `telegram_decision_audit.jsonl`
- `telegram_rate_limit_events.jsonl`
- `health_checks.jsonl`
- `manual_override_audit.jsonl`
- `system_controls.jsonl`

## 7. Phase 1 Tickets (Execution-Ready)

### Ticket P1-1: Core Models and Schema Versioning

Acceptance criteria:

- Define pydantic models for all JSONL entities.
- Include `schema_version` in each record type.
- Add fixtures with valid and invalid records.

### Ticket P1-2: State Machine and Transition Guards

Acceptance criteria:

- Encode allowed transitions (`draft -> ready_for_approval -> approved -> scheduled -> posted|failed`).
- Reject illegal transitions with clear error reasons.
- Unit tests for all legal and illegal transitions.

### Ticket P1-3: JSONL Storage Engine

Acceptance criteria:

- Append-only writes with file lock.
- Safe read/query helpers by ID/status/date.
- Compaction command design documented and stubbed.

### Ticket P1-4: Deterministic Hash and Idempotency Key

Acceptance criteria:

- Canonical content hashing function implemented spec (not code yet).
- Idempotency key format fixed:
  - `campaign_id + platform + approved_content_hash`
- Unit tests for hash stability and key determinism.

### Ticket P1-5: Structured Logging Contract

Acceptance criteria:

- Define structured event schema (`event_id`, `event_type`, `campaign_id`, `post_id`, timestamps).
- Map key lifecycle events to log events.
- Redaction policy documented for secrets and tokens.

## 8. Release Gate Checklist Before Phase 2

- [ ] All Phase 1 tickets complete
- [ ] Unit tests green for state/storage/hash logic
- [ ] JSONL fixture validation pass
- [ ] Logging schema reviewed
- [ ] Design review sign-off

## 9. Open Clarifications Before Coding (Optional but Recommended)

1. Local timezone source of truth:
   - OS timezone or explicit config key?
2. Compaction trigger:
   - Manual command only or size/time threshold?
3. Log retention:
   - Keep indefinitely in v1 or rotate after N days?

## 10. Explicit Start Prompt

When ready to begin implementation, use:

`Start implementation Phase 1 only, following Pre-Implementation Checklist and PRD decisions.`
