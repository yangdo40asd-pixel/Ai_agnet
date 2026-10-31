"""채팅 요청의 생명주기. 자료 캐시 키·분석 스냅샷과 요청 ID를 혼용하지 않는다."""
from copy import deepcopy
from dataclasses import dataclass, replace
from uuid import uuid4

from src.models import AppError
from src.models import StockCandidate
from src.agents.request import ChatIntent


REQUEST_STATE_KEYS = (
    "chat_request", "chat_requests", "request_id", "original_question", "resolved_stock",
    "intent", "data_scope", "answer_required", "result_id", "queued_retry_request_id",
    "retry_request_id", "chat_request_status",
)


@dataclass(frozen=True)
class ChatRequest:
    request_id: str
    original_question: str
    history: tuple
    attachments: tuple = ()
    status: str = "idle"
    intent: ChatIntent | None = None
    resolved_stock: StockCandidate | None = None
    data_scope: str = "all"
    answer_required: bool = True
    data_result_id: str | None = None
    result_id: str | None = None
    user_recorded: bool = False
    detail_request: str = ""
    answer_goal: str = ""


def current_request(state):
    return state.get("chat_request")


def _store(state, request):
    state["chat_request"] = request
    records = dict(state.get("chat_requests", {}))
    records[request.request_id] = request
    state["chat_requests"] = dict(list(records.items())[-40:])
    for key in ("request_id", "original_question", "resolved_stock", "intent",
                "data_scope", "answer_required", "result_id"):
        state[key] = getattr(request, key)
    state["chat_request_status"] = request.status
    # 후보 탐색 완료와 분석 종목 선택 대기를 같은 상태로 합치지 않는다.
    state["request_status"] = ("awaiting_selection" if request.status == "completed"
                               and getattr(request.intent, "action", None) == "discover"
                               else request.status)
    return request


def start_request(state, question, history, attachments=(), *, retry_id=None):
    """일반 재전송은 신규 요청이며, 명시적인 실패 재시도만 원래 ID와 원문을 쓴다."""
    if retry_id:
        request = state.get("chat_requests", {}).get(retry_id)
        if request is None or request.original_question != question:
            raise AppError("request_retry", "다시 시도할 원래 질문을 확인할 수 없습니다. 새 질문으로 보내 주세요.")
        if request.status != "failed":
            return None
        return _store(state, replace(request, status="idle"))
    return _store(state, ChatRequest(uuid4().hex, question, tuple(deepcopy(history)),
                                     tuple(deepcopy(attachments))))


def update_request(state, **changes):
    request = current_request(state)
    if request is None:
        return None
    if set(changes) & {"request_id", "original_question", "history", "attachments"}:
        raise ValueError("요청 ID와 원문·최초 문맥은 변경할 수 없습니다.")
    if request.status == "completed":
        raise ValueError("완료된 요청과 결과 ID는 변경할 수 없습니다.")
    return _store(state, replace(request, **changes))


def complete_request(state, *, result_id=None):
    return update_request(state, status="completed", result_id=result_id)


def fail_request(state):
    request = update_request(state, status="failed")
    if request:
        state["retry_request_id"] = request.request_id
        state["retry_submission"] = state.get("last_submission")


def pending_request(state):
    request = current_request(state)
    if request and request.status in {"fetching", "answering"}:
        return request
    return None
