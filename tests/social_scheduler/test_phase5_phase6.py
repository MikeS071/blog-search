from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from social_scheduler.core.models import PostState, SocialPost, utc_now_iso
from social_scheduler.core.hashing import idempotency_key
from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.worker.health_gate import can_publish_now
from social_scheduler.worker.runner import WorkerRunner


def _reset(service: SocialSchedulerService) -> None:
    service.posts.delete_where(lambda _: True)
    service.attempts.delete_where(lambda _: True)
    service.telegram_decisions.delete_where(lambda _: True)
    service.telegram_audit.delete_where(lambda _: True)
    service.controls.delete_where(lambda _: True)
    service.health.delete_where(lambda _: True)
    service.events.delete_where(lambda _: True)


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


def test_retry_failed_post_queues_immediate_retry():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_retry_manual")

    failed = service.mark_post_result(post, success=False, error_message="boom", transient=False)
    assert failed.state == PostState.FAILED

    retried = service.retry_failed_post(post.id)
    assert retried.state == PostState.SCHEDULED
    assert retried.scheduled_for_utc is not None
    assert any(
        e["event_type"] == "post_retry_requested" and e["post_id"] == post.id
        for e in service.events.read_all()
    )


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


def test_worker_notification_failures_do_not_crash_run():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_notify")

    runner = WorkerRunner(service)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("notify failed")

    runner.telegram.send_message = _boom  # type: ignore[assignment]
    count = runner.run_once(dry_run=True)
    assert count >= 0


def test_live_publish_requires_daily_health_gate_pass():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_gate")

    # Without a current-day health pass, live publish must be blocked.
    ok, reason = can_publish_now(service)
    assert not ok
    assert "Daily health gate not passed" in reason


def test_health_check_fails_without_worker_heartbeat():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    from pathlib import Path

    token_file = Path(".social_scheduler/secrets/tokens.enc")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("encrypted-placeholder", encoding="utf-8")
    try:
        status = service.health_check()
        assert status.overall_status == "fail"
        assert status.worker_status == "down"
    finally:
        token_file.unlink(missing_ok=True)


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
        service.set_worker_heartbeat()
        status = service.health_check()
        assert status.overall_status == "pass"
        assert service.has_passed_health_gate_today()
    finally:
        token_file.unlink(missing_ok=True)


def test_health_gate_cycle_before_6am_uses_previous_day():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    tz = datetime.now().astimezone().tzinfo
    now_local = datetime(2026, 2, 13, 5, 30, tzinfo=tz)
    prev_day = (now_local.date() - timedelta(days=1)).isoformat()
    service.set_control("health_gate_last_pass_date", prev_day)

    assert service.has_passed_health_gate_today(now_local=now_local)


def test_health_gate_cycle_after_6am_requires_current_day():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    tz = datetime.now().astimezone().tzinfo
    now_local = datetime(2026, 2, 13, 6, 1, tzinfo=tz)
    prev_day = (now_local.date() - timedelta(days=1)).isoformat()
    service.set_control("health_gate_last_pass_date", prev_day)

    assert not service.has_passed_health_gate_today(now_local=now_local)


def test_worker_sends_decision_card_and_marks_reminder():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    service.telegram_decisions.append(
        {
            "id": "tgr_test",
            "request_type": "approval",
            "message": "Approve campaign c1",
            "status": "open",
            "created_at": utc_now_iso(),
            "expires_at": (datetime.now(tz=ZoneInfo("UTC")) + timedelta(minutes=20)).isoformat(),
        }
    )

    runner = WorkerRunner(service)
    sent: list[str] = []

    def _card(request_id: str, message: str) -> str:
        sent.append(f"{request_id}:{message}")
        return "789"

    runner.telegram.send_decision_card = _card  # type: ignore[assignment]
    runner.telegram.send_message = lambda *_args, **_kwargs: None  # type: ignore[assignment]

    runner.run_once(dry_run=True)
    assert len(sent) == 1
    assert sent[0].startswith("tgr_test:")

    row = service.telegram_decisions.find_one("id", "tgr_test")
    assert row is not None
    assert row["reminder_count"] == 1
    audits = service.telegram_audit.read_all()
    assert len(audits) == 1
    assert audits[0]["action"] == "decision_card_sent"
    assert audits[0]["telegram_message_id"] == "789"


def test_worker_live_preflight_failure_marks_post_failed():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_preflight")

    row = service.posts.find_one("id", post.id)
    assert row is not None
    row["content"] = "Bad\n{{placeholder}}"
    row["approved_content_hash"] = None
    service.posts.upsert("id", post.id, row)

    # Ensure health gate can pass for live path.
    from pathlib import Path

    token_file = Path(".social_scheduler/secrets/tokens.enc")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("encrypted-placeholder", encoding="utf-8")
    try:
        service.set_worker_heartbeat()
        health = service.health_check()
        assert health.overall_status == "pass"
        runner = WorkerRunner(service)
        processed = runner.run_once(dry_run=False)
        assert processed == 0

        updated = service.posts.find_one("id", post.id)
        assert updated is not None
        assert updated["state"] == PostState.FAILED.value
        assert "Preflight failed:" in (updated.get("last_error") or "")
    finally:
        token_file.unlink(missing_ok=True)


