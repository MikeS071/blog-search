# PRD: Automated Scheduling and Posting to LinkedIn and X

## 1. Summary

Build a feature that automatically schedules and posts blog content to LinkedIn and X.com from this blog workspace, with approval controls, retries, and post status tracking.

This PRD is planning-only. No implementation starts until explicit approval.

## 1.1 Engineering Principles (Karpathy-Aligned)

- Keep the system simple and composable; avoid unnecessary complexity in v1.
- Favor deterministic, debuggable behavior over opaque automation.
- Make critical behavior measurable with structured events and clear state transitions.
- Build small, testable units with tight feedback loops.
- Roll out in safe increments with explicit gates and kill-switch controls.

## 2. Problem

Current workflow requires manual distribution after blog writing. This causes:

- Inconsistent posting cadence
- Manual copy/paste effort
- Missed timing windows
- No centralized status history

## 3. Goals

- Publish blog-derived social posts to LinkedIn and X from one workflow.
- Determine and use ideal posting windows before scheduling.
- Support scheduled posting by date/time and timezone.
- Keep human approval before publish in early versions.
- Track per-platform post status and errors.
- Allow retries for transient failures.
- Deliver consistent posting cadence and measurable engagement improvement in month 1.

### 3.1 Success Metrics (Month 1)

- Cadence consistency:
  - At least 90% of approved campaigns are posted on scheduled day/time.
- Engagement lift:
  - Improve average engagement rate vs baseline manual workflow.

## 4. Non-Goals (Initial Release)

- Social analytics dashboard (engagement, impressions, CTR)
- Multi-user role management
- Image/video asset generation pipeline
- Auto-reply/comment automation

## 5. Users

- Primary: Blog owner/operator (single user)
- Secondary (future): Team collaborator/editor

## 6. User Stories

1. As a publisher, I can pick a blog post and generate platform-specific drafts.
2. As a publisher, I can schedule each platform post for a specific timestamp.
3. As a publisher, I can approve/reject drafts before they are published.
4. As a publisher, I can see posting status (`scheduled`, `posted`, `failed`, `retrying`).
5. As a publisher, I can retry failed posts without recreating content.

## 7. Functional Requirements

### 7.1 Content Selection and Drafting

- Select source from `Blog Posts/*.md`.
- Every campaign must include both platforms: LinkedIn and X.
- Generate platform variants:
  - LinkedIn: article post generated from markdown source.
  - X: article post generated from markdown source.
- Use a consistent tone across both platforms.
- No mandatory CTA/link/hashtag/disclosure requirement in v1.
- Human edit is required before approval.
- Overlap in phrasing across platform variants is allowed.
- Support preview/edit before scheduling.

### 7.2 Scheduling

- Run optimal-time analysis before finalizing schedule.
- Auto-schedule immediately after approval.
- Schedule by datetime + timezone.
- Use a single campaign time across all platforms.
- Maximum scheduling horizon is 30 days ahead.
- No blackout windows in v1.
- Validate times are in the future.
- Allow immediate publish as a special case.

### 7.3 Approval Workflow (MVP)

- States:
  - `draft`
  - `ready_for_approval`
  - `approved`
  - `scheduled`
  - `posted`
  - `failed`
- Publish only if state is `approved`.
- Manual approval is default behavior.
- Optional automated approval is allowed only via explicit user-defined rule.
- All human decisions, reviews, and choices are handled via Telegram interactions in v1.

### 7.4 Posting Execution

- Platform connectors:
  - LinkedIn API
  - X API
- Queue due jobs and process asynchronously.
- Idempotency key uses `campaign_id + platform + approved_content_hash`.
- Approved content hash must be locked at approval time and reused at publish time.
- Enforce a global publish kill switch that can pause all pending publishes instantly.

### 7.5 Reliability

- Retry policy for transient errors: 3 attempts with exponential backoff at 5m, 15m, 45m.
- Permanent failure classification for auth/permission/validation errors.
- Structured error messages stored per attempt.
- If publish API response is ambiguous, verify posting status before retrying to prevent duplicates.
- Allow canceling scheduled posts anytime before execution starts.
- If worker missed schedule while offline:
  - Publish immediately if delay <= 2 hours.
  - Require reconfirmation if delay > 2 hours.

