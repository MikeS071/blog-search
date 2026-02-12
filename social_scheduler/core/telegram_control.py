from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from social_scheduler.core.models import (
    ConfirmationToken,
    PostState,
    SocialPost,
    TelegramDecisionAudit,
    TelegramDecisionRequest,
    TelegramRateLimitEvent,
    utc_now_iso,
)
from social_scheduler.core.service import SocialSchedulerService


@dataclass
class TelegramResult:
    ok: bool
    message: str


class TelegramControl:
    def __init__(self, service: SocialSchedulerService, allowed_user_id: str):
        self.service = service
        self.allowed_user_id = str(allowed_user_id)

    def create_decision_request(
        self,
        request_type: str,
        message: str,
        campaign_id: str | None = None,
        social_post_id: str | None = None,
        timeout_minutes: int = 30,
    ) -> TelegramDecisionRequest:
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        req = TelegramDecisionRequest(
            id=self.service._new_id("tgr"),  # noqa: SLF001
            request_type=request_type,  # type: ignore[arg-type]
            message=message,
            campaign_id=campaign_id,
            social_post_id=social_post_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=timeout_minutes)).isoformat(),
        )
        self.service.telegram_decisions.append(req.model_dump())
        return req

    def create_confirmation_token(self, action: str, target_id: str, ttl_minutes: int = 30) -> ConfirmationToken:
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        token = ConfirmationToken(
            id=self.service._new_id("tok"),  # noqa: SLF001
            action=action,
            target_id=target_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=ttl_minutes)).isoformat(),
        )
        self.service.confirm_tokens.append(token.model_dump())
        return token

    def refresh_expired_confirmation_token(
        self, token_id: str, ttl_minutes: int = 30
    ) -> ConfirmationToken | None:
        row = self.service.confirm_tokens.find_one("id", token_id)
        if not row:
            return None
        token = ConfirmationToken.model_validate(row)
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        if token.used_at is not None:
            return None
        if datetime.fromisoformat(token.expires_at) > now:
            return None
        return self.create_confirmation_token(
            action=token.action,
            target_id=token.target_id,
            ttl_minutes=ttl_minutes,
        )

    def handle_command(self, telegram_user_id: str, text: str) -> TelegramResult:
        user_id = str(telegram_user_id)
        if user_id != self.allowed_user_id:
            self._audit(user_id, "unauthorized_command")
            return TelegramResult(False, "Unauthorized user")

        limited = self._rate_limited(user_id, text)
        if limited:
            return TelegramResult(False, "Rate limit exceeded. Cooldown in effect. Use /health or wait 60s.")

        parts = text.strip().split()
        if not parts:
            return TelegramResult(False, "Empty command")

        cmd = parts[0].lower()

        if cmd == "/health":
            status = self.service.health_check()
            self._audit(user_id, "health_check")
            return TelegramResult(True, f"Health={status.overall_status}")

        if cmd == "/digest":
            from social_scheduler.reports.digest import daily_digest

            self._audit(user_id, "digest_daily")
            return TelegramResult(True, daily_digest(self.service))

        if cmd == "/weekly":
            from social_scheduler.reports.digest import weekly_summary

            self._audit(user_id, "digest_weekly")
            return TelegramResult(True, weekly_summary(self.service))

        if cmd == "/approve" and len(parts) == 2:
            return self._resolve_request(user_id, parts[1], "approve")

        if cmd == "/reject" and len(parts) == 2:
            return self._resolve_request(user_id, parts[1], "reject")

        if cmd == "/confirm" and len(parts) == 2:
            return self._consume_confirmation_token(user_id, parts[1])

        if cmd in {"/kill_on", "/kill_off"}:
            desired = "on" if cmd == "/kill_on" else "off"
            token = self.create_confirmation_token(action=f"kill_switch_{desired}", target_id="global")
            self._audit(user_id, f"kill_switch_request_{desired}", token.id)
            return TelegramResult(True, f"Confirm with /confirm {token.id}")

        if cmd == "/override" and len(parts) >= 2:
            post_id = parts[1]
            token = self.create_confirmation_token(
                action="manual_override_publish",
                target_id=post_id,
            )
            self._audit(user_id, "manual_override_request", token.id)
            return TelegramResult(True, f"Confirm override with /confirm {token.id}")

        if cmd == "/cancel" and len(parts) >= 2:
            post_id = parts[1]
            token = self.create_confirmation_token(
                action="cancel_scheduled_post",
                target_id=post_id,
            )
            self._audit(user_id, "cancel_post_request", token.id)
            return TelegramResult(True, f"Confirm cancellation with /confirm {token.id}")

        return TelegramResult(False, "Unknown command")

    def expire_decision_requests(self) -> int:
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        expired = 0
        rows = self.service.telegram_decisions.read_all()
        for row in rows:
            req = TelegramDecisionRequest.model_validate(row)
            if req.status != "open":
                continue
            if datetime.fromisoformat(req.expires_at) > now:
                continue

            req.status = "expired"
            req.resolved_at = utc_now_iso()
            req.resolution_action = "timeout"
            self.service.telegram_decisions.upsert("id", req.id, req.model_dump())
            expired += 1

            if req.social_post_id:
                post_row = self.service.posts.find_one("id", req.social_post_id)
                if post_row:
                    post = SocialPost.model_validate(post_row)
                    if post.state in {PostState.READY_FOR_APPROVAL, PostState.APPROVED}:
                        post.state = PostState.PENDING_MANUAL
                        post.updated_at = utc_now_iso()
                        self.service.posts.upsert("id", post.id, post.model_dump())

        return expired

    def reminder_candidates(self, min_interval_minutes: int = 30) -> list[TelegramDecisionRequest]:
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        if self._in_quiet_hours_local(now):
            return []
        rows = self.service.telegram_decisions.read_all()
        out: list[TelegramDecisionRequest] = []
        for row in rows:
            if row.get("status") != "open":
                continue
            req = TelegramDecisionRequest.model_validate(row)
            if datetime.fromisoformat(req.expires_at) <= now:
                continue
            if req.last_reminder_at:
                last = datetime.fromisoformat(req.last_reminder_at.replace("Z", "+00:00"))
                if now - last < timedelta(minutes=min_interval_minutes):
                    continue
            out.append(req)
        return out

    def mark_reminded(self, request_id: str) -> None:
        row = self.service.telegram_decisions.find_one("id", request_id)
        if not row:
            return
        req = TelegramDecisionRequest.model_validate(row)
        if req.status != "open":
            return
        req.last_reminder_at = utc_now_iso()
        req.reminder_count += 1
        self.service.telegram_decisions.upsert("id", req.id, req.model_dump())

    def refresh_expired_request(
        self, request_id: str, timeout_minutes: int = 30
    ) -> TelegramDecisionRequest | None:
        row = self.service.telegram_decisions.find_one("id", request_id)
        if not row:
            return None
        req = TelegramDecisionRequest.model_validate(row)
        if req.status != "expired":
            return None

        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        refreshed = TelegramDecisionRequest(
            id=self.service._new_id("tgr"),  # noqa: SLF001
            campaign_id=req.campaign_id,
            social_post_id=req.social_post_id,
            request_type=req.request_type,
            message=req.message,
            status="open",
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=timeout_minutes)).isoformat(),
        )
        self.service.telegram_decisions.append(refreshed.model_dump())
        return refreshed

    def _resolve_request(self, user_id: str, request_id: str, action: str) -> TelegramResult:
        row = self.service.telegram_decisions.find_one("id", request_id)
        if not row:
            return TelegramResult(False, f"Request not found: {request_id}")
        req = TelegramDecisionRequest.model_validate(row)
        if req.status != "open":
            return TelegramResult(False, f"Request not open: {req.status}")

        req.status = "resolved"
        req.resolved_at = utc_now_iso()
        req.resolution_action = action
        self.service.telegram_decisions.upsert("id", req.id, req.model_dump())
        self._audit(user_id, f"decision_{action}", decision_token_id=req.id)
        return TelegramResult(True, f"Request {request_id} resolved with {action}")

    def _consume_confirmation_token(self, user_id: str, token_id: str) -> TelegramResult:
        row = self.service.confirm_tokens.find_one("id", token_id)
        if not row:
            return TelegramResult(False, f"Token not found: {token_id}")

        token = ConfirmationToken.model_validate(row)
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        if token.used_at is not None:
            return TelegramResult(False, "Token already used")
        if datetime.fromisoformat(token.expires_at) <= now:
            return TelegramResult(False, "Token expired")

        token.used_at = utc_now_iso()
        token.used_by = user_id
        self.service.confirm_tokens.upsert("id", token.id, token.model_dump())

        if token.action == "kill_switch_on":
            self.service.set_kill_switch(True)
            self._audit(user_id, "kill_switch_on", token.id)
            return TelegramResult(True, "Kill switch enabled")
        if token.action == "kill_switch_off":
            self.service.set_kill_switch(False)
            self._audit(user_id, "kill_switch_off", token.id)
            return TelegramResult(True, "Kill switch disabled")
        if token.action == "manual_override_publish":
            post = self.service.manual_override_publish(
                post_id=token.target_id,
                reason="telegram_manual_override",
                telegram_user_id=user_id,
                confirmation_token_id=token.id,
            )
            self._audit(user_id, "manual_override_confirmed", token.id)
            return TelegramResult(True, f"Manual override queued for post {post.id}")
        if token.action == "cancel_scheduled_post":
            post = self.service.cancel_scheduled_post(token.target_id)
            self._audit(user_id, "cancel_post_confirmed", token.id)
            return TelegramResult(True, f"Canceled post {post.id}")

        self._audit(user_id, f"token_consumed_{token.action}", token.id)
        return TelegramResult(True, f"Token consumed for action {token.action}")

    def _rate_limited(self, user_id: str, command: str, limit: int = 20) -> bool:
        now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        window_start = now - timedelta(minutes=1)

        recent = self.service.telegram_rate.filter(
            lambda r: r.get("telegram_user_id") == user_id
            and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= window_start
        )
        blocked = len(recent) >= limit

        event = TelegramRateLimitEvent(
            id=self.service._new_id("trl"),  # noqa: SLF001
            telegram_user_id=user_id,
            command=command,
            window_start_utc=window_start.isoformat(),
            window_end_utc=now.isoformat(),
            action_taken="rejected" if blocked else "allowed",
            created_at=utc_now_iso(),
        )
        self.service.telegram_rate.append(event.model_dump())
        return blocked

    def _in_quiet_hours_local(self, now_utc: datetime) -> bool:
        local = now_utc.astimezone()
        hh = local.hour
        return hh >= 23 or hh < 6

    def _audit(self, user_id: str, action: str, decision_token_id: str | None = None) -> None:
        audit = TelegramDecisionAudit(
            id=self.service._new_id("tga"),  # noqa: SLF001
            telegram_user_id=user_id,
            action=action,
            decision_token_id=decision_token_id,
            created_at=utc_now_iso(),
        )
        self.service.telegram_audit.append(audit.model_dump())
