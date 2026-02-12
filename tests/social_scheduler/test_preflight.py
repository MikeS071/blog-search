from __future__ import annotations

import pytest

from social_scheduler.core.models import PostState, SocialPost, utc_now_iso
from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.preflight import validate_post
from social_scheduler.core.service import SocialSchedulerService


def _reset(service: SocialSchedulerService) -> None:
    service.campaigns.delete_where(lambda _: True)
    service.posts.delete_where(lambda _: True)


def _post(content: str, platform: str = "x") -> SocialPost:
    now = utc_now_iso()
    return SocialPost(
        id="p1",
        campaign_id="c1",
        platform=platform,  # type: ignore[arg-type]
        content=content,
        state=PostState.READY_FOR_APPROVAL,
        created_at=now,
        updated_at=now,
    )


def test_preflight_rejects_unresolved_placeholders():
    post = _post("Title line\nThis body has enough words but contains {{TODO}} unresolved marker.")
    result = validate_post(post, stage="pre_approval")
    assert not result.ok
    assert any("unresolved template placeholders" in err for err in result.errors)


def test_preflight_requires_body_content():
    post = _post("Title\nToo short")
    result = validate_post(post, stage="pre_approval")
    assert not result.ok
    assert any("body too short" in err for err in result.errors)


def test_approve_campaign_fails_when_preflight_fails(tmp_path):
    ensure_directories()
    service = SocialSchedulerService()
    _reset(service)

    blog = tmp_path / "blog.md"
    blog.write_text("# Valid Title\nThis body has enough words to make a valid draft source document.", encoding="utf-8")
    campaign = service.create_campaign_from_blog(str(blog), "America/New_York")
    posts = service.list_campaign_posts(campaign.id)
    assert len(posts) == 2

    for post in posts:
        service.edit_post(post.id, "Bad\n{{placeholder}}")

    with pytest.raises(ValueError, match="Preflight failed"):
        service.approve_campaign(campaign.id, editor_user="tester")
