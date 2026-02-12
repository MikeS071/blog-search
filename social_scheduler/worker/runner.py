from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from social_scheduler.core.models import PostState
from social_scheduler.core.hashing import content_hash, idempotency_key
from social_scheduler.core.preflight import validate_post
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.telegram_control import TelegramControl
from social_scheduler.core.token_vault import TokenVault
from social_scheduler.integrations.linkedin_client import LinkedInClient
from social_scheduler.integrations.telegram_bot import TelegramNotifier
from social_scheduler.integrations.x_client import XClient
from social_scheduler.reports.digest import daily_digest, weekly_summary
from social_scheduler.worker.health_gate import can_publish_now
from social_scheduler.worker.kill_switch import is_publish_paused


class WorkerRunner:
    def __init__(self, service: SocialSchedulerService) -> None:
        self.service = service
        self.vault = TokenVault() if os.getenv("SOCIAL_ENCRYPTION_KEY") else None
        self.linkedin = LinkedInClient(vault=self.vault)
        self.x = XClient(vault=self.vault)
        self.telegram = TelegramNotifier()
        self.telegram_control = TelegramControl(
            service,
            allowed_user_id=os.getenv("TELEGRAM_ALLOWED_USER_ID", ""),
        )

    def run_once(self, dry_run: bool = True) -> int:
        expired, refreshed = self.telegram_control.expire_and_refresh_decision_requests(refresh=True)
        if expired:
            self._safe_notify(f"{expired} Telegram decision request(s) expired.", critical=True)
        for req in refreshed:
            if self._safe_decision_reminder(req.id, req.message):
                self.telegram_control.mark_reminded(req.id)
            else:
                self._pause_for_telegram_decision_outage(req.id)
        for req in self.telegram_control.reminder_candidates():
            if self._safe_decision_reminder(req.id, req.message):
                self.telegram_control.mark_reminded(req.id)
            else:
                self._pause_for_telegram_decision_outage(req.id)
        self._maybe_send_scheduled_reports()

        if is_publish_paused(self.service):
            self._safe_notify("Publish worker run skipped: kill switch is ON.", critical=True)
            return 0
        if not dry_run:
            ok, reason = can_publish_now(self.service)
            if not ok:
                if self._should_send_health_alert():
                    self._safe_notify(
                        f"Publish worker blocked by health gate: {reason}",
                        critical=True,
                    )
                return 0

        due = self.service.due_posts(datetime.now(tz=ZoneInfo("UTC")))
        processed = 0
        for post in due:
            try:
                if post.state != PostState.SCHEDULED:
                    continue
                if not self.service.should_publish_missed_schedule(post):
                    self._safe_notify(
                        f"Post {post.id} requires reconfirmation (>2h overdue).",
                        critical=True,
                    )
                    continue
                if not dry_run:
                    preflight = validate_post(post, stage="pre_publish")
                    if not preflight.ok:
                        self.service.mark_post_result(
                            post,
                            success=False,
                            error_message=f"Preflight failed: {'; '.join(preflight.errors)}",
                            transient=False,
                        )
                        self._safe_notify(
                            f"Preflight blocked publish for {post.platform} ({post.id}).",
                            critical=True,
                        )
                        continue
                if post.platform == "linkedin":
                    external_id = self.linkedin.publish_article(
                        post.content,
                        dry_run=dry_run,
                        idempotency_key=self._publish_idempotency_key(post),
                    )
                elif post.platform == "x":
                    external_id = self.x.publish_article(
                        post.content,
                        dry_run=dry_run,
                        idempotency_key=self._publish_idempotency_key(post),
                    )
                else:
                    raise RuntimeError(f"Unsupported platform: {post.platform}")

                self.service.mark_post_result(post, success=True, external_post_id=external_id)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if self._is_ambiguous_error(message):
                    verified_external_id = self._verify_ambiguous_publish(post)
                    if verified_external_id:
                        self.service.mark_post_result(
                            post,
                            success=True,
                            external_post_id=verified_external_id,
                        )
                        processed += 1
                        continue
                transient = self._is_transient_error(message)
                self.service.mark_post_result(
                    post,
                    success=False,
                    error_message=message,
                    transient=transient,
                )
                self._safe_notify(
                    f"Post failed for {post.platform} ({post.id}): {exc}", critical=True
                )

        return processed

    def run_forever(self, interval_seconds: int = 60, dry_run: bool = True) -> None:
        while True:
            self.run_once(dry_run=dry_run)
            time.sleep(interval_seconds)

    def _is_transient_error(self, message: str) -> bool:
        lower = message.lower()
        permanent_markers = (
            "unauthorized",
            "forbidden",
            "invalid token",
            "permission",
            "bad request",
            "validation",
        )
        if any(marker in lower for marker in permanent_markers):
            return False
        return True

    def _is_ambiguous_error(self, message: str) -> bool:
        lower = message.lower()
        markers = (
            "ambiguous",
            "timeout",
            "timed out",
            "connection reset",
            "gateway timeout",
        )
        return any(marker in lower for marker in markers)

    def _verify_ambiguous_publish(self, post) -> str | None:
        try:
            if post.platform == "linkedin":
                return self.linkedin.verify_publish(post.id)
            if post.platform == "x":
                return self.x.verify_publish(post.id)
        except Exception:  # noqa: BLE001
            return None
        return None

    def _publish_idempotency_key(self, post) -> str:
        approved_hash = post.approved_content_hash or content_hash(post.content)
        return idempotency_key(post.campaign_id, post.platform, approved_hash)

    def _maybe_send_scheduled_reports(self) -> None:
        now_local = datetime.now().astimezone()
        minute_key = now_local.strftime("%Y-%m-%d %H:%M")
        hm = now_local.strftime("%H:%M")

        daily_slots = {"08:30", "19:00"}
        if hm in daily_slots:
            control_key = f"daily_digest_sent:{minute_key}"
            if self.service.get_control(control_key) != "1":
                self._safe_notify(daily_digest(self.service), critical=False)
                self.service.set_control(control_key, "1")

        if now_local.weekday() == 0 and hm == "20:00":
            control_key = f"weekly_digest_sent:{minute_key}"
            if self.service.get_control(control_key) != "1":
                self._safe_notify(weekly_summary(self.service), critical=False)
                self.service.set_control(control_key, "1")

    def _should_send_health_alert(self) -> bool:
        key = "health_gate_last_alert_utc"
        now = datetime.now(tz=ZoneInfo("UTC"))
        last = self.service.get_control(key)
        if last:
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if now - dt < timedelta(minutes=30):
                    return False
            except ValueError:
                pass
        self.service.set_control(key, now.isoformat())
        return True

    def _safe_notify(self, text: str, critical: bool) -> None:
        try:
            self.telegram.send_message(text, critical=critical)
        except Exception:  # noqa: BLE001
            # Notification failures should not stop scheduling/publishing flow.
            pass

    def _safe_decision_reminder(self, request_id: str, message: str) -> bool:
        try:
            message_id = self.telegram.send_decision_card(request_id=request_id, message=f"Reminder: {message}")
            self.telegram_control.audit_decision_card_sent(
                telegram_user_id=self.telegram_control.allowed_user_id,
                request_id=request_id,
                message_id=message_id,
            )
            return True
        except Exception:  # noqa: BLE001
            try:
                self.telegram.send_message(f"Reminder: {message}", critical=False)
                return True
            except Exception:  # noqa: BLE001
                return False

    def _pause_for_telegram_decision_outage(self, request_id: str) -> None:
        if not self.service.is_kill_switch_on():
            self.service.set_kill_switch(True)
            self.service._log_event(  # noqa: SLF001
                "telegram_decision_outage_paused",
                details={"request_id": request_id},
            )
