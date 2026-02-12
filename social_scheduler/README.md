# Social Scheduler

Automated scheduling and publishing workflow for LinkedIn and X with Telegram-first human controls, safety gates, and JSONL persistence.

## Quick Start

1. Create environment file:

```bash
cp .env.social-scheduler.example .env.social-scheduler
```

2. Fill required variables in `.env.social-scheduler`:

- `SOCIAL_ENCRYPTION_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID`
- platform app credentials

3. Initialize runtime data:

```bash
./.venv/bin/python -m social_scheduler.main init
```

4. Store access tokens in encrypted vault:

```bash
./.venv/bin/python -m social_scheduler.main token-set linkedin_access_token --value '<token>'
./.venv/bin/python -m social_scheduler.main token-set x_access_token --value '<token>'
```

## Run Modes

### Worker daemon

```bash
scripts/social-scheduler/run-worker.sh 60 true
```

Args:

- arg1: poll interval seconds (default `60`)
- arg2: dry-run (`true`/`false`, default `true`)

### Telegram polling bot

```bash
scripts/social-scheduler/run-telegram-polling.sh
```

### Telegram webhook bot

```bash
scripts/social-scheduler/run-telegram-webhook.sh 127.0.0.1 8080 /telegram https://your-public-url
```

## Core Commands

```bash
# Create campaign from markdown source
./.venv/bin/python -m social_scheduler.main campaign-create 'Blog Posts/<file>.md' --audience-timezone 'America/New_York'

# Edit generated draft before approval
./.venv/bin/python -m social_scheduler.main post-edit <post_id> --content-file edited.md
./.venv/bin/python -m social_scheduler.main post-retry <failed_post_id>

# Analyze timing and approve campaign
./.venv/bin/python -m social_scheduler.main campaign-analyze-time <campaign_id>
./.venv/bin/python -m social_scheduler.main preflight --stage pre_approval --campaign-id <campaign_id>
./.venv/bin/python -m social_scheduler.main campaign-approve <campaign_id>

# Run one worker cycle
./.venv/bin/python -m social_scheduler.main worker-run --once true --dry-run true

# Health and kill switch
./.venv/bin/python -m social_scheduler.main health
./.venv/bin/python -m social_scheduler.main kill-switch status
./.venv/bin/python -m social_scheduler.main rollout-stage status
./.venv/bin/python -m social_scheduler.main rollout-stage set linkedin_live

# View lifecycle timeline events
./.venv/bin/python -m social_scheduler.main events --campaign-id <campaign_id> --limit 50

# Reclaim JSONL storage space (all stores or a specific store)
./.venv/bin/python -m social_scheduler.main compact
./.venv/bin/python -m social_scheduler.main compact posts
```

## Operational Notes

- Live publishing (`--dry-run false`) is blocked unless daily health gate has passed.
- Kill switch pauses queued and retry publishing.
- Overdue posts require reconfirmation after kill-switch resume.
- Telegram decision requests expire after 30 minutes and can transition posts to `pending_manual`.
- Telegram control commands include `/health`, `/kill_on`, `/kill_off`, `/override <post_id>`, and `/cancel <post_id>`.
- Critical actions use confirmation tokens and support one-tap inline `Confirm` in Telegram.
- Structured lifecycle events are stored in `.social_scheduler/logs/events.jsonl`.
- If Telegram decision delivery fails, worker enters fail-safe pause by turning kill switch ON.
