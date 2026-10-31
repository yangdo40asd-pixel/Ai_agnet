"""로컬 추론 검수의 제한과 계측 및 턴 전체 대기 예산. 일반 앱과 Groq 검수 정책은 변경하지 않는다."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import time
from src.models import AppError

_active = ContextVar("local_llm_verification", default=None)
_turn_deadline = ContextVar("local_llm_turn_deadline", default=None)


@dataclass
class LocalVerification:
    max_requests: int
    max_seconds: float
    started: float = field(default_factory=time.monotonic)
    requests: int = 0
    events: list = field(default_factory=list)

    def before_request(self):
        if self.requests >= self.max_requests or time.monotonic() - self.started > self.max_seconds:
            raise AppError("ai_verification_budget", "이번 로컬 모델 검수의 호출·시간 예산을 사용해 중단했습니다.")
        self.requests += 1


def current_local_verification():
    return _active.get()


def current_turn_remaining() -> float | None:
    deadline = _turn_deadline.get()
    if deadline is None:
        return None
    return deadline - time.monotonic()


@contextmanager
def turn_budget(max_seconds: float):
    """단일 질문 처리 전체(뉴스 판정·생성·심사·재작성)의 누적 대기 시간 예산을 관리한다."""
    existing = _turn_deadline.get()
    if existing is not None:
        yield existing
        return
    deadline = time.monotonic() + float(max_seconds)
    token = _turn_deadline.set(deadline)
    try:
        yield deadline
    finally:
        _turn_deadline.reset(token)


@contextmanager
def local_verification(*, max_requests=12, max_seconds=900):
    if type(max_requests) is not int or not 1 <= max_requests <= 40 or not 1 <= max_seconds <= 3600:
        raise ValueError("로컬 검수는 1~40회, 1~3600초로 제한합니다.")
    state = LocalVerification(max_requests, max_seconds)
    token = _active.set(state)
    try:
        yield state
    finally:
        _active.reset(token)
