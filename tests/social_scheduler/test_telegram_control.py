from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from social_scheduler.core.models import PostState, SocialPost, utc_now_iso
from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.telegram_control import TelegramControl


def _seed_post(service: SocialSchedulerService, post_id: str = "p1") -> None:
    now = utc_now_iso()
    post = SocialPost(
        id=post_id,
        campaign_id="c1",
        platform="x",
        content="hello",
        state=PostState.READY_FOR_APPROVAL,
        created_at=now,
        updated_at=now,
    )
    service.posts.append(post.model_dump())


def _reset(service: SocialSchedulerService) -> None:
    service.posts.delete_where(lambda _: True)
    service.telegram_audit.delete_where(lambda _: True)
    service.telegram_rate.delete_where(lambda _: True)
    service.telegram_decisions.delete_where(lambda _: True)
    service.confirm_tokens.delete_where(lambda _: True)
    service.controls.delete_where(lambda _: True)
    service.manual_overrides.delete_where(lambda _: True)


def test_unauthorized_user_rejected():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    control = TelegramControl(service, allowed_user_id="123")

    result = control.handle_command("999", "/health")
    assert not result.ok


def test_kill_switch_two_step_confirm():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    control = TelegramControl(service, allowed_user_id="123")

    req = control.handle_command("123", "/kill_on")
    assert req.ok
    token = req.message.split()[-1]

    confirm = control.handle_command("123", f"/confirm {token}")
    assert confirm.ok
    assert service.is_kill_switch_on()


def test_rate_limit_blocks_after_20():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    control = TelegramControl(service, allowed_user_id="123")

    for _ in range(20):
        ok = control.handle_command("123", "/health")
        assert ok.ok

    blocked = control.handle_command("123", "/health")
    assert not blocked.ok


def test_expired_decision_moves_post_to_pending_manual():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    control = TelegramControl(service, allowed_user_id="123")

    _seed_post(service)
    req = control.create_decision_request(
        request_type="confirmation",
        message="confirm",
        social_post_id="p1",
        timeout_minutes=30,
    )

    # Force expire by updating expires_at to past.
    row = service.telegram_decisions.find_one("id", req.id)
    assert row is not None
    row["expires_at"] = (datetime.now(tz=ZoneInfo("UTC")) - timedelta(minutes=1)).isoformat()
    service.telegram_decisions.upsert("id", req.id, row)

    expired = control.expire_decision_requests()
    assert expired == 1

    post_row = service.posts.find_one("id", "p1")
    assert post_row is not None
    assert post_row["state"] == PostState.PENDING_MANUAL.value


def test_manual_override_confirm_schedules_post_now():
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)
    _seed_post(service, post_id="p_override")

    # Move to pending_manual so override is relevant.
    row = service.posts.find_one("id", "p_override")
    assert row is not None
    row["state"] = PostState.PENDING_MANUAL.value
    service.posts.upsert("id", "p_override", row)

    control = TelegramControl(service, allowed_user_id="123")
    request = control.handle_command("123", "/override p_override")
    assert request.ok
    token = request.message.split()[-1]

    confirmed = control.handle_command("123", f"/confirm {token}")
    assert confirmed.ok

    post_row = service.posts.find_one("id", "p_override")
    assert post_row is not None
    assert post_row["state"] == PostState.SCHEDULED.value

    audits = service.manual_overrides.read_all()
    assert len(audits) == 1
