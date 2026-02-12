from __future__ import annotations

from social_scheduler.core.models import PostState

_ALLOWED_TRANSITIONS: dict[PostState, set[PostState]] = {
    PostState.DRAFT: {PostState.READY_FOR_APPROVAL, PostState.CANCELED},
    PostState.READY_FOR_APPROVAL: {PostState.PENDING_MANUAL, PostState.APPROVED, PostState.CANCELED},
    PostState.PENDING_MANUAL: {PostState.APPROVED, PostState.SCHEDULED, PostState.CANCELED},
    PostState.APPROVED: {PostState.SCHEDULED, PostState.CANCELED},
    PostState.SCHEDULED: {PostState.POSTED, PostState.FAILED, PostState.CANCELED, PostState.PENDING_MANUAL},
    PostState.FAILED: {PostState.SCHEDULED, PostState.CANCELED},
    PostState.POSTED: set(),
    PostState.CANCELED: set(),
}


def can_transition(current: PostState, target: PostState) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def ensure_transition(current: PostState, target: PostState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"Illegal state transition: {current.value} -> {target.value}")