### 7.6 Audit and Logs

- Record who approved and when (single-user now, future-proof fields).
- Store request/response metadata with redaction for secrets.
- Provide timeline per social post item.
- Send failure alerts via Telegram in addition to CLI/status output.
- Use structured logs with event IDs and per-campaign timeline correlation.

### 7.7 Optimal Time Analysis

- System must recommend the best posting time before scheduling.
- Recommendation inputs (MVP):
  - Historical post performance (if available)
  - Platform-level default best-time heuristics
  - Primary audience timezone
  - Day-of-week and hour-of-day weighting
- Recommendation output:
  - `recommended_time_utc`
  - `confidence_score` (0-1)
  - `reasoning_summary` (human-readable)
  - `fallback_used` (boolean)
- If confidence is below threshold, require explicit confirmation before scheduling.
- Low-confidence default recommendation is `09:30` local time.
- Tie-break order for equal scores:
  1. Earliest next available slot
  2. Prefer weekdays over weekends
  3. Prefer historically best-performing day
- If no history exists, use deterministic fallback heuristics and flag low confidence.
- Optimization target is a balanced score between engagement and reliability/consistency.

### 7.8 Validation and Dry-Run

- Preflight validator is required before approval/scheduling:
  - platform length/format checks
  - policy checks
  - required structural checks for publishability
- Dry-run mode is required in v1 to simulate scheduling/posting without live publish.
- Run a final preflight re-validation immediately before live publish execution.

### 7.9 Scheduler Execution Model

- v1 uses a local polling worker every 60 seconds.
- v2 can add OS scheduler integration (hybrid model).
- If global kill switch is ON, pause all publish-related execution, including retries and queued publishes.
- On kill-switch resume, overdue posts must be re-evaluated and reconfirmed before publish.

### 7.10 Telegram Control Plane

- Telegram is the primary human-in-the-loop interface in v1.
- Required interaction flows via Telegram:
  - draft review prompts
  - approval/rejection decisions
  - low-confidence schedule confirmation
  - failure alerts and retry decisions
  - kill-switch activation/deactivation
- Access control:
  - Only a single whitelisted Telegram user ID is authorized for control actions in v1.
- Critical-action safety:
  - Require explicit confirmation token for critical actions (`publish_now`, kill-switch toggle, cancel scheduled post).
  - Kill-switch activation/deactivation must always use two-step confirmation (request + confirm token).
- Availability behavior:
  - If Telegram is unavailable at decision time, fail-safe by pausing publish and waiting for recovery.
- Decision timeout policy:
  - Decision requests expire after 30 minutes and transition to `pending_manual`.
- Reminder policy:
  - Send Telegram reminders every 30 minutes until decision is resolved.
- Quiet hours:
  - Local quiet hours are `23:00-06:00` for non-critical reminders.
  - Critical alerts always send (quiet-hours bypass).
- Interaction UX:
  - Provide inline quick-action buttons with text-command fallback.
  - Quick-action buttons expire after 30 minutes.
  - On expiry, system auto-sends a fresh action card.
- Auditability:
  - Persist full Telegram decision metadata (user ID, message ID, timestamp, action, related campaign/post).
- Daily operations:
  - Send two daily Telegram digests at `08:30` and `19:00` local time.
  - Support on-demand digest command (e.g., `/digest`).
- Weekly operations:
  - Send weekly summary every Monday at `20:00` local time.
  - Support on-demand weekly summary command (e.g., `/weekly`).
- Command safety:
  - Apply per-user Telegram command rate limiting at 20 commands/minute.
  - On rate-limit breach, reject command and return cooldown plus safe recovery options.

### 7.11 Daily Health Gate

- Morning operator health check is required each day before live publishing windows.
- Health check command is Telegram-based (for example `/health`).
- Health gate resets daily at `06:00` local time.
- Health gate applies every day, including weekends.
- If health check is missed, block all live publishing until it passes.
- Required health validations:
  - token validity
  - scheduler/worker running status
  - kill-switch state
  - pending critical failures
- `/health` includes guided one-tap recovery actions for recoverable issues.
- If token expiry/refresh failure persists:
  - keep publishing blocked
  - send high-priority Telegram alerts every 30 minutes until resolved