def test_worker_auto_refreshes_expired_decision_and_sends_card():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    service.telegram_decisions.append(
        {
            "id": "tgr_expired",
            "request_type": "approval",
            "message": "Approve campaign c9",
            "status": "open",
            "created_at": utc_now_iso(),
            "expires_at": (datetime.now(tz=ZoneInfo("UTC")) - timedelta(minutes=1)).isoformat(),
        }
    )

    runner = WorkerRunner(service)
    sent: list[str] = []

    def _card(request_id: str, message: str) -> str:
        sent.append(f"{request_id}:{message}")
        return "901"

    runner.telegram.send_decision_card = _card  # type: ignore[assignment]
    runner.telegram.send_message = lambda *_args, **_kwargs: None  # type: ignore[assignment]
    runner.run_once(dry_run=True)

    assert len(sent) >= 1
    rows = service.telegram_decisions.read_all()
    assert any(r["id"] == "tgr_expired" and r["status"] == "expired" for r in rows)
    assert any(r["status"] == "open" and r["id"] != "tgr_expired" for r in rows)


def test_worker_ambiguous_publish_verifies_as_posted():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_ambiguous_ok")

    runner = WorkerRunner(service)
    runner.x.publish_article = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ambiguous timeout"))  # type: ignore[assignment]
    runner.x.verify_publish = lambda _post_id: "x_live_verified_1"  # type: ignore[assignment]

    count = runner.run_once(dry_run=True)
    assert count == 1
    row = service.posts.find_one("id", post.id)
    assert row is not None
    assert row["state"] == PostState.POSTED.value
    assert row["external_post_id"] == "x_live_verified_1"
    assert any(
        e["event_type"] == "post_publish_result"
        and e["post_id"] == post.id
        and e["details"].get("success") is True
        for e in service.events.read_all()
    )


def test_worker_ambiguous_publish_unverified_reschedules_retry():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_ambiguous_retry")

    runner = WorkerRunner(service)
    runner.x.publish_article = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ambiguous timeout"))  # type: ignore[assignment]
    runner.x.verify_publish = lambda _post_id: None  # type: ignore[assignment]

    count = runner.run_once(dry_run=True)
    assert count == 0
    row = service.posts.find_one("id", post.id)
    assert row is not None
    assert row["state"] == PostState.SCHEDULED.value


def test_worker_passes_deterministic_idempotency_key_to_publish_client():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_idem")

    runner = WorkerRunner(service)
    captured: dict[str, str] = {}

    def _publish(_content: str, dry_run: bool = True, idempotency_key: str | None = None) -> str:
        assert dry_run is True
        captured["key"] = idempotency_key or ""
        return "x_dry_fixed"

    runner.x.publish_article = _publish  # type: ignore[assignment]
    runner.run_once(dry_run=True)

    expected = idempotency_key(post.campaign_id, post.platform, post.approved_content_hash or "")
    assert captured.get("key") == expected


def test_worker_missed_schedule_over_2h_requires_reconfirmation():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_missed_over2h", offset_minutes=-121)

    runner = WorkerRunner(service)
    count = runner.run_once(dry_run=True)
    assert count == 0

    row = service.posts.find_one("id", post.id)
    assert row is not None
    assert row["state"] == PostState.PENDING_MANUAL.value

    reqs = service.telegram_decisions.filter(
        lambda r: r.get("social_post_id") == post.id and r.get("status") == "open"
    )
    assert len(reqs) == 1


def test_worker_missed_schedule_within_2h_publishes_immediately():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    post = _seed_scheduled_post(service, "p_missed_under2h", offset_minutes=-30)

    runner = WorkerRunner(service)
    count = runner.run_once(dry_run=True)
    assert count == 1

    row = service.posts.find_one("id", post.id)
    assert row is not None
    assert row["state"] == PostState.POSTED.value


def test_worker_pauses_when_telegram_unavailable_at_decision_time():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    service.telegram_decisions.append(
        {
            "id": "tgr_outage",
            "request_type": "approval",
            "message": "Approve campaign outage",
            "status": "open",
            "created_at": utc_now_iso(),
            "expires_at": (datetime.now(tz=ZoneInfo("UTC")) + timedelta(minutes=20)).isoformat(),
        }
    )
    runner = WorkerRunner(service)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("telegram down")

    runner.telegram.send_decision_card = _boom  # type: ignore[assignment]
    runner.telegram.send_message = _boom  # type: ignore[assignment]
    runner.run_once(dry_run=True)

    assert service.is_kill_switch_on()
    assert any(
        e["event_type"] == "telegram_decision_outage_paused"
        and e["details"].get("request_id") == "tgr_outage"
        for e in service.events.read_all()
    )


def test_worker_rollout_stage_dry_run_only_blocks_live_publish():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_rollout_block")
    service.set_rollout_stage("dry_run_only")

    from pathlib import Path

    token_file = Path(".social_scheduler/secrets/tokens.enc")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("encrypted-placeholder", encoding="utf-8")
    try:
        service.set_worker_heartbeat()
        service.health_check()
        runner = WorkerRunner(service)
        count = runner.run_once(dry_run=False)
        assert count == 0
        row = service.posts.find_one("id", "p_rollout_block")
        assert row is not None
        assert row["state"] == PostState.SCHEDULED.value
    finally:
        token_file.unlink(missing_ok=True)


def test_worker_rollout_stage_linkedin_live_skips_x_live():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_scheduled_post(service, "p_rollout_x")
    service.set_rollout_stage("linkedin_live")

    from pathlib import Path

    token_file = Path(".social_scheduler/secrets/tokens.enc")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("encrypted-placeholder", encoding="utf-8")
    try:
        service.set_worker_heartbeat()
        service.health_check()
        runner = WorkerRunner(service)
        count = runner.run_once(dry_run=False)
        assert count == 0
        row = service.posts.find_one("id", "p_rollout_x")
        assert row is not None
        assert row["state"] == PostState.SCHEDULED.value
    finally:
        token_file.unlink(missing_ok=True)
