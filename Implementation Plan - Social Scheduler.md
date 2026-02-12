# Implementation Plan: Social Scheduler (Planning Only)

## 1. Scope

This plan operationalizes `PRD - Automated Social Scheduling and Posting.md` into executable work packages, effort estimates, and technical dependencies.

No implementation starts until explicit approval.

## 2. Recommended Tech Stack (V1)

Aligned with your existing repo (Python + `uv`):

- Runtime: `Python 3.10+`
- CLI: `Typer` (clean command UX, typed options)
- HTTP/API clients: `httpx`
- Data validation: `pydantic`
- Storage: JSONL + atomic writes + `filelock`
- Crypto: `cryptography` (`Fernet`/AES-based token encryption at rest)
- Telegram bot: `python-telegram-bot`
- Scheduler worker: in-process polling loop (`60s`) + graceful shutdown handlers
- Logging: structured JSON logging via stdlib `logging` + custom formatter
- Testing: `pytest` + `pytest-mock` + `respx` (HTTP mocks) + `freezegun` (time logic)

Why this stack:

- Minimal operational complexity for local-first deployment
- Deterministic behavior and testability
- Matches current project direction and avoids early infra overhead

## 3. Work Breakdown and Estimates

Estimates assume one engineer, focused execution.

### Phase 1: Foundations and Contracts

Effort: `2-3 days`

Tasks:

1. Define JSONL schemas and schema versioning strategy.
2. Define state machine and legal transitions.
3. Define deterministic IDs, content hash, and idempotency key format.
4. Build file I/O layer with locking and atomic append/update patterns.

Deliverables:

- schema docs + fixtures
- storage utility module
- state transition guard module

Dependencies: none

### Phase 2: Drafting and Approval Core

Effort: `2-3 days`

Tasks:

1. Ingest `.md` source posts from `Blog Posts/`.
2. Generate LinkedIn and X article variants.
3. Enforce required manual edit before approval.
4. Lock `approved_content_hash` at approval.

Deliverables:

- draft generation service
- approval service + validation checks

Dependencies: Phase 1

### Phase 3: Timing Intelligence and Scheduling

Effort: `2-3 days`

Tasks:

1. Implement recommendation scoring and tie-break policy.
2. Implement low-confidence fallback (`09:30` local) + explicit confirmation requirement.
3. Enforce single campaign schedule time and +30 day horizon.
4. Auto-schedule on approval.

Deliverables:

- timing engine module
- scheduling policy module

Dependencies: Phases 1-2

### Phase 4: Telegram Control Plane

Effort: `4-5 days`

Tasks:

1. Implement whitelisted user enforcement.
2. Implement Telegram decision cards, inline actions, command fallback.
3. Add critical-action token confirmations.
4. Add rate limiting (`20 cmds/min`), timeout (`30 min`), reminder cadence (`30 min`).
5. Add quiet-hour logic (`23:00-06:00`) with critical bypass.
6. Add daily/weekly digests and on-demand commands.

Deliverables:

- Telegram interaction module
- decision audit persistence
- digest/report job module

Dependencies: Phases 1-3

### Phase 5: Worker, Reliability, Safety Controls

Effort: `3-4 days`

Tasks:

1. Build 60-second polling worker loop and execution orchestrator.
2. Implement retries (`5m/15m/45m`) + ambiguous response verify-before-retry.
3. Implement global kill-switch with two-step confirmation.
4. Implement overdue post reconfirmation on resume.
5. Implement cancellation semantics.

Deliverables:

- execution worker
- reliability policy engine
- kill-switch control path

Dependencies: Phases 1-4

### Phase 6: Health Gate and Rollout Controls

Effort: `3-4 days`

Tasks:

1. Implement required daily `/health` gate (`06:00` reset, every day).
2. Validate token/worker/kill-switch/critical-failure status.
3. Implement guided fix actions.
4. Implement token-failure escalation alerts every 30 min until resolved.
5. Implement one-time emergency override + full audit.

Deliverables:

- health gate module
- recovery actions
- override audit controls

Dependencies: Phases 1-5

### Phase 7: Verification and Staged Rollout

Effort: `3-4 days`

Tasks:

1. Build unit/integration/dry-run replay suite per release gate.
2. Run dry-run only stage.
3. Run LinkedIn live stage.
4. Run X live stage.

Deliverables:

- test suite and replay scenarios
- staged rollout checklist and sign-off notes

Dependencies: Phases 1-6

## 4. Total Estimate

- Core build + hardening: `19-26 engineering days`
- With iteration buffer (20%): `23-31 days`

## 5. Critical Path

1. Storage/state contracts
2. Approval hash lock and idempotency
3. Telegram decision loop
4. Worker + retries + kill-switch
5. Health gate
6. Release-gate test suite

## 6. Risk Hotspots

- Telegram UX complexity (timeouts, stale actions, race conditions)
- JSONL consistency under concurrent updates
- OAuth token lifecycle edge cases
- Ambiguous publish responses and duplicate prevention

## 7. Recommended Repo Structure (V1)

```text
social_scheduler/
  cli/
  core/
    models.py
    state_machine.py
    storage_jsonl.py
    hashing.py
    timing_engine.py
    approval_rules.py
  integrations/
    linkedin_client.py
    x_client.py
    telegram_bot.py
  worker/
    runner.py
    retry_policy.py
    kill_switch.py
    health_gate.py
  reports/
    digest.py
  tests/
```

## 8. Technical Decisions Needed From You

Please confirm these before implementation:

1. CLI framework:
   - `Typer` (recommended)
   - `argparse` (stdlib-only)
2. Telegram library:
   - `python-telegram-bot` (recommended)
   - direct API via `httpx`
3. Encryption approach for local token file:
   - `cryptography` Fernet (recommended)
   - OS-native encryption wrapper
4. JSONL write strategy:
   - append + compaction job (recommended)
   - full rewrite on every update
5. Packaging/layout:
   - new `social_scheduler/` package (recommended)
   - extend existing monolithic scripts

### 8.1 Approved Technical Choices

1. CLI framework: `Typer`
2. Telegram integration: Python Telegram library (`python-telegram-bot`)
3. Encryption: `cryptography`
4. JSONL write strategy: append + compaction
5. Code layout: new `social_scheduler/` package

## 9. Approval Gate

Implementation can start only after:

1. You approve the stack choices in Section 8.
2. You approve effort/timeline assumptions.
3. You approve starting with Phase 1.
