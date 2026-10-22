"""선택 종목·조회 조건·분석 결과·엑셀 파일의 세션 상태를 일관되게 관리한다."""

from collections.abc import MutableMapping
from copy import deepcopy
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
    "canvases",
    "canvas_seq",
    "canvas_scroll_generation",
    "pending_attachments",
    "composer_text",
    "composer_files",
    "queued_prompt",
    "queued_submission",
    "retry_submission",
    "awaiting_theme",
    "conversation_mode",
    "inflight_request",
    "results", "active_canvas_id", "request_scope", "request_status", "pending_question",
    "last_submission", "queued_action", "pending_previous_result", "answer_result_id",
)

THEME_KEEP_KEYS = {
    "chat_messages",
    "theme_history",
    "canvases",
    "canvas_seq",
    "canvas_scroll_generation",
    "inflight_request",
    "results", "active_canvas_id",
}

MAX_CANVASES = 8

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
    if isinstance(state.get("dashboard_result"), AnalysisResult):
        remember_result(state, state["dashboard_result"])
        state["pending_previous_result"] = state["dashboard_result"]
    for key in SELECTION_RESULT_KEYS:
        state.pop(key, None)


def reset_all_state(state: MutableMapping[str, Any], *, keep_conversation: bool = False) -> None:
    """새 대화는 전체 초기화, 테마 전환은 대화와 이미 만든 캔버스만 유지한다."""
    for key in ALL_STATE_KEYS:
        if keep_conversation and key in {"composer_text", "composer_files"}:
            continue
        if keep_conversation and key in THEME_KEEP_KEYS:
            continue
        state.pop(key, None)
    if not keep_conversation:
        # 업로더 값은 직접 덮어쓸 수 없으므로 위젯 키를 바꿔 빈 입력으로 재생성한다.
        state["composer_generation"] = int(state.get("composer_generation", 0)) + 1
        for key in list(state):
            if key.startswith(("composer_files_", "canvas_period_")):
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
    state["conversation_mode"] = "candidate_selection"
    state["request_status"] = "awaiting_selection"
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
    state["request_status"] = "pending" if cleaned else "awaiting_selection"


def ensure_export_bundle(
    state: MutableMapping[str, Any],
    result: AnalysisResult,
) -> tuple[bytes, str]:
    """동일 result_id에 대해서는 메모리 엑셀 바이트를 재사용하고, 결과 변경 시에만 새로 생성한다."""
    target_id = canvas_result_id(result)
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
    state["request_status"] = "complete" if result.complete else "partial"
    remember_result(state, result)
    state.pop("pending_previous_result", None)


def store_analysis_error(
    state: MutableMapping[str, Any],
    message: str,
    request_key: str | None = None,
) -> None:
    """선택 종목 분석 또는 후보 탐색 실패 시 이전 결과를 제거하고 오류만 남긴다."""
    reset_selection_result(state)
    state["request_error"] = message
    state["latest_error"] = message
    state["request_status"] = "failed"
    if request_key is not None:
        state["active_request_key"] = request_key


def update_query_options(state: MutableMapping[str, Any], **changes: Any) -> QueryOptions:
    """조회 옵션(기간·사업연도·보고서·연결 구분) 변경 시 결과와 엑셀 캐시를 무효화한다."""
    current = state.get("query_options")
    if not isinstance(current, QueryOptions):
        current = QueryOptions()
    if "price_period" in changes:
        changes["price_range"] = changes["price_period"]
    updated = replace(current, **changes)
    if updated != current:
        reset_selection_result(state)
        state["query_options"] = updated
    return updated


def canvas_result_id(result: AnalysisResult) -> str:
    if result.result_id:
        return result.result_id
    retrieved = result.financial.retrieved_at.isoformat()
    return f"{result.theme}:{result.financial.stock.code}:{retrieved}"


def remember_result(state, result):
    results = dict(state.get("results", {}))
    results[canvas_result_id(result)] = result
    state["results"] = dict(list(results.items())[-20:])


def get_result(state, result_id):
    result = state.get("results", {}).get(result_id)
    if result is not None:
        return result
    return next((c["result"] for c in state.get("canvases", ()) if c["result_id"] == result_id), None)


def historical_result(state, text):
    """과거 대상을 자동으로 최신 결과로 바꾸지 않는다. (명시 여부, 결과)를 반환한다."""
    import re
    cards = list(state.get("canvases", ()))
    def checked(result):
        if result is None:
            return True, None
        known = [r for r in state.get("results", {}).values()]
        known += [c["result"] for c in cards]
        named = {s.code for r in known for s in r.candidates
                 if s.name in text or (s.code and s.code in text)}
        # 카드 지시와 명시한 회사가 충돌하면 과거 숫자를 다른 회사의 답으로 쓰지 않는다.
        return True, result if not named or named == {result.target_code} else None
    if re.search(r"첫\s*번째\s*(?:카드|캔버스)", text):
        return checked(cards[0]["result"] if cards else None)
    if re.search(r"(?:이|현재)\s*(?:카드|캔버스)|이 자료", text):
        card = next((c for c in cards if c["canvas_id"] == state.get("active_canvas_id")), None)
        return checked(card["result"] if card else None)
    if re.search(r"아까|이전\s*(?:종목|결과|분석)", text):
        current = state.get("dashboard_result")
        results = list(state.get("results", {}).values())
        previous = [r for r in results if current is None or canvas_result_id(r) != canvas_result_id(current)]
        return checked(previous[-1] if previous else None)
    return False, None


