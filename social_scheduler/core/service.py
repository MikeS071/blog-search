from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from social_scheduler.core.approval_rules import should_auto_approve
from social_scheduler.core.hashing import content_hash
from social_scheduler.core.models import (
    ApprovalRule,
    AttemptResult,
    Campaign,
    HealthCheckStatus,
    ManualOverrideAudit,
    PostState,
    SocialPost,
    SocialPostAttempt,
    SystemControl,
    TelegramDecisionRequest,
    TelegramDecisionAudit,
    utc_now_iso,
)
from social_scheduler.core.paths import (
    ATTEMPTS_FILE,
    CAMPAIGNS_FILE,
    CONFIRM_TOKENS_FILE,
    EVENTS_FILE,
    HEALTH_FILE,
    MANUAL_OVERRIDE_FILE,
    POSTS_FILE,
    RULES_FILE,
    SYSTEM_CONTROLS_FILE,
    TELEGRAM_AUDIT_FILE,
    TELEGRAM_DECISIONS_FILE,
    TELEGRAM_RATE_LIMIT_FILE,
    TOKENS_FILE,
)
from social_scheduler.core.preflight import validate_post
from social_scheduler.core.state_machine import ensure_transition
from social_scheduler.core.storage_jsonl import JsonlStore
from social_scheduler.core.timing_engine import Recommendation, recommend_post_time


