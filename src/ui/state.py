"""선택 종목·조회 조건·분석 결과·엑셀 파일의 세션 상태를 일관되게 관리한다."""

from collections.abc import MutableMapping
from dataclasses import replace
from typing import Any

from src.export.excel import build_export_filename, build_workbook_bytes
from src.models import AnalysisResult, CandidateDiscoveryResult, QueryOptions

ALL_STATE_KEYS = (
    "candidate_result",
    "selected_code",
    "query_options",
    "dashboard_result",
    "request_error",
    "export_bytes",
    "export_filename",
    "export_result_id",
    "active_request_key",
    "latest_theme",
    "latest_result",
    "latest_error",
    "candidate_selector",
    "price_range_selector",
    "chat_messages",
    "theme_history",
)

SELECTION_RESULT_KEYS = (
    "dashboard_result",
    "latest_result",
    "request_error",
    "latest_error",
    "export_bytes",
    "export_filename",
    "export_result_id",
    "active_request_key",
)


def build_request_key(
    theme: str,
    selected_code: str | None,
    query_options: QueryOptions | None = None,
) -> str:
    """정규화 테마·선택 종목코드·가격 범위·사업연도/보고서·연결 구분·재조회 세대를 반영한 요청 키."""
    normalized_theme = " ".join(str(theme or "").split())
    code = (selected_code or "").strip().upper()
    options = query_options or QueryOptions()
    return (
        f"{normalized_theme}|{code}|{options.price_period}|"
        f"{options.bsns_year or 'latest'}|{options.reprt_code}|"
        f"{options.fs_div}|{options.refresh_generation}"
    )


def reset_selection_result(state: MutableMapping[str, Any]) -> None:
    """종목 변경·조건 변경·재요청 시 이전 종목의 상세 결과·AI·오류·차트·엑셀 바이트를 무효화한다."""
    for key in SELECTION_RESULT_KEYS:
        state.pop(key, None)


def reset_all_state(state: MutableMapping[str, Any], *, keep_conversation: bool = False) -> None:
    """새 대화는 전체 초기화, 테마 전환은 대화 기록만 유지한다."""
    for key in ALL_STATE_KEYS:
        if keep_conversation and key in {"chat_messages", "theme_history"}:
            continue
        state.pop(key, None)


def store_candidate_discovery(
    state: MutableMapping[str, Any],
    discovery: CandidateDiscoveryResult,
) -> None:
    """새 테마 후보 탐색 결과를 저장하고 선택 상태를 초기 선택 대기 상태로 둔다."""
    reset_all_state(state, keep_conversation=True)
    state["latest_theme"] = discovery.theme
    state["candidate_result"] = discovery
    state["selected_code"] = None
    state["query_options"] = QueryOptions()
    history = list(state.get("theme_history", ()))
    if not history or history[-1] != discovery.theme:
        history.append(discovery.theme)
    state["theme_history"] = history[-10:]


def append_chat_message(state: MutableMapping[str, Any], role: str, text: str, **extra: Any) -> None:
    """세션 내 최근 40개 메시지를 보존한다. 새로고침에서 중복 추가하지 않는다."""
    messages = list(state.get("chat_messages", ()))
    messages.append({"role": role, "text": text, **extra})
    state["chat_messages"] = messages[-40:]


def select_candidate(state: MutableMapping[str, Any], code: str | None) -> None:
    """후보 위젯이나 관련 종목 클릭으로 분석 종목을 변경할 때 호출하는 단일 선택 함수."""
    cleaned = code.strip().upper() if isinstance(code, str) and code.strip() else None
    previous = state.get("selected_code")
    if cleaned != previous:
        reset_selection_result(state)
    state["selected_code"] = cleaned


def ensure_export_bundle(
    state: MutableMapping[str, Any],
    result: AnalysisResult,
) -> tuple[bytes, str]:
    """동일 result_id에 대해서는 메모리 엑셀 바이트를 재사용하고, 결과 변경 시에만 새로 생성한다."""
    target_id = result.result_id or f"{result.theme}:{result.target_code}"
    cached_bytes = state.get("export_bytes")
    cached_name = state.get("export_filename")
    if (
        state.get("export_result_id") == target_id
        and isinstance(cached_bytes, bytes)
        and cached_bytes
        and isinstance(cached_name, str)
        and cached_name
    ):
        return cached_bytes, cached_name

    xlsx_bytes = build_workbook_bytes(result)
    filename = build_export_filename(result)
    state["export_bytes"] = xlsx_bytes
    state["export_filename"] = filename
    state["export_result_id"] = target_id
    return xlsx_bytes, filename


def store_analysis_result(
    state: MutableMapping[str, Any],
    result: AnalysisResult,
    request_key: str,
) -> None:
    """선택 종목 분석 성공(또는 부분 성공) 결과를 저장하고 이전 오류·불일치 엑셀을 정리한다."""
    state.pop("request_error", None)
    state.pop("latest_error", None)
    state["dashboard_result"] = result
    state["latest_result"] = result
    state["active_request_key"] = request_key
    ensure_export_bundle(state, result)


def store_analysis_error(
    state: MutableMapping[str, Any],
    message: str,
    request_key: str | None = None,
) -> None:
    """선택 종목 분석 또는 후보 탐색 실패 시 이전 결과를 제거하고 오류만 남긴다."""
    reset_selection_result(state)
    state["request_error"] = message
    state["latest_error"] = message
    if request_key is not None:
        state["active_request_key"] = request_key


def update_query_options(state: MutableMapping[str, Any], **changes: Any) -> QueryOptions:
    """조회 옵션(기간·사업연도·보고서·연결 구분) 변경 시 결과와 엑셀 캐시를 무효화한다."""
    current = state.get("query_options")
    if not isinstance(current, QueryOptions):
        current = QueryOptions()
    updated = replace(current, **changes)
    if updated != current:
        reset_selection_result(state)
        state["query_options"] = updated
    return updated


def trigger_refresh(state: MutableMapping[str, Any]) -> QueryOptions:
    """현재 선택된 종목을 명시적으로 재조회하도록 세대 번호를 증가시킨다."""
    current = state.get("query_options")
    if not isinstance(current, QueryOptions):
        current = QueryOptions()
    updated = replace(current, refresh_generation=current.refresh_generation + 1)
    reset_selection_result(state)
    state["query_options"] = updated
    return updated
