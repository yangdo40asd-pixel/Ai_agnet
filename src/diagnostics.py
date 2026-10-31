"""기본 로그에는 오류 분류만 기록한다. 원문 수집은 명시적 검수 문맥에서만 활성화한다."""
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar

from src.models import AppError

logger = logging.getLogger("ai_agent.diagnostics")
_validation_sink = ContextVar("validation_diagnostic_sink", default=None)


@contextmanager
def capture_validation_events(sink):
    """명시적 검수에서만 공개 자료·생성 결과를 수집한다. 기본 로그에는 원문을 남기지 않는다."""
    token = _validation_sink.set(sink)
    try:
        yield
    finally:
        _validation_sink.reset(token)


def record_validation_failure(stage, payload, evidence, error, *, question=""):
    sink = _validation_sink.get()
    if sink is None:
        return
    from copy import deepcopy
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if not any(word in str(key).lower() for word in ("api_key", "authorization", "password", "secret", "token"))}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return deepcopy(value)
    try:
        sink({"stage": stage, "code": getattr(error, "code", type(error).__name__),
              "question": question, "response": clean(payload), "evidence": clean(evidence),
              "leftover_contexts": list(getattr(error, "leftover_contexts", ()))})
    except Exception:
        # 검수용 기록 장치가 답변의 성공·실패를 변경하지 않는다.
        pass
_STAGES = frozenset({"chat", "analysis", "pending_answer", "export"})
_ERROR_TYPES = frozenset({"AppError", "ValueError", "TypeError", "KeyError", "RuntimeError", "TimeoutError"})
_CODES = frozenset({"ai_auth", "ai_rate_limit", "ai_format", "ai_failed", "ai_truncated",
                    "ai_settings", "stock_unconfirmed", "finance_identity", "settings",
                    "chat_answer", "chat_evidence", "chat_grounding", "chat_numbers"})


def record_failure(stage: str, error: Exception, *, result_id: str | None = None) -> None:
    """허용 목록의 값과 자체 생성 UUID만 남기며 진단 실패는 화면 흐름을 막지 않는다."""
    stage = stage if stage in _STAGES else "unknown"
    error_type = type(error).__name__
    error_type = error_type if error_type in _ERROR_TYPES else "UnexpectedError"
    code = error.code if isinstance(error, AppError) and error.code in _CODES else "unspecified"
    reference = result_id if isinstance(result_id, str) and re.fullmatch(r"[0-9a-f]{32}", result_id) else "none"
    try:
        logger.warning("stage=%s type=%s code=%s result_id=%s", stage, error_type, code, reference)
    except Exception:
        # 기록 장치의 실패 때문에 수집 결과나 캔버스를 잃지 않는다.
        pass