- Critical health-failure alerts bypass quiet hours.
- Dry-run replay within last 24 hours is not required for health gate in v1.
- Emergency one-time manual override is allowed:
  - requires explicit confirmation token
  - must be fully audit-logged

## 8. Non-Functional Requirements

- Security: OAuth tokens encrypted at rest, never logged in clear text.
- Observability: clear logs and status fields for each attempt.
- Performance: handle at least 50 scheduled posts/day without manual intervention.
- Portability: works in mixed WSL/Windows setup currently used by this repo.
- Link management: do not auto-append UTM tags in v1.
- Determinism: publish payload is pinned by approved content hash.

## 9. High-Level Architecture

1. Post Source Layer:
   - Reads blog markdown files and metadata.
2. Drafting Layer:
   - Generates/editable social drafts per platform.
3. Timing Intelligence Layer:
   - Computes ideal campaign post time and confidence.
4. Scheduling Store:
   - Persists jobs and state transitions.
5. Worker/Dispatcher:
   - Polls due jobs and invokes platform connectors.
6. Platform Connectors:
   - LinkedIn and X publish APIs.
7. Status/Audit Layer:
   - Tracks attempts, outcomes, and retry state.
8. Telegram Interaction Layer:
   - Delivers approvals, alerts, confirmations, and operator controls on mobile.

## 10. Data Model (Proposed)

- `social_campaign`
  - `id`
  - `source_blog_path`
  - `campaign_time_utc`
  - `audience_timezone`
  - `generation_prompt_version`
  - `generation_model_version`
  - `created_at`
  - `updated_at`

- `social_post`
  - `id`
  - `campaign_id`
  - `platform` (`linkedin` | `x`)
  - `content`
  - `state`
  - `approved_content_hash`
  - `recommended_for_utc`
  - `recommended_confidence`
  - `recommended_reasoning`
  - `recommendation_fallback_used`
  - `scheduled_for_utc`
  - `approved_at`
  - `posted_at`
  - `external_post_id`
  - `last_error`

- `social_post_attempt`
  - `id`
  - `social_post_id`
  - `attempt_number`
  - `started_at`
  - `finished_at`
  - `result` (`success` | `transient_failure` | `permanent_failure`)
  - `error_code`
  - `error_message_redacted`

- `telegram_decision_audit`
  - `id`
  - `campaign_id`
  - `social_post_id`
  - `telegram_user_id`
  - `telegram_message_id`
  - `action`
  - `decision_token_id` (nullable)
  - `created_at`

- `telegram_rate_limit_event`
  - `id`
  - `telegram_user_id`
  - `command`
  - `window_start_utc`
  - `window_end_utc`
  - `action_taken` (`allowed` | `rejected`)
  - `created_at`

- `health_check_status`
  - `id`
  - `date_local`
  - `checked_at`
  - `overall_status` (`pass` | `fail`)
  - `token_status`
  - `worker_status`
  - `kill_switch_status`
  - `critical_failure_status`
  - `notes`

- `manual_override_audit`
  - `id`
  - `campaign_id`
  - `social_post_id`
  - `telegram_user_id`
  - `reason`
  - `confirmation_token_id`
  - `created_at`

- `approval_rule` (optional for auto-approval)
  - `id`
  - `name`
  - `enabled`
  - `conditions_json`
  - `action` (`auto_approve` | `manual`)
  - `updated_at`
  - Note: latest rules only, no version history in v1.

- `system_control`
  - `key` (`global_publish_paused`)
  - `value`
  - `updated_at`

## 11. API / Tooling Surface (Proposed)

- `create_social_drafts(blog_path, platforms)`
- `update_social_draft(post_id, content)`
- `submit_for_approval(campaign_id)`
- `approve_social_posts(campaign_id)`
- `analyze_optimal_post_time(campaign_id, audience_timezone, constraints)`
- `schedule_campaign(campaign_id, datetime, timezone)`
- `schedule_campaign_auto(campaign_id, audience_timezone, constraints)`
- `publish_now(post_id)`
- `list_social_post_status(filters)`
- `retry_social_post(post_id)`
- `cancel_scheduled_post(post_id)`
- `validate_campaign(campaign_id)`
- `dry_run_campaign(campaign_id)`
- `set_global_publish_pause(enabled)`
- `telegram_decision_webhook(payload)`
- `send_daily_telegram_digest()`
- `send_weekly_telegram_summary()`
- `telegram_digest_command()`
- `telegram_weekly_command()`
- `run_health_check()`
- `health_fix_action(action_id, token)`
- `manual_override_publish(post_id, reason, token)`