def add_canvas(state: MutableMapping[str, Any], result: AnalysisResult | None) -> str:
    """현재 결과를 오른쪽 카드로 복사한다. 같은 결과는 한 장만 둔다."""
    if result is None:
        return "missing"
    result_id = canvas_result_id(result)
    canvases = list(state.get("canvases") or [])
    existing = next((item for item in canvases if item.get("result_id") == result_id), None)
    if existing is not None:
        state["canvases"] = [existing, *[c for c in canvases if c is not existing]]
        state["active_canvas_id"] = existing["canvas_id"]
        state["canvas_scroll_generation"] = int(state.get("canvas_scroll_generation") or 0) + 1
        return "focused"
    seq = int(state.get("canvas_seq") or 0) + 1
    state["canvas_seq"] = seq
    # frozen dataclass 안의 dict도 변경 가능하므로 참조가 아닌 독립된 사본을 보관한다.
    snapshot = deepcopy(result)
    canvases.insert(0, {
        "canvas_id": f"c{seq}",
        "result_id": result_id,
        "title": f"{result.financial.stock.name} 분석",
        "stock_name": result.financial.stock.name,
        "stock_code": result.financial.stock.code or "",
        "retrieved_at": result.financial.retrieved_at,
        "result": snapshot,
        "export_bytes": None,
        "export_filename": None,
    })
    state["canvases"] = canvases[:MAX_CANVASES]
    state["active_canvas_id"] = f"c{seq}"
    remember_result(state, result)
    state["canvas_scroll_generation"] = int(state.get("canvas_scroll_generation") or 0) + 1
    return "added"


def close_canvas(state: MutableMapping[str, Any], canvas_id: str) -> None:
    state["canvases"] = [
        item for item in list(state.get("canvases") or []) if item.get("canvas_id") != canvas_id
    ]
    state.pop(f"canvas_period_{canvas_id}", None)
    if state.get("active_canvas_id") == canvas_id:
        state["active_canvas_id"] = state["canvases"][0]["canvas_id"] if state["canvases"] else None


def select_canvas_candidate(
    state: MutableMapping[str, Any], canvas_id: str, code: str, price_period: str | None = None,
) -> bool:
    """과거 캔버스의 동작은 그 카드의 후보·조회 조건으로 새 분석을 준비한다."""
    card = next((c for c in state.get("canvases", ()) if c["canvas_id"] == canvas_id), None)
    if card is None:
        return False
    result = card["result"]
    if not any(s.code == code and s.selectable for s in result.candidates):
        return False
    discovery = CandidateDiscoveryResult(result.theme, result.candidates, result.financial.retrieved_at)
    store_candidate_discovery(state, discovery)
    select_candidate(state, code)
    options = result.query_options
    if price_period is not None:
        options = replace(options, price_period=price_period, price_range=price_period)
    state["query_options"] = options
    return True


def begin_request(state: MutableMapping[str, Any], key: str) -> bool:
    """진행 중에는 중복 실행을 막는다. 성공 결과 캐시와는 별도로 관리한다."""
    if state.get("inflight_request"):
        return False
    state["inflight_request"] = key
    return True


def finish_request(state: MutableMapping[str, Any], key: str) -> None:
    if state.get("inflight_request") == key:
        state.pop("inflight_request", None)


def guide_actions(state: MutableMapping[str, Any]) -> list[str]:
    """화면 상태에 따라 보이는 편의 버튼 키."""
    actions = ["find"]
    if state.get("dashboard_result") is not None:
        actions.append("risk")
    if state.get("selected_code"):
        actions.append("refresh")
    if state.get("dashboard_result") is not None:
        actions.append("canvas")
    return actions


def suggested_prompts(state: MutableMapping[str, Any]) -> tuple[str, ...]:
    """지금 가진 값과 구현된 단일 종목 기능으로 실행 가능한 질문만 제안한다."""
    result = state.get("dashboard_result")
    prompts = []
    if result is not None:
        if result.financial.per is not None or result.financial.pbr is not None:
            prompts.append("현재 종목의 PER와 PBR을 설명해줘")
        if len(result.annual_summaries) >= 2:
            prompts.append("최근 실적이 좋아졌는지 알려줘")
        if result.news.articles:
            prompts.append("이 종목의 최근 뉴스에서 확인할 점은 뭐야?")
        if result.price_history and result.price_history.status == "ok" and len(result.price_history.bars) >= 2:
            prompts.append("조회 기간의 주가와 거래량 변화를 설명해줘")
    elif state.get("candidate_result"):
        # 연관성을 조사하지 않은 후보에게 사업 설명/비교를 약속하지 않는다.
        prompts.append("PER의 뜻을 설명해줘")
    else:
        prompts.extend(("반도체 관련 종목을 찾아줘", "PER와 PBR의 차이를 설명해줘"))
    recent = {m.get("text") for m in list(state.get("chat_messages", ()))[-6:] if m.get("role") == "user"}
    return tuple(p for p in prompts if p not in recent)[:3]


def trigger_refresh(state: MutableMapping[str, Any]) -> QueryOptions:
    """현재 선택된 종목을 명시적으로 재조회하도록 세대 번호를 증가시킨다."""
    current = state.get("query_options")
    if not isinstance(current, QueryOptions):
        current = QueryOptions()
    updated = replace(current, refresh_generation=current.refresh_generation + 1)
    reset_selection_result(state)
    state["query_options"] = updated
    return updated