class SocialSchedulerService:
    def __init__(self) -> None:
        self.campaigns = JsonlStore(CAMPAIGNS_FILE)
        self.posts = JsonlStore(POSTS_FILE)
        self.attempts = JsonlStore(ATTEMPTS_FILE)
        self.rules = JsonlStore(RULES_FILE)
        self.telegram_audit = JsonlStore(TELEGRAM_AUDIT_FILE)
        self.telegram_decisions = JsonlStore(TELEGRAM_DECISIONS_FILE)
        self.telegram_rate = JsonlStore(TELEGRAM_RATE_LIMIT_FILE)
        self.confirm_tokens = JsonlStore(CONFIRM_TOKENS_FILE)
        self.health = JsonlStore(HEALTH_FILE)
        self.manual_overrides = JsonlStore(MANUAL_OVERRIDE_FILE)
        self.controls = JsonlStore(SYSTEM_CONTROLS_FILE)
        self.events = JsonlStore(EVENTS_FILE)

    def compact_data(self, store: str = "all") -> dict[str, int]:
        stores = {
            "campaigns": self.campaigns,
            "posts": self.posts,
            "attempts": self.attempts,
            "rules": self.rules,
            "telegram_audit": self.telegram_audit,
            "telegram_decisions": self.telegram_decisions,
            "telegram_rate": self.telegram_rate,
            "confirm_tokens": self.confirm_tokens,
            "health": self.health,
            "manual_overrides": self.manual_overrides,
            "controls": self.controls,
            "events": self.events,
        }
        if store == "all":
            return {name: target.compact() for name, target in stores.items()}
        if store not in stores:
            allowed = ", ".join(sorted(stores.keys()))
            raise ValueError(f"Unknown store: {store}. Allowed: {allowed}, all")
        return {store: stores[store].compact()}

    def _new_id(self, prefix: str) -> str:
        raw = f"{prefix}:{utc_now_iso()}:{uuid.uuid4().hex}"
        suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        return f"{prefix}_{suffix}"

    def _log_event(
        self,
        event_type: str,
        campaign_id: str | None = None,
        post_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.events.append(
            {
                "event_id": self._new_id("evt"),
                "event_type": event_type,
                "campaign_id": campaign_id,
                "post_id": post_id,
                "timestamp": utc_now_iso(),
                "details": details or {},
            }
        )

    def preflight_posts(
        self,
        stage: str,
        campaign_id: str | None = None,
        post_id: str | None = None,
    ) -> dict[str, list[str]]:
        if campaign_id and post_id:
            raise ValueError("Provide campaign_id or post_id, not both")
        if post_id:
            row = self.posts.find_one("id", post_id)
            if not row:
                raise ValueError(f"Post not found: {post_id}")
            posts = [SocialPost.model_validate(row)]
        elif campaign_id:
            posts = self.list_campaign_posts(campaign_id)
            if not posts:
                raise ValueError(f"No posts found for campaign: {campaign_id}")
        else:
            posts = [SocialPost.model_validate(r) for r in self.posts.read_all()]

        out: dict[str, list[str]] = {}
        for post in posts:
            result = validate_post(post, stage=stage)
            if not result.ok:
                out[post.id] = result.errors
        return out

    def query_events(
        self,
        campaign_id: str | None = None,
        post_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        rows = self.events.read_all()
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == campaign_id]
        if post_id:
            rows = [r for r in rows if r.get("post_id") == post_id]
        if limit > 0:
            rows = rows[-limit:]
        return rows

    def create_campaign_from_blog(self, blog_path: str, audience_timezone: str) -> Campaign:
        blog_file = Path(blog_path)
        if not blog_file.exists():
            raise FileNotFoundError(f"Blog file not found: {blog_path}")

        content = blog_file.read_text(encoding="utf-8")
        now = utc_now_iso()
        campaign = Campaign(
            id=self._new_id("camp"),
            source_blog_path=blog_path,
            audience_timezone=audience_timezone,
            created_at=now,
            updated_at=now,
        )
        self.campaigns.append(campaign.model_dump())
        self._log_event("campaign_created", campaign_id=campaign.id, details={"source_blog_path": blog_path})

        for platform in ("linkedin", "x"):
            post = SocialPost(
                id=self._new_id("post"),
                campaign_id=campaign.id,
                platform=platform,
                content=self._draft_for_platform(content, platform),
                state=PostState.DRAFT,
                created_at=now,
                updated_at=now,
            )
            self.posts.append(post.model_dump())
            self._log_event(
                "post_drafted",
                campaign_id=campaign.id,
                post_id=post.id,
                details={"platform": platform},
            )

        return campaign

    def _draft_for_platform(self, blog_markdown: str, platform: str) -> str:
        lines = [ln.strip() for ln in blog_markdown.splitlines() if ln.strip()]
        title = lines[0].lstrip("# ") if lines else "Untitled"
        body = "\n\n".join(lines[1:6]) if len(lines) > 1 else ""
        return f"{title}\n\n{body}\n\nSource: article"

    def list_campaign_posts(self, campaign_id: str) -> list[SocialPost]:
        rows = self.posts.filter(lambda r: r.get("campaign_id") == campaign_id)
        return [SocialPost.model_validate(r) for r in rows]

    def edit_post(self, post_id: str, content: str) -> SocialPost:
        row = self.posts.find_one("id", post_id)
        if not row:
            raise ValueError(f"Post not found: {post_id}")
        post = SocialPost.model_validate(row)
        if post.state in (PostState.POSTED, PostState.CANCELED):
            raise ValueError("Cannot edit posted/canceled posts")
        post.content = content
        post.edited_at = utc_now_iso()
        post.updated_at = utc_now_iso()
        if post.state == PostState.DRAFT:
            ensure_transition(post.state, PostState.READY_FOR_APPROVAL)
            post.state = PostState.READY_FOR_APPROVAL
        self.posts.upsert("id", post.id, post.model_dump())
        self._log_event("post_edited", campaign_id=post.campaign_id, post_id=post.id)
        return post

    def analyze_optimal_time(self, campaign_id: str) -> Recommendation:
        campaign_row = self.campaigns.find_one("id", campaign_id)
        if not campaign_row:
            raise ValueError(f"Campaign not found: {campaign_id}")
        campaign = Campaign.model_validate(campaign_row)

        history_exists = bool(self.posts.filter(lambda r: r.get("posted_at") is not None))
        rec = recommend_post_time(campaign.audience_timezone, has_history=history_exists)

        posts = self.list_campaign_posts(campaign_id)
        for post in posts:
            post.recommended_for_utc = rec.recommended_time_utc
            post.recommended_confidence = rec.confidence_score
            post.recommended_reasoning = rec.reasoning_summary
            post.recommendation_fallback_used = rec.fallback_used
            post.updated_at = utc_now_iso()
            self.posts.upsert("id", post.id, post.model_dump())
        return rec

    def approve_campaign(self, campaign_id: str, editor_user: str = "local-cli") -> list[SocialPost]:
        posts = self.list_campaign_posts(campaign_id)
        if len(posts) != 2:
            raise ValueError("Campaign must have exactly two platform posts")

        approved: list[SocialPost] = []
        rules = [ApprovalRule.model_validate(r) for r in self.rules.read_all()]

        for post in posts:
            preflight = validate_post(post, stage="pre_approval")
            if not preflight.ok:
                raise ValueError(f"Preflight failed for {post.id}: {'; '.join(preflight.errors)}")
            if not post.edited_at:
                raise ValueError(f"Post {post.id} requires human edit before approval")
            if post.state not in (PostState.READY_FOR_APPROVAL, PostState.PENDING_MANUAL, PostState.DRAFT):
                raise ValueError(f"Post {post.id} not in approvable state: {post.state.value}")
            if post.state == PostState.DRAFT:
                ensure_transition(PostState.DRAFT, PostState.READY_FOR_APPROVAL)
                post.state = PostState.READY_FOR_APPROVAL

            auto = should_auto_approve(post, rules)
            ensure_transition(post.state, PostState.APPROVED)
            post.state = PostState.APPROVED
            post.approved_at = utc_now_iso()
            post.approved_content_hash = content_hash(post.content)
            post.updated_at = utc_now_iso()
            self.posts.upsert("id", post.id, post.model_dump())
            approved.append(post)
            self._log_event(
                "post_approved",
                campaign_id=campaign_id,
                post_id=post.id,
                details={"approval_mode": "auto" if auto else "manual"},
            )

            audit = TelegramDecisionAudit(
                id=self._new_id("tg"),
                campaign_id=campaign_id,
                social_post_id=post.id,
                telegram_user_id=editor_user,
                action="auto_approve" if auto else "manual_approve",
                created_at=utc_now_iso(),
            )
            self.telegram_audit.append(audit.model_dump())

        # Auto-schedule immediately after approval.
        self.schedule_campaign_auto(campaign_id)
        return approved

    def schedule_campaign_auto(self, campaign_id: str) -> list[SocialPost]:
        campaign_row = self.campaigns.find_one("id", campaign_id)
        if not campaign_row:
            raise ValueError(f"Campaign not found: {campaign_id}")
        campaign = Campaign.model_validate(campaign_row)

        rec = self.analyze_optimal_time(campaign_id)

        # Low confidence requires explicit confirmation; keep pending_manual.
        if rec.confidence_score < 0.5:
            posts = self.list_campaign_posts(campaign_id)
            for post in posts:
                ensure_transition(post.state, PostState.PENDING_MANUAL)
                post.state = PostState.PENDING_MANUAL
                post.updated_at = utc_now_iso()
                self.posts.upsert("id", post.id, post.model_dump())
                req = TelegramDecisionRequest(
                    id=self._new_id("tgr"),
                    campaign_id=campaign_id,
                    social_post_id=post.id,
                    request_type="confirmation",
                    message=(
                        f"Low-confidence timing for {post.platform} post {post.id}. "
                        "Confirm schedule or reschedule manually."
                    ),
                    created_at=utc_now_iso(),
                    expires_at=(datetime.now(tz=ZoneInfo("UTC")) + timedelta(minutes=30)).isoformat(),
                )
                self.telegram_decisions.append(req.model_dump())
            raise ValueError(
                "Low confidence timing recommendation. Explicit confirmation required (fallback 09:30 local)."
            )

        return self.schedule_campaign(campaign_id, rec.recommended_time_utc)

    def schedule_campaign(self, campaign_id: str, scheduled_utc: str) -> list[SocialPost]:
        scheduled = datetime.fromisoformat(scheduled_utc.replace("Z", "+00:00"))
        now = datetime.now(tz=ZoneInfo("UTC"))
        if scheduled <= now:
            raise ValueError("Scheduled time must be in the future")
        if scheduled > now + timedelta(days=30):
            raise ValueError("Scheduling horizon exceeded (max 30 days)")

        campaign_row = self.campaigns.find_one("id", campaign_id)
        if not campaign_row:
            raise ValueError(f"Campaign not found: {campaign_id}")
        campaign = Campaign.model_validate(campaign_row)
        campaign.campaign_time_utc = scheduled.isoformat()
        campaign.updated_at = utc_now_iso()
        self.campaigns.upsert("id", campaign.id, campaign.model_dump())

        posts = self.list_campaign_posts(campaign_id)
        for post in posts:
            preflight = validate_post(post, stage="pre_schedule")
            if not preflight.ok:
                raise ValueError(f"Preflight failed for {post.id}: {'; '.join(preflight.errors)}")
        for post in posts:
            ensure_transition(post.state, PostState.SCHEDULED)
            post.state = PostState.SCHEDULED
            post.scheduled_for_utc = scheduled.isoformat()
            post.updated_at = utc_now_iso()
            self.posts.upsert("id", post.id, post.model_dump())
            self._log_event(
                "post_scheduled",
                campaign_id=campaign_id,
                post_id=post.id,
                details={"scheduled_for_utc": post.scheduled_for_utc},
            )
        return posts

    def set_kill_switch(self, enabled: bool) -> SystemControl:
        control = SystemControl(
            key="global_publish_paused",
            value="true" if enabled else "false",
            updated_at=utc_now_iso(),
        )
        self.controls.upsert("key", control.key, control.model_dump())
        if not enabled:
            self._mark_overdue_for_reconfirmation()
        return control

    def is_kill_switch_on(self) -> bool:
        row = self.controls.find_one("key", "global_publish_paused")
        return bool(row and row.get("value") == "true")

    def get_control(self, key: str) -> str | None:
        row = self.controls.find_one("key", key)
        return None if row is None else row.get("value")

    def set_control(self, key: str, value: str) -> SystemControl:
        control = SystemControl(key=key, value=value, updated_at=utc_now_iso())
        self.controls.upsert("key", key, control.model_dump())
        return control

    def set_worker_heartbeat(self, now_utc: datetime | None = None) -> None:
        now = now_utc or datetime.now(tz=ZoneInfo("UTC"))
        self.set_control("worker_last_heartbeat_utc", now.isoformat())

    def get_rollout_stage(self) -> str:
        return self.get_control("rollout_stage") or "all_live"

    def set_rollout_stage(self, stage: str) -> SystemControl:
        allowed = {"dry_run_only", "linkedin_live", "all_live"}
        if stage not in allowed:
            raise ValueError(f"Invalid rollout stage: {stage}. Allowed: {', '.join(sorted(allowed))}")
        return self.set_control("rollout_stage", stage)

    def health_check(self) -> HealthCheckStatus:
        token_ok = bool(TOKENS_FILE.exists() and TOKENS_FILE.stat().st_size > 0)
        worker_ok = False
        heartbeat = self.get_control("worker_last_heartbeat_utc")
        if heartbeat:
            try:
                hb = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
                worker_ok = (datetime.now(tz=ZoneInfo("UTC")) - hb) <= timedelta(minutes=5)
            except ValueError:
                worker_ok = False
        kill = self.is_kill_switch_on()
        critical_failures = bool(self.posts.filter(lambda r: r.get("state") == PostState.FAILED.value))

        overall = "pass" if token_ok and worker_ok and not critical_failures else "fail"
        status = HealthCheckStatus(
            id=self._new_id("health"),
            date_local=datetime.now().astimezone().date().isoformat(),
            checked_at=utc_now_iso(),
            overall_status=overall,
            token_status="ok" if token_ok else "missing_or_invalid",
            worker_status="ok" if worker_ok else "down",
            kill_switch_status="on" if kill else "off",
            critical_failure_status="present" if critical_failures else "none",
        )
        self.health.append(status.model_dump())
        if status.overall_status == "pass":
            self.set_control("health_gate_last_pass_date", self._health_gate_cycle_date())
        return status

    def _health_gate_cycle_date(self, now_local: datetime | None = None) -> str:
        """
        Health gate cycle resets at 06:00 local time.
        Before 06:00, treat the cycle as previous local date.
        """
        local = (now_local or datetime.now().astimezone()).astimezone()
        cycle_date = local.date()
        if local.hour < 6:
            cycle_date = cycle_date - timedelta(days=1)
        return cycle_date.isoformat()

    def has_passed_health_gate_today(self, now_local: datetime | None = None) -> bool:
        value = self.get_control("health_gate_last_pass_date")
        return value == self._health_gate_cycle_date(now_local)

    def due_posts(self, now_utc: datetime | None = None) -> list[SocialPost]:
        if now_utc is None:
            now_utc = datetime.now(tz=ZoneInfo("UTC"))
        rows = self.posts.filter(
            lambda r: r.get("state") == PostState.SCHEDULED.value
            and r.get("scheduled_for_utc")
            and datetime.fromisoformat(r["scheduled_for_utc"].replace("Z", "+00:00")) <= now_utc
        )
        return [SocialPost.model_validate(r) for r in rows]

    def should_publish_missed_schedule(self, post: SocialPost, now_utc: datetime | None = None) -> bool:
        if now_utc is None:
            now_utc = datetime.now(tz=ZoneInfo("UTC"))
        if not post.scheduled_for_utc:
            return True
        scheduled_dt = datetime.fromisoformat(post.scheduled_for_utc.replace("Z", "+00:00"))
        lag = now_utc - scheduled_dt
        if lag <= timedelta(hours=2):
            return True

        ensure_transition(post.state, PostState.PENDING_MANUAL)
        post.state = PostState.PENDING_MANUAL
        post.updated_at = utc_now_iso()
        self.posts.upsert("id", post.id, post.model_dump())
        self._log_event(
            "post_reconfirmation_required",
            campaign_id=post.campaign_id,
            post_id=post.id,
            details={"lag_minutes": int(lag.total_seconds() // 60)},
        )

        existing_open = self.telegram_decisions.filter(
            lambda r: r.get("social_post_id") == post.id
            and r.get("status") == "open"
            and r.get("request_type") == "confirmation"
        )
        if not existing_open:
            req = TelegramDecisionRequest(
                id=self._new_id("tgr"),
                campaign_id=post.campaign_id,
                social_post_id=post.id,
                request_type="confirmation",
                message=(
                    f"Post {post.id} missed schedule by more than 2 hours. "
                    "Reconfirm schedule before publish."
                ),
                created_at=utc_now_iso(),
                expires_at=(now_utc + timedelta(minutes=30)).isoformat(),
            )
            self.telegram_decisions.append(req.model_dump())
        return False

    def mark_post_result(
        self,
        post: SocialPost,
        success: bool,
        external_post_id: str | None = None,
        error_message: str | None = None,
        transient: bool = True,
    ) -> SocialPost:
        attempt_number = self._next_attempt_number(post.id)
        if success:
            ensure_transition(post.state, PostState.POSTED)
            post.state = PostState.POSTED
            post.posted_at = utc_now_iso()
            post.external_post_id = external_post_id
            post.last_error = None
        else:
            ensure_transition(post.state, PostState.FAILED)
            post.state = PostState.FAILED
            post.last_error = error_message
        post.updated_at = utc_now_iso()
        self.posts.upsert("id", post.id, post.model_dump())
        self._log_event(
            "post_publish_result",
            campaign_id=post.campaign_id,
            post_id=post.id,
            details={
                "success": success,
                "state": post.state.value,
                "external_post_id": external_post_id,
                "transient": transient,
            },
        )

        attempt = SocialPostAttempt(
            id=self._new_id("attempt"),
            social_post_id=post.id,
            attempt_number=attempt_number,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            result=(
                AttemptResult.SUCCESS
                if success
                else (AttemptResult.TRANSIENT_FAILURE if transient else AttemptResult.PERMANENT_FAILURE)
            ),
            error_message_redacted=error_message,
        )
        self.attempts.append(attempt.model_dump())

        if not success and transient:
            from social_scheduler.worker.retry_policy import retry_delay

            delay = retry_delay(attempt_number)
            if delay is not None:
                ensure_transition(post.state, PostState.SCHEDULED)
                post.state = PostState.SCHEDULED
                post.scheduled_for_utc = (datetime.now(tz=ZoneInfo("UTC")) + delay).isoformat()
                post.updated_at = utc_now_iso()
                self.posts.upsert("id", post.id, post.model_dump())
                self._log_event(
                    "post_retry_scheduled",
                    campaign_id=post.campaign_id,
                    post_id=post.id,
                    details={"scheduled_for_utc": post.scheduled_for_utc},
                )
        return post

    def cancel_scheduled_post(self, post_id: str) -> SocialPost:
        row = self.posts.find_one("id", post_id)
        if not row:
            raise ValueError(f"Post not found: {post_id}")
        post = SocialPost.model_validate(row)
        if post.state not in {PostState.SCHEDULED, PostState.PENDING_MANUAL, PostState.FAILED}:
            raise ValueError(f"Cannot cancel post in state {post.state.value}")
        ensure_transition(post.state, PostState.CANCELED)
        post.state = PostState.CANCELED
        post.updated_at = utc_now_iso()
        self.posts.upsert("id", post.id, post.model_dump())
        self._log_event("post_canceled", campaign_id=post.campaign_id, post_id=post.id)
        return post

    def retry_failed_post(self, post_id: str) -> SocialPost:
        row = self.posts.find_one("id", post_id)
        if not row:
            raise ValueError(f"Post not found: {post_id}")
        post = SocialPost.model_validate(row)
        if post.state != PostState.FAILED:
            raise ValueError(f"Can only retry failed posts, got state={post.state.value}")
        ensure_transition(post.state, PostState.SCHEDULED)
        post.state = PostState.SCHEDULED
        post.scheduled_for_utc = datetime.now(tz=ZoneInfo("UTC")).isoformat()
        post.updated_at = utc_now_iso()
        self.posts.upsert("id", post.id, post.model_dump())
        self._log_event(
            "post_retry_requested",
            campaign_id=post.campaign_id,
            post_id=post.id,
            details={"scheduled_for_utc": post.scheduled_for_utc},
        )
        return post

    def manual_override_publish(
        self,
        post_id: str,
        reason: str,
        telegram_user_id: str,
        confirmation_token_id: str,
    ) -> SocialPost:
        row = self.posts.find_one("id", post_id)
        if not row:
            raise ValueError(f"Post not found: {post_id}")
        post = SocialPost.model_validate(row)
        if post.state in {PostState.POSTED, PostState.CANCELED}:
            raise ValueError(f"Cannot override post in state {post.state.value}")
        if post.state != PostState.SCHEDULED:
            ensure_transition(post.state, PostState.SCHEDULED)
            post.state = PostState.SCHEDULED
        post.scheduled_for_utc = datetime.now(tz=ZoneInfo("UTC")).isoformat()
        post.updated_at = utc_now_iso()
        self.posts.upsert("id", post.id, post.model_dump())
        self._log_event(
            "manual_override_publish",
            campaign_id=post.campaign_id,
            post_id=post.id,
            details={"telegram_user_id": telegram_user_id},
        )

        audit = ManualOverrideAudit(
            id=self._new_id("ovr"),
            campaign_id=post.campaign_id,
            social_post_id=post.id,
            telegram_user_id=telegram_user_id,
            reason=reason,
            confirmation_token_id=confirmation_token_id,
            created_at=utc_now_iso(),
        )
        self.manual_overrides.append(audit.model_dump())
        return post

    def _mark_overdue_for_reconfirmation(self) -> None:
        now = datetime.now(tz=ZoneInfo("UTC"))
        for row in self.posts.read_all():
            if row.get("state") != PostState.SCHEDULED.value:
                continue
            scheduled = row.get("scheduled_for_utc")
            if not scheduled:
                continue
            scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
            if scheduled_dt > now:
                continue

            post = SocialPost.model_validate(row)
            ensure_transition(post.state, PostState.PENDING_MANUAL)
            post.state = PostState.PENDING_MANUAL
            post.updated_at = utc_now_iso()
            self.posts.upsert("id", post.id, post.model_dump())

            req = TelegramDecisionRequest(
                id=self._new_id("tgr"),
                campaign_id=post.campaign_id,
                social_post_id=post.id,
                request_type="confirmation",
                message=(
                    f"Post {post.id} became overdue while paused. "
                    "Reconfirm schedule before publish resume."
                ),
                created_at=utc_now_iso(),
                expires_at=(now + timedelta(minutes=30)).isoformat(),
            )
            self.telegram_decisions.append(req.model_dump())

    def _next_attempt_number(self, post_id: str) -> int:
        attempts = self.attempts.filter(lambda r: r.get("social_post_id") == post_id)
        if not attempts:
            return 1
        return max(int(a.get("attempt_number", 0)) for a in attempts) + 1