## 12. Security and Compliance

- OAuth with least privilege publish-only scopes in v1.
- Single LinkedIn account and single X account in v1.
- Tokens stored in encrypted local file.
- Encryption key loaded from environment variable.
- No secrets in repo, logs, or markdown outputs.
- Respect platform rate limits and posting policies.

## 13. Risks and Mitigations

- API policy/rate-limit changes:
  - Mitigation: connector isolation + clear error mapping.
- Duplicate posting:
  - Mitigation: idempotency keys + state guard checks.
- Token expiry:
  - Mitigation: refresh flow + proactive health check.
- Content length/policy mismatches:
  - Mitigation: platform-specific validation pre-schedule.
- Poor timing recommendations with limited historical data:
  - Mitigation: confidence scoring + manual confirmation gate + fallback heuristics.
- Telegram delivery failures:
  - Mitigation: retry Telegram message sends with backoff and persist failed alert events for operator review.
- Unauthorized Telegram interaction attempts:
  - Mitigation: whitelist enforcement, rejection logging, and optional security alert.
- Telegram command flood / accidental rapid taps:
  - Mitigation: per-user rate limit, cooldown messaging, and safe recovery options.
- Missed daily health check leading to unsafe publishing:
  - Mitigation: mandatory daily health gate with hard block until pass.
- Stale token/refresh failure:
  - Mitigation: persistent blocked state with high-priority 30-minute Telegram escalation until fixed.

## 14. MVP Scope (Phase 1)

- Single-user flow
- LinkedIn + X text posts only
- Both platforms required per campaign
- Manual approval required before scheduling/publish, unless explicit rule-based auto-approval is configured
- Automatic ideal-time recommendation with confidence score and manual override
- Auto-schedule immediately after approval
- Basic retries and status dashboard (CLI/table output acceptable)
- Required preflight validation and required dry-run mode
- Telegram-based human decision workflow and failure alerts
- Single whitelisted Telegram user control model with full decision audit trail
- Global kill switch support
- Local polling worker (60s) with missed-schedule handling policy
- Quiet-hours-aware reminders with critical alert override
- Daily and weekly Telegram digests (scheduled + on-demand)
- Daily required health gate before live publishing
- Emergency one-time manual override path with strict confirmation and audit

## 15. Milestones

1. Design and schema finalized
2. Draft generation and editing flow
3. Approval state machine
4. Scheduler + worker with retries
5. LinkedIn connector
6. X connector
7. End-to-end test pass + dry-run validation
8. Staged rollout:
   - dry-run only
   - LinkedIn live
   - X live

### 15.1 Release Gates

- Before each live phase, pass:
  - unit tests
  - integration tests
  - dry-run replay suite

## 16. Approved Product Decisions

1. Content source and X format:
   - Use article posting generated from a markdown (`.md`) source.
2. Scheduling granularity:
   - Use a single campaign time across all platforms.
3. UX rollout:
   - Build CLI-first, then add MCP tool support.
4. Approval strictness:
   - Manual approval by default.
   - Automated approval is allowed only when an explicit user-defined rule exists.
5. Storage:
   - Use JSONL storage for initial release.
6. Timing recommendation policy:
   - Auto-scheduling is enabled.
7. Platform inclusion:
   - Always post to both LinkedIn and X for each campaign.
8. Scheduling constraints:
   - Max 30 days ahead, no blackout windows in v1.
9. Tone and content controls:
   - Same tone across platforms, no mandatory CTA/link/hashtags/disclosure in v1.
10. Low-confidence behavior:
   - Explicit confirmation required; default recommendation `09:30` local time.
11. Tie-break policy:
   - Earliest slot, then weekday preference, then historically best-performing day.
