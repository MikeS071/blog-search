from __future__ import annotations

import os
import asyncio
from pathlib import Path

import typer

from social_scheduler.core.models import SocialPost
from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.token_vault import TokenVault
from social_scheduler.integrations.telegram_runtime import TelegramRuntime
from social_scheduler.core.telegram_control import TelegramControl
from social_scheduler.reports.digest import daily_digest, weekly_summary
from social_scheduler.worker.runner import WorkerRunner

app = typer.Typer(help="Social Scheduler CLI")


def _service() -> SocialSchedulerService:
    ensure_directories()
    return SocialSchedulerService()


@app.command("init")
def init_data() -> None:
    """Initialize storage directories and JSONL files."""
    ensure_directories()
    typer.echo("Initialized .social_scheduler data directories and files.")


@app.command("campaign-create")
def campaign_create(
    blog_path: str = typer.Argument(..., help="Path to markdown source file"),
    audience_timezone: str = typer.Option("America/New_York", help="Audience timezone IANA"),
) -> None:
    service = _service()
    campaign = service.create_campaign_from_blog(blog_path, audience_timezone)
    posts = service.list_campaign_posts(campaign.id)
    typer.echo(f"Campaign created: {campaign.id}")
    for post in posts:
        typer.echo(f"- {post.id} [{post.platform}] state={post.state.value}")


@app.command("campaign-posts")
def campaign_posts(campaign_id: str) -> None:
    service = _service()
    posts = service.list_campaign_posts(campaign_id)
    if not posts:
        typer.echo("No posts found.")
        raise typer.Exit(code=1)
    for p in posts:
        typer.echo(
            f"{p.id} platform={p.platform} state={p.state.value} "
            f"scheduled={p.scheduled_for_utc or '-'} confidence={p.recommended_confidence}"
        )


@app.command("post-edit")
def post_edit(
    post_id: str,
    content_file: Path = typer.Option(..., exists=True, readable=True),
) -> None:
    service = _service()
    content = content_file.read_text(encoding="utf-8")
    post = service.edit_post(post_id, content)
    typer.echo(f"Updated {post.id}; state={post.state.value}; edited_at={post.edited_at}")


@app.command("campaign-analyze-time")
def campaign_analyze_time(campaign_id: str) -> None:
    service = _service()
    rec = service.analyze_optimal_time(campaign_id)
    typer.echo(
        f"Recommended UTC={rec.recommended_time_utc} confidence={rec.confidence_score:.2f} "
        f"fallback={rec.fallback_used}\n{rec.reasoning_summary}"
    )


@app.command("preflight")
def preflight(
    stage: str = typer.Option("pre_approval", help="pre_approval|pre_schedule|pre_publish"),
    campaign_id: str | None = typer.Option(None),
    post_id: str | None = typer.Option(None),
) -> None:
    service = _service()
    failures = service.preflight_posts(stage=stage, campaign_id=campaign_id, post_id=post_id)
    if not failures:
        typer.echo("Preflight OK")
        return
    for pid, errors in failures.items():
        typer.echo(f"{pid}: {'; '.join(errors)}")
    raise typer.Exit(code=1)


@app.command("campaign-approve")
def campaign_approve(campaign_id: str, actor: str = typer.Option("local-cli")) -> None:
    service = _service()
    approved = service.approve_campaign(campaign_id, editor_user=actor)
    typer.echo(f"Approved {len(approved)} posts for campaign {campaign_id}")


@app.command("campaign-schedule")
def campaign_schedule(campaign_id: str, scheduled_utc: str) -> None:
    service = _service()
    posts = service.schedule_campaign(campaign_id, scheduled_utc)
    typer.echo(f"Scheduled {len(posts)} posts at {scheduled_utc}")


@app.command("post-cancel")
def post_cancel(post_id: str) -> None:
    service = _service()
    post = service.cancel_scheduled_post(post_id)
    typer.echo(f"Canceled {post.id}; state={post.state.value}")


@app.command("post-retry")
def post_retry(post_id: str) -> None:
    service = _service()
    post = service.retry_failed_post(post_id)
    typer.echo(f"Retry queued {post.id}; state={post.state.value}; scheduled={post.scheduled_for_utc}")


@app.command("worker-run")
def worker_run(
    once: bool = typer.Option(True, help="Run once if true, otherwise run forever"),
    dry_run: bool = typer.Option(True, help="Use dry-run publishing mode"),
) -> None:
    service = _service()
    runner = WorkerRunner(service)
    if once:
        count = runner.run_once(dry_run=dry_run)
        typer.echo(f"Processed {count} due post(s)")
        return
    runner.run_forever(interval_seconds=60, dry_run=dry_run)


@app.command("worker-daemon")
def worker_daemon(
    interval_seconds: int = typer.Option(60, min=10, help="Polling interval in seconds"),
    dry_run: bool = typer.Option(True, help="Use dry-run publishing mode"),
) -> None:
    service = _service()
    runner = WorkerRunner(service)
    runner.run_forever(interval_seconds=interval_seconds, dry_run=dry_run)


@app.command("health")
def health() -> None:
    service = _service()
    status = service.health_check()
    gate_today = "yes" if service.has_passed_health_gate_today() else "no"
    typer.echo(
        f"Health: {status.overall_status} token={status.token_status} "
        f"worker={status.worker_status} kill_switch={status.kill_switch_status} "
        f"critical_failures={status.critical_failure_status} "
        f"gate_passed_today={gate_today}"
    )


