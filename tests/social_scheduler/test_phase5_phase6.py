from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from social_scheduler.core.models import PostState, SocialPost, utc_now_iso
from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.worker.health_gate import can_publish_now
from social_scheduler.worker.runner import WorkerRunner


def _reset(service: SocialSchedulerService) -> None:
    service.posts.delete_where(lambda _: True)
    service.attempts.delete_where(lambda _: True)
    service.telegram_decisions.delete_where(lambda _: True)
    service.controls.delete_where(lambda _: True)
    service.health.delete_where(lambda _: True)


def _seed_scheduled_post(service: SocialSchedulerService, post_id: str, offset_minutes: int = -1) -> SocialPost:
    now = datetime.now(tz=ZoneInfo("UTC"))
    post = SocialPost(
        id=post_id,
        campaign_id="camp_x",
        platform="x",
        content="hello",
        state=PostState.SCHEDULED,
        scheduled_for_utc=(now + timedelta(minutes=offset_minutes)).isoformat(),
        approved_content_hash="abc",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    service.posts.append(post.model_dump())
    return post


def test_transient_failure_reschedules_with_retry_delay():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_retry")

    updated = service.mark_post_result(post, success=False, error_message="timeout", transient=True)
    assert updated.state == PostState.SCHEDULED
    assert updated.scheduled_for_utc is not None


def test_kill_switch_resume_marks_overdue_pending_manual():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_overdue", offset_minutes=-10)

    service.set_kill_switch(True)
    service.set_kill_switch(False)

    row = service.posts.find_one("id", "p_overdue")
    assert row is not None
    assert row["state"] == PostState.PENDING_MANUAL.value

    requests = service.telegram_decisions.read_all()
    assert len(requests) >= 1


def test_worker_blocks_live_publish_when_health_fails():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_live")

    runner = WorkerRunner(service)
    processed = runner.run_once(dry_run=False)
    assert processed == 0

    row = service.posts.find_one("id", "p_live")
    assert row is not None
    assert row["state"] == PostState.SCHEDULED.value


def test_live_publish_requires_daily_health_gate_pass():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_gate")

    # Without a current-day health pass, live publish must be blocked.
    ok, reason = can_publish_now(service)
    assert not ok
    assert "Daily health gate not passed" in reason


def test_health_check_sets_gate_pass_for_today():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    # Seed token file so health can pass.
    from pathlib import Path

    token_file = Path(".social_scheduler/secrets/tokens.enc")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("encrypted-placeholder", encoding="utf-8")
    try:
        status = service.health_check()
        assert status.overall_status == "pass"
        assert service.has_passed_health_gate_today()
    finally:
        token_file.unlink(missing_ok=True)