12. Optimization strategy:
   - Balanced engagement and reliability/consistency.
13. Approval-rule model:
   - Start with simple rules and extend later.
14. Rule history:
   - Latest rule only, no version history in v1.
15. Safety controls:
   - Dry-run and preflight validation are required in v1.
16. Reliability:
   - 3 retries with 5m/15m/45m backoff.
17. Ambiguous publish handling:
   - Verify before retry.
18. Cancellation:
   - Allowed anytime before execution starts.
19. Link policy:
   - No automatic UTM appending in v1.
20. Alerting:
   - CLI/status plus Telegram alerts.
21. Account model:
   - Single LinkedIn account and single X account in v1.
22. Token storage:
   - Encrypted local token file with encryption key from environment variable.
23. Scope policy:
   - Publish-only OAuth scopes in v1.
24. Observability:
   - Structured logs, event IDs, and per-campaign timeline are required.
25. Determinism:
   - Approved content hash is locked at approval and used for idempotency and publish payload.
26. Rollout:
   - Staged: dry-run only, then LinkedIn live, then X live.
27. Kill switch:
   - Global publish pause is required in v1.
28. Scheduling engine:
   - Hybrid strategy: local polling worker in v1, OS scheduler integration later.
29. Polling cadence:
   - 60-second worker interval in v1.
30. Missed schedule policy:
   - Auto-publish only if <= 2h late; else require reconfirmation.
31. Execution safety:
   - Mandatory preflight re-validation at publish time.
32. Reproducibility:
   - Store prompt and model version per campaign.
33. Telegram authorization:
   - Only a single whitelisted Telegram user ID can approve/control v1 workflows.
34. Critical action control:
   - Confirmation token required for publish-now, kill-switch change, and cancellation actions.
35. Telegram outage policy:
   - Fail-safe pause and wait for recovery at decision points.
36. Decision timeout:
   - 30-minute timeout to `pending_manual`.
37. Reminder cadence:
   - Remind every 30 minutes until resolved.
38. Telegram UX:
   - Inline buttons plus text-command fallback.
39. Telegram audit:
   - Persist full decision metadata.
40. Daily digest:
   - Required in v1 with schedule at 08:30 and 19:00 local plus on-demand command.
41. Telegram rate limit:
   - 20 commands/minute per whitelisted user.
42. Rate-limit handling:
   - Reject excess commands with cooldown and safe recovery options.
43. Kill-switch confirmation:
   - Two-step token confirmation required.
44. Kill-switch pause scope:
   - Pause all queued publishes and retries when ON.
45. Resume policy:
   - Re-evaluate and reconfirm overdue posts before publish.
46. Quiet hours:
   - 23:00-06:00 local for non-critical reminders.
47. Quiet-hours critical override:
   - Critical alerts always send.
48. Quick-action TTL:
   - Telegram action buttons expire after 30 minutes.
49. Expiry behavior:
   - Auto-send fresh action card.
50. Weekly summary:
   - Required in v1 every Monday at 20:00 local, plus on-demand command.
51. Daily health gate:
   - Required every day before live publishing.
52. Health gate failure policy:
   - Block all live publishing until health passes.
53. Health check scope:
   - Validate token status, worker running, kill-switch state, and pending critical failures.
54. Health repair UX:
   - Provide guided one-tap recovery actions in Telegram.
55. Health reset:
   - Reset gate daily at 06:00 local.
56. Token-failure escalation:
   - If unresolved, keep blocked and alert every 30 minutes.
57. Critical alert override:
   - Critical health alerts bypass quiet hours.
58. Dry-run dependency:
   - Last-24h dry-run replay is not required for health pass in v1.
59. Emergency override:
   - Allow one-time manual override with explicit token confirmation and full audit logging.
60. CLI framework:
   - Use `Typer`.
61. Telegram integration library:
   - Use Python Telegram library (`python-telegram-bot`).
62. Local encryption approach:
   - Use `cryptography`.
63. JSONL persistence strategy:
   - Use append + compaction.
64. Code organization:
   - Use a new `social_scheduler/` package.

## 17. Implementation Gate

No coding or infrastructure changes begin until explicit approval on:

- MVP scope
- Decisions in Section 16
- Milestone order

