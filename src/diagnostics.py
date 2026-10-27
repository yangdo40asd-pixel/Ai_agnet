"""오류의 위치와 종류만 기록한다. 예외 본문·사용자 입력·설정값은 기록하지 않는다."""
import logging
import re

from src.models import AppError

logger = logging.getLogger("ai_agent.diagnostics")
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
