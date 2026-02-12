from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from social_scheduler.core.models import PostState
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.telegram_control import TelegramControl
from social_scheduler.integrations.linkedin_client import LinkedInClient
from social_scheduler.integrations.telegram_bot import TelegramNotifier
from social_scheduler.integrations.x_client import XClient
from social_scheduler.reports.digest import daily_digest, weekly_summary
from social_scheduler.worker.health_gate import can_publish_now
from social_scheduler.worker.kill_switch import is_publish_paused


class WorkerRunner:
    def __init__(self, service: SocialSchedulerService) -> None:
        self.service = service
        self.linkedin = LinkedInClient()
        self.x = XClient()
        self.telegram = TelegramNotifier()
        self.telegram_control = TelegramControl(
            service,
            allowed_user_id=os.getenv("TELEGRAM_ALLOWED_USER_ID", ""),
        )

    def run_once(self, dry_run: bool = True) -> int:
        expired = self.telegram_control.expire_decision_requests()
        if expired:
            self.telegram.send_message(f"{expired} Telegram decision request(s) expired.", critical=True)
        for req in self.telegram_control.reminder_candidates():
            self.telegram.send_message(f"Reminder: {req.message}", critical=False)
        self._maybe_send_scheduled_reports()

        if is_publish_paused(self.service):
            self.telegram.send_message("Publish worker run skipped: kill switch is ON.", critical=True)
            return 0
        if not dry_run:
            ok, reason = can_publish_now(self.service)
            if not ok:
                self.telegram.send_message(f"Publish worker blocked by health gate: {reason}", critical=True)
                return 0

        due = self.service.due_posts(datetime.now(tz=ZoneInfo("UTC")))
        processed = 0
        for post in due:
            try:
                if post.state != PostState.SCHEDULED:
                    continue
                if post.platform == "linkedin":
                    external_id = self.linkedin.publish_article(post.content, dry_run=dry_run)
                elif post.platform == "x":
                    external_id = self.x.publish_article(post.content, dry_run=dry_run)
                else:
                    raise RuntimeError(f"Unsupported platform: {post.platform}")

                self.service.mark_post_result(post, success=True, external_post_id=external_id)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                transient = self._is_transient_error(message)
                self.service.mark_post_result(
                    post,
                    success=False,
                    error_message=message,
                    transient=transient,
                )
                self.telegram.send_message(
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

    def _maybe_send_scheduled_reports(self) -> None:
        now_local = datetime.now().astimezone()
        minute_key = now_local.strftime("%Y-%m-%d %H:%M")
        hm = now_local.strftime("%H:%M")

        daily_slots = {"08:30", "19:00"}
        if hm in daily_slots:
            control_key = f"daily_digest_sent:{minute_key}"
            if self.service.get_control(control_key) != "1":
                self.telegram.send_message(daily_digest(self.service), critical=False)
                self.service.set_control(control_key, "1")

        if now_local.weekday() == 0 and hm == "20:00":
            control_key = f"weekly_digest_sent:{minute_key}"
            if self.service.get_control(control_key) != "1":
                self.telegram.send_message(weekly_summary(self.service), critical=False)
                self.service.set_control(control_key, "1")
