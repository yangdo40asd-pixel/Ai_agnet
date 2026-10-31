"""사업 자료 수집의 하위 시간 예산. 기존 전체 질문 예산을 늘리지 않는다."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

from src.models import AppError

_deadline = ContextVar("business_source_deadline", default=None)


@contextmanager
def business_budget(seconds=45):
    existing = _deadline.get()
    deadline = time.monotonic() + seconds
    token = _deadline.set(min(existing, deadline) if existing is not None else deadline)
    try:
        yield
    finally:
        _deadline.reset(token)


def business_timeout(settings):
    from src.agents.local_verification import current_turn_remaining
    limits = [settings.request_timeout, 12]
    if _deadline.get() is not None:
        limits.append(_deadline.get() - time.monotonic())
    remaining = current_turn_remaining()
    if remaining is not None:
        limits.append(remaining)
    if min(limits) <= 0:
        raise AppError("business_source_budget", "사업 자료 조회 시간 예산이 끝났습니다.")
    return min(limits)