## 18. V1 Implementation Blueprint (Planning Only)

This section translates approved decisions into an execution-ready plan. It is implementation planning only.

### 18.1 Delivery Sequence

1. Foundation and schema
2. Drafting and approval flow
3. Timing intelligence and scheduling
4. Telegram control plane and health gate
5. Publish execution and reliability controls
6. Rollout and production hardening

### 18.2 Phase Plan

#### Phase 1: Foundation and Data Contracts

- Define JSONL schemas and schema version fields for:
  - campaigns
  - posts
  - attempts
  - approval rules
  - Telegram audits
  - health status
  - system controls
- Define canonical state machine and legal transitions.
- Define deterministic IDs and content hash strategy.

Exit criteria:

- State transition rules documented and testable.
- JSONL read/write contracts validated with sample fixtures.
- Idempotency key format finalized.

#### Phase 2: Drafting and Approval Core

- Implement `.md` source ingestion from `Blog Posts/*.md`.
- Generate article outputs for LinkedIn and X.
- Enforce required human edit before approval.
- Lock approved content hash at approval time.

Exit criteria:

- Both platform drafts produced per campaign.
- Approval blocked until edit confirmation recorded.
- Content hash remains stable between approval and publish.

#### Phase 3: Timing Intelligence and Scheduling

- Implement recommendation engine with confidence scoring.
- Apply low-confidence fallback (`09:30` local) with explicit confirmation.
- Enforce single campaign time across platforms.
- Enforce scheduling constraints (future only, max +30 days).

Exit criteria:

- Recommendation outputs include time, confidence, reasoning, fallback flag.
- Tie-break policy behaves as specified.
- Auto-schedule triggers immediately after approval.

#### Phase 4: Telegram Control Plane

- Implement whitelisted single-user Telegram authorization.
- Implement decision cards, inline quick actions, and text fallback.
- Implement token-confirmed critical actions.
- Implement reminder cadence, quiet hours, and daily/weekly digests.

Exit criteria:

- Full decision loop works from Telegram end-to-end.
- Decision timeout and `pending_manual` behavior verified.
- Quiet-hour and critical-override behavior verified.

#### Phase 5: Worker, Reliability, and Safety

- Implement 60-second polling worker.
- Implement retries (5m/15m/45m) and ambiguity verification-before-retry.
- Implement kill switch with two-step confirmation and full pause scope.
- Implement missed-schedule policy and resume reconfirmation policy.

Exit criteria:

- Publish pipeline is deterministic and idempotent.
- Kill-switch ON pauses all publish/retry execution.
- Resume path reconfirms overdue posts.

#### Phase 6: Health Gate and Rollout

- Implement required daily `/health` gate (6:00 reset, every day).
- Implement guided fix actions and high-priority escalation behavior.
- Implement staged rollout:
  - dry-run only
  - LinkedIn live
  - X live

Exit criteria:

- Live publish blocked when health gate not passed.
- Emergency one-time override is token-confirmed and fully audited.
- Release gates pass before each stage.

### 18.3 Acceptance Criteria (System-Level)

- Determinism:
  - Approved content hash governs publish payload and idempotency key.
- Safety:
  - No live publish without passing approval + health gate checks.
- Control:
  - Telegram supports all human decisions and critical controls.
- Reliability:
  - Retry and failure handling follow approved policy.
- Auditability:
  - Decision, override, and control actions are fully logged.
- Operability:
  - Daily and weekly summaries provide actionable status visibility.

### 18.4 Test Strategy

- Unit tests:
  - state machine transitions
  - recommendation scoring/tie-break logic
  - idempotency key and content hash rules
- Integration tests:
  - JSONL persistence
  - Telegram decision workflow
  - scheduler/worker execution and retry logic
- Dry-run replay suite:
  - full campaign flow without live posting
  - ambiguous publish responses
  - kill-switch and health-gate scenarios

### 18.5 Operational Runbook (V1)

- Daily:
  - pass `/health` before first live window
  - review pending manual decisions
- During incidents:
  - enable kill switch
  - resolve auth/platform failures
  - reconfirm overdue posts before resume
- Weekly:
  - review Monday summary and adjust approval rules/timing heuristics as needed
