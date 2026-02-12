# Prompt: End-to-End PRD Creation Workflow (for Codex)

Use this prompt when you want Codex to produce a complete, implementation-ready PRD through structured questioning and decision capture.

## Objective

Create a professional PRD that:

- is complete enough to start implementation safely
- includes explicit product decisions and constraints
- includes operations, reliability, and security policies
- includes approval gates before coding

The assistant must ask questions one-by-one, capture each answer, apply answers into the PRD immediately, and keep iterating until all critical unknowns are closed.

## Operating Rules

1. Planning-only mode until explicit user approval to build.
2. Ask one question at a time unless user asks for grouped questions.
3. Convert every user answer into concrete PRD updates.
4. If user gives policy-level preferences, normalize them into deterministic requirements.
5. Keep an explicit `Approved Product Decisions` section as source of truth.
6. After each question cluster, update the PRD file and continue.
7. Prioritize safe defaults, determinism, and auditability.

## Step-by-Step Workflow

### Step 1: Create initial PRD skeleton

Generate sections:

- Summary
- Problem
- Goals / Non-goals
- Users / User stories
- Functional requirements
- Non-functional requirements
- Architecture
- Data model
- API/tool surface
- Security/compliance
- Risks/mitigations
- MVP scope
- Milestones
- Open decisions
- Implementation gate

### Step 2: Round 1 product questions (strategy + behavior)

If appropriate for the solution, Ask and capture, otherwise determine the best questions first and then ask one by one:

1. Primary month-1 success metrics
2. Platform posting scope (mandatory both vs optional)
3. Auto-scheduling trigger point
4. Scheduling horizon
5. Blackout windows
6. Platform tone strategy
7. Mandatory content elements (CTA/link/hashtags/disclosures)
8. Human edit requirement
9. Cross-platform duplication policy
10. Canonical timezone for timing analysis
11. Low-confidence timing behavior
12. Tie-break policy for equal slots
13. Optimization priority (engagement/reliability/balanced)
14. Approval rule complexity model
15. Rule history/versioning
16. Dry-run requirement
17. Retry policy
18. Failure alert channel
19. Ambiguous publish response policy
20. Cancellation policy
21. UTM policy
22. Preflight validator requirement

After answers:

- update requirements and data model
- convert `Open Decisions` into `Approved Product Decisions`

### Step 3: Round 2 technical architecture + operational safety

If appropriate for the solution, Ask and capture, otherwise determine the best questions first and then ask one by one:

1. Account model (single vs multi account)
2. Token storage location
3. Encryption key source
4. OAuth scope policy
5. Observability baseline
6. Content determinism/hash lock policy
7. Rollout strategy (staged vs all-at-once)
8. Kill-switch requirement
9. Idempotency key design
10. Scheduling engine model
11. Polling cadence
12. Missed schedule behavior
13. Publish-time preflight re-check
14. Prompt/model version reproducibility storage
15. Test gate requirement
16. Alert-failure handling policy

After answers:

- embed “engineering principles” section (Karpathy-aligned):
  - simplicity
  - determinism
  - measurable behavior
  - small testable units
  - staged rollout and safety gates

### Step 4: Telegram/mobile-first control plane deep dive

If appropriate for the solution, Ask and capture, otherwise determine the best questions first and then ask one by one:

1. Telegram auth model (whitelist)
2. Confirmation tokens for critical actions
3. Telegram outage fallback
4. Decision timeout policy
5. Reminder cadence
6. Daily digest requirement/times
7. Weekly summary requirement/time/day
8. Quick actions UI (buttons + command fallback)
9. Full Telegram decision audit metadata
10. Quiet hours policy
11. Critical alert quiet-hours bypass
12. Action-card TTL and refresh behavior
13. Command rate limit and limit behavior
14. Kill-switch semantics while ON and on resume

After answers:

- update Telegram requirements section
- update API surface and data model
- update risks and mitigations
- append all choices into `Approved Product Decisions`

### Step 5: Health gate and override policy

Ask and capture:

1. Daily required health gate
2. Failure behavior if gate missed
3. Required health checks
4. Guided fix actions
5. Daily reset time
6. Token failure escalation policy
7. Quiet-hour bypass for critical health failures
8. Dry-run dependency for health pass
9. Weekend applicability
10. One-time emergency override policy

After answers:

- add formal health gate section
- update decisions, API, and audit requirements

### Step 6: Add implementation blueprint

Generate:

- phase sequence
- phase tasks + exit criteria
- acceptance criteria
- testing strategy
- operational runbook

### Step 7: Add implementation plan document

Create separate plan file with:

- recommended stack
- phase effort estimates
- critical path
- risks
- repo structure
- required technical choices

### Step 8: Confirm technical stack choices

Ask user to choose and lock:

- CLI framework
- Telegram integration method
- encryption approach
- JSONL write strategy
- package layout strategy

Then write choices into:

- implementation plan
- PRD approved decisions

### Step 9: Create pre-implementation checklist

Include:

- go/no-go gate
- dependency list
- scaffold plan
- config/env plan
- JSONL contract files
- phase-1 tickets with acceptance criteria
- release gate before phase-2

### Step 10: Build approval and start

Wait for explicit “approved/build it”.

Then implement in small phases with:

- tests added per phase
- checkpoints committed/pushed on request
- no destructive changes to unrelated work

## Question Style Template

When asking each question, use short optioned format:

```
Question N: <topic>
1. <option>
2. <option>
3. <option>
```

If user gives partial/custom answer:

- accept it
- normalize into exact requirement language
- reflect in PRD

## PRD Update Rules

Each answer should update at least one of:

- Functional requirements
- Non-functional requirements
- Data model
- API surface
- Risks/mitigations
- MVP scope
- Approved decisions

Never leave decisions only in chat; persist them in files.

## Output Artifacts Expected

At minimum:

1. `PRD - <feature name>.md`
2. `Implementation Plan - <feature name>.md`
3. `Pre-Implementation Checklist - <feature name>.md`

Optional supporting artifact:

4. This workflow prompt file (`Prompt - PRD creation workflow.md`)