@app.command("kill-switch")
def kill_switch(action: str = typer.Argument(..., help="on|off|status")) -> None:
    service = _service()
    action_lower = action.lower()
    if action_lower == "status":
        typer.echo("on" if service.is_kill_switch_on() else "off")
        return
    if action_lower not in {"on", "off"}:
        raise typer.BadParameter("Action must be one of: on, off, status")
    control = service.set_kill_switch(action_lower == "on")
    typer.echo(f"Kill switch set to {control.value}")


@app.command("rollout-stage")
def rollout_stage(action: str = typer.Argument("status"), stage: str = typer.Argument("all_live")) -> None:
    service = _service()
    action_l = action.lower()
    if action_l == "status":
        typer.echo(service.get_rollout_stage())
        return
    if action_l != "set":
        raise typer.BadParameter("action must be status or set")
    try:
        control = service.set_rollout_stage(stage)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"rollout_stage={control.value}")


@app.command("status")
def status(campaign_id: str | None = None) -> None:
    service = _service()
    if campaign_id:
        posts = service.list_campaign_posts(campaign_id)
    else:
        posts = [SocialPost.model_validate(r) for r in service.posts.read_all()]

    if not posts:
        typer.echo("No posts found.")
        return

    for p in posts:
        typer.echo(
            f"{p.id} campaign={p.campaign_id} platform={p.platform} "
            f"state={p.state.value} scheduled={p.scheduled_for_utc or '-'} posted={p.posted_at or '-'}"
        )


@app.command("events")
def events(
    campaign_id: str | None = typer.Option(None),
    post_id: str | None = typer.Option(None),
    limit: int = typer.Option(50, min=1, max=500),
) -> None:
    service = _service()
    rows = service.query_events(campaign_id=campaign_id, post_id=post_id, limit=limit)
    if not rows:
        typer.echo("No events found.")
        return
    for row in rows:
        details = row.get("details") or {}
        typer.echo(
            f"{row.get('timestamp')} {row.get('event_type')} "
            f"campaign={row.get('campaign_id') or '-'} post={row.get('post_id') or '-'} "
            f"event_id={row.get('event_id')} details={details}"
        )


@app.command("compact")
def compact(store: str = typer.Argument("all", help="Store name or all")) -> None:
    service = _service()
    try:
        result = service.compact_data(store=store)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    total = 0
    for name, saved in result.items():
        total += saved
        typer.echo(f"{name}: reclaimed_bytes={saved}")
    typer.echo(f"total_reclaimed_bytes={total}")


@app.command("digest")
def digest(kind: str = typer.Argument("daily", help="daily|weekly")) -> None:
    service = _service()
    if kind == "daily":
        typer.echo(daily_digest(service))
        return
    if kind == "weekly":
        typer.echo(weekly_summary(service))
        return
    raise typer.BadParameter("kind must be daily or weekly")


@app.command("token-set")
def token_set(
    name: str = typer.Argument(..., help="Token name, e.g. linkedin_access_token"),
    value: str = typer.Option(..., prompt=True, hide_input=True),
) -> None:
    _service()
    vault = TokenVault()
    vault.set_token(name, value)
    typer.echo(f"Stored token: {name}")


@app.command("token-get")
def token_get(name: str) -> None:
    _service()
    vault = TokenVault()
    value = vault.get_token(name)
    if value is None:
        typer.echo("Token not found.")
        raise typer.Exit(code=1)
    typer.echo(f"{name}: present ({len(value)} chars)")


@app.command("token-list")
def token_list() -> None:
    _service()
    vault = TokenVault()
    names = vault.list_tokens()
    if not names:
        typer.echo("No tokens stored.")
        return
    for name in names:
        typer.echo(name)


@app.command("token-delete")
def token_delete(name: str) -> None:
    _service()
    vault = TokenVault()
    deleted = vault.delete_token(name)
    if not deleted:
        typer.echo("Token not found.")
        raise typer.Exit(code=1)
    typer.echo(f"Deleted token: {name}")


@app.command("telegram-run")
def telegram_run() -> None:
    runtime = TelegramRuntime()
    runtime.run_polling()


@app.command("telegram-webhook")
def telegram_webhook(
    listen: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8080),
    url_path: str = typer.Option("/telegram"),
    webhook_url: str = typer.Option("", help="Public HTTPS URL base, e.g. https://example.com"),
) -> None:
    runtime = TelegramRuntime()
    asyncio.run(
        runtime.run_webhook(
            listen=listen,
            port=port,
            url_path=url_path,
            webhook_url=(webhook_url or None),
        )
    )


@app.command("telegram-cmd")
def telegram_cmd(
    user_id: str = typer.Option(..., help="Telegram user id"),
    text: str = typer.Option(..., help="Telegram command text"),
) -> None:
    service = _service()
    allowed = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
    control = TelegramControl(service, allowed_user_id=allowed)
    result = control.handle_command(user_id, text)
    if result.ok:
        typer.echo(result.message)
        return
    typer.echo(result.message)
    raise typer.Exit(code=1)


@app.command("telegram-expire")
def telegram_expire() -> None:
    service = _service()
    allowed = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
    control = TelegramControl(service, allowed_user_id=allowed)
    count = control.expire_decision_requests()
    typer.echo(f"Expired {count} decision request(s)")


@app.command("telegram-reminders")
def telegram_reminders() -> None:
    service = _service()
    allowed = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
    control = TelegramControl(service, allowed_user_id=allowed)
    reminders = control.reminder_candidates()
    if not reminders:
        typer.echo("No reminder candidates.")
        return
    for req in reminders:
        typer.echo(f"{req.id} type={req.request_type} expires_at={req.expires_at} message={req.message}")


if __name__ == "__main__":
    app()
