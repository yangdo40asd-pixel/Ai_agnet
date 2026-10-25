"""사용자 입력, 후보 종목 선택, 조회 결과, 근거와 누락 안내를 표시하는 화면."""

import re
import sys
from pathlib import Path

import streamlit as st

# Streamlit이 파일 경로로 실행해도 프로젝트의 src 모듈을 찾을 수 있게 한다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.history import PRICE_RANGE_LABELS
from src.agents.chat import (
    answer_question,
    prepare_submission,
    resolve_follow_up,
    route_message,
)
from src.analysis_flow import needs_data, analysis_response
from src.diagnostics import record_failure
from src.config import load_settings
from src.models import AppError, CandidateDiscoveryResult, QueryOptions, StockCandidate, now_kst
from src.pipeline import analyze_selected_stock, discover_theme_candidates, identify_stock
from src.ui.dashboard import render_dashboard
from src.ui.answer import render_answer, response_fields, time_label
from src.ui.layout import WORKSPACE_CSS, canvas_scroll_key, panel_content_height
from src.ui.state import (
    build_request_key,
    append_chat_message,
    reset_all_state,
    reset_selection_result,
    select_candidate,
    store_analysis_error,
    store_analysis_result,
    store_candidate_discovery,
    trigger_refresh,
    prepare_analysis_request,
    add_canvas,
    close_canvas,
    guide_actions,
    begin_request,
    finish_request,
    select_canvas_candidate,
    suggested_prompts,
    get_result, historical_result, canvas_result_id, ensure_export_bundle, update_query_options,
)


def escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>$~])", r"\\\1", text)


def candidate_role_label(stock: StockCandidate, selected_code: str | None) -> str:
    if selected_code and stock.code == selected_code:
        return "대표 종목 (선택됨)"
    if stock.selectable:
        return "선택 가능"
    return "선택 불가"


def render_candidates_table(
    candidates: tuple[StockCandidate, ...],
    selected_code: str | None,
) -> None:
    st.subheader("관련 종목 후보")
    st.dataframe(
        [
            {
                "후보": index,
                "종목명": stock.name,
                "종목코드": stock.code or "미확인",
                "시장": stock.market or "미확인",
                "상장 확인": "확인" if stock.verified else "미확인",
                "분석 대상": candidate_role_label(stock, selected_code),
                "안내": stock.reason or "상장 종목명·코드 확인",
                "테마 연관 근거": stock.association_reason or "별도 확인 안 됨",
                "근거 상태": stock.association_status,
            }
            for index, stock in enumerate(candidates, 1)
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "AI가 제안한 순서이며 투자 우선순위가 아닙니다. 상장 및 지원 시장이 확인된 후보만 선택해 분석할 수 있습니다. "
        "상장 확인은 테마 연관성을 보증하지 않습니다."
    )


def _on_selector_change() -> None:
    chosen = st.session_state.get("candidate_selector")
    select_candidate(st.session_state, chosen)


def _on_range_change(canvas_id: str, code: str) -> None:
    chosen_range = st.session_state.get(f"canvas_period_{canvas_id}")
    if isinstance(chosen_range, str) and chosen_range in PRICE_RANGE_LABELS:
        select_canvas_candidate(st.session_state, canvas_id, code, chosen_range)


def render_candidate_selector(
    discovery: CandidateDiscoveryResult,
    selected_code: str | None,
) -> None:
    selectable = discovery.selectable_candidates
    if not selectable:
        return
    code_to_stock = {stock.code: stock for stock in selectable if stock.code}
    options: list[str | None] = [None, *list(code_to_stock)]
    if selected_code in code_to_stock:
        st.session_state["candidate_selector"] = selected_code
    elif "candidate_selector" not in st.session_state or st.session_state.get("candidate_selector") not in options:
        st.session_state["candidate_selector"] = None

    def format_option(code: str | None) -> str:
        if code is None:
            return "종목을 선택하세요"
        stock = code_to_stock.get(code)
        if stock is None:
            return str(code)
        return f"{stock.name} ({stock.code} · {stock.market})"

    st.selectbox(
        "분석할 종목 선택",
        options=options,
        format_func=format_option,
        key="candidate_selector",
        on_change=_on_selector_change,
    )


def render_related_candidate_buttons(
    candidates: tuple[StockCandidate, ...],
    selected_code: str | None,
    *,
    key_prefix: str = "related_select",
) -> None:
    st.markdown("**후보 종목 바로 선택**")
    cols = st.columns(max(len(candidates), 1))
    for col, stock in zip(cols, candidates):
        with col:
            if stock.selectable and stock.code:
                is_current = stock.code == selected_code
                label = (
                    f"{stock.name} ({stock.code}) · 현재 선택됨"
                    if is_current
                    else f"{stock.name} ({stock.code}) 선택"
                )
                st.button(
                    label,
                    key=f"{key_prefix}_{stock.code}",
                    disabled=is_current,
                    on_click=select_candidate,
                    args=(st.session_state, stock.code),
                )
            else:
                st.button(
                    f"{stock.name} (선택 불가)",
                    key=f"{key_prefix}_disabled_{stock.name}",
                    disabled=True,
                )
                st.caption(stock.reason or "상장 미확인")


def _say(state, text: str, **extra) -> None:
    linked = get_result(state, extra.get("result_id")) if extra.get("result_id") else None
    if linked is not None:
        extra["result_target"] = {"name": linked.financial.stock.name, "code": linked.target_code}
    show_follow_up = extra.pop("show_follow_up", True)
    follow = resolve_follow_up(
        extra.pop("follow_up", ""),
        list(state.get("chat_messages", ())),
        state.get("dashboard_result"),
        state.get("candidate_result"),
    )
    if not show_follow_up:
        follow = ""
    append_chat_message(state, "assistant", text, follow_up=follow, **extra)


def _fill_prompt(text: str) -> None:
    st.session_state["composer_text"] = text


def render_state_context() -> None:
    state = st.session_state
    result = state.get("dashboard_result")
    discovery = state.get("candidate_result")
    mode = state.get("conversation_mode", "general")
    if result is not None:
        stock = result.financial.stock
        st.caption(
            f"현재 분석 결과 · {stock.name} ({stock.code}) · {stock.market or '시장 미확인'} · "
            f"조회 시각 {result.financial.retrieved_at:%Y-%m-%d %H:%M}"
        )
    elif discovery is not None:
        st.caption(
            f"현재 탐색 중 · {discovery.theme} · 후보 {len(discovery.candidates)}개 · "
            f"확인 시각 {discovery.retrieved_at:%Y-%m-%d %H:%M}"
        )
    elif mode == "theme_search":
        st.caption("테마 검색 모드 · 테마를 입력하기 전에는 외부 자료를 조회하지 않습니다.")
    else:
        st.caption("대화형 탐색 중 · 테마, 종목, 시장에 관해 자유롭게 질문해 보세요.")


def _on_find() -> None:
    st.session_state["conversation_mode"] = "theme_search"
    st.session_state.pop("awaiting_theme", None)


def _on_refresh() -> None:
    trigger_refresh(st.session_state)
    _say(st.session_state, "현재 종목 자료를 다시 조회합니다.")


def _on_add_canvas(result_id: str | None = None) -> None:
    state = st.session_state
    result = get_result(state, result_id) if result_id else state.get("dashboard_result")
    status = add_canvas(state, result)
    if status == "missing":
        _say(state, "해당 분석 결과가 남아 있지 않습니다. 종목을 다시 조회해 주세요.", show_follow_up=False)


def _prepare_export(canvas_id):
    card = next((c for c in st.session_state.get("canvases", ()) if c["canvas_id"] == canvas_id), None)
    if card is None:
        return
    try:
        data, name = ensure_export_bundle(card, card["result"])
        card["export_bytes"], card["export_filename"] = data, name
        card.pop("export_error", None)
    except Exception as error:
        record_failure("export", error, result_id=card["result"].result_id)
        card["export_error"] = "엑셀을 생성하지 못했습니다. 분석 자료는 유지됩니다. 다시 시도할 수 있습니다."


def _on_close_canvas(canvas_id: str) -> None:
    close_canvas(st.session_state, canvas_id)


def _on_retry_submission() -> None:
    submission = st.session_state.get("retry_submission")
    if submission is not None:
        st.session_state["queued_submission"] = submission


def process_chat_message(raw_text: str, files: list[tuple[str, bytes]] | None = None, explicit_action=None) -> None:
    if not begin_request(st.session_state, "chat"):
        st.info("현재 요청을 처리 중입니다. 잠시 기다려 주세요.")
        return
    try:
        _process_chat_message(raw_text, files, explicit_action)
    finally:
        finish_request(st.session_state, "chat")


def _process_chat_message(raw_text: str, files=None, explicit_action=None) -> None:
    state = st.session_state
    try:
        kind, text, attachments = prepare_submission(raw_text, files)
    except AppError as error:
        st.error(error.message)
        return
    if kind == "empty":
        st.error("질문이나 테마를 입력해 주세요.")
        return
    if kind == "attachment_only":
        append_chat_message(state, "user", "", attachments=attachments)
        _say(state, "확인할 질문을 함께 입력해 주세요. 이미지·PDF 본문은 현재 읽을 수 없습니다.")
        return
    history = list(state.get("chat_messages", ()))
    append_chat_message(state, "user", text, attachments=attachments)
    state["last_submission"] = (text, [(i["name"], i["data"]) for i in attachments], explicit_action)
    try:
        historical, saved = historical_result(state, text)
        if historical:
            if saved is None:
                _say(state, "참조할 과거 결과를 확인할 수 없습니다. 종목명이나 캔버스를 선택해 주세요.")
                return
            _answer(text, saved, history, attachments)
            return
        intent = route_message(text, state.get("candidate_result"), state.get("selected_code"), history,
                               load_settings(), explicit_action=explicit_action)
        state.pop("retry_submission", None)
        if intent.action == "greeting":
            _say(state, "안녕하세요. 관심 테마나 종목을 입력하면 확인된 금융·뉴스 자료를 바탕으로 분석합니다.")
        elif intent.action in {"clarify", "unsupported"}:
            _say(state, intent.reason or ("요청한 비교나 분석 범위는 현재 지원하지 않습니다. 한 종목과 확인할 자료를 지정해 주세요." if intent.action == "unsupported" else "분석할 종목명 또는 관심 테마를 입력해 주세요."))
        elif intent.action == "discover":
            with st.status("관련 종목 후보를 탐색하고 있습니다.", expanded=False) as status:
                discovery = discover_theme_candidates(intent.theme, lambda m: status.update(label=m))
                store_candidate_discovery(state, discovery)
                if discovery.failure_reason:
                    store_analysis_error(state, discovery.failure_reason)
                    _say(state, discovery.failure_reason)
                    status.update(label="종목 후보를 확인하지 못했습니다.", state="error")
                else:
                    names = ", ".join(v.name for v in discovery.selectable_candidates)
                    _say(state, f"{discovery.theme} 관련 후보입니다: {names}. 공식 상장 정보는 확인했으며, 테마와의 사업 연관성은 별도 근거 확인이 필요합니다. 분석할 종목을 선택해 주세요.", discovery=discovery)
                    status.update(label="후보 확인 완료", state="complete")
        elif intent.action in {"lookup", "select"}:
            if intent.action == "lookup":
                stock = identify_stock(intent.company or intent.code)
                discovery = CandidateDiscoveryResult(stock.name, (stock,), now_kst())
                store_candidate_discovery(state, discovery)
                code = stock.code
            else:
                code = intent.code
            prepare_analysis_request(state, scope=intent.scope, period=intent.period,
                                     question=text if intent.scope != "all" else "", code=code)
        elif intent.action == "refresh":
            prepare_analysis_request(state, scope=intent.scope, period=intent.period,
                                     question=text if intent.scope != "all" else "", refresh=True)
        else:
            result = state.get("dashboard_result")
            if result is not None and _needs_data(result, intent.scope, text, intent.period):
                prepare_analysis_request(state, scope=intent.scope, period=intent.period,
                                         question=text, refresh=True)
            else:
                _answer(text, result, history, attachments)
    except AppError as error:
        record_failure("chat", error)
        state["retry_submission"] = state.get("last_submission")
        _say(state, error.message)
        st.error(error.message)
    except Exception as error:
        record_failure("chat", error)
        state["retry_submission"] = state.get("last_submission")
        _say(state, "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        st.error("요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")


def _needs_data(result, scope, text, period=""):
    return needs_data(result, scope, text, period, now=now_kst(),
                      dart_enabled=bool(load_settings().dart_api_key) if scope == "financials" else False)


def _answer(text, result, history, attachments=None):
    with st.spinner("질문과 근거를 확인하고 있습니다."):
        response = answer_question(text, result, history, load_settings(), attachments,
                                   st.session_state.get("candidate_result"))
        answer, evidence, follow = response
    # 일반 개념 답변에 현재 종목의 상세 버튼을 잘못 붙이지 않는다.
    linked = result if evidence else None
    append_chat_message(st.session_state, "assistant", answer, evidence=evidence, follow_up=follow,
                        target=linked.financial.stock.name if linked else "일반 설명",
                        result_id=canvas_result_id(linked) if linked else None,
                        result_target={"name": linked.financial.stock.name, "code": linked.target_code} if linked else None,
                        **response_fields(response))


def analyze_pending_selection() -> None:
    state = st.session_state
    discovery = state.get("candidate_result")
    selected_code = state.get("selected_code")
    if discovery is None or selected_code is None:
        return
    options = state.get("query_options") or QueryOptions()
    request_key = build_request_key(discovery.theme, selected_code, options)
    if state.get("active_request_key") == request_key:
        return
    if not begin_request(state, request_key):
        return
    previous = state.get("dashboard_result") or state.get("pending_previous_result")
    scope = state.pop("request_scope", "all")
    pending_question = state.pop("pending_question", "")
    state["request_status"] = "running"
    reset_selection_result(state)
    with st.status("선택 종목을 분석하고 있습니다.", expanded=False) as status:
        try:
            result = analyze_selected_stock(
                discovery.theme, discovery.candidates, selected_code, options,
                lambda message: status.update(label=message), scope=scope, previous=previous,
            )
            store_analysis_result(state, result, request_key)
            response = analysis_response(result, scope)
            summary, evidence, _ = response
            if pending_question:
                # 실패해도 수집 결과와 열기 버튼은 보존한다.
                try:
                    _answer(pending_question, result, list(state.get("chat_messages", ())))
                except AppError as error:
                    record_failure("pending_answer", error, result_id=result.result_id)
                    _say(state, f"요청한 자료는 보관했습니다. {error.message}", evidence=evidence, result_id=canvas_result_id(result))
                except Exception as error:
                    record_failure("pending_answer", error, result_id=result.result_id)
                    _say(state, "요청한 자료는 보관했습니다. 설명 처리에 문제가 발생했습니다. 다시 질문할 수 있습니다.",
                         evidence=evidence, result_id=canvas_result_id(result))
            else:
                _say(state, summary, evidence=evidence, result_id=canvas_result_id(result),
                     analysis_error=result.ai_error, news_missing=not result.news.articles, show_follow_up=False,
                     **response_fields(response))
            status.update(label="조회 결과를 표시합니다." if result.complete else "요청 처리를 마쳤습니다. 일부 자료는 미확인입니다.", state="complete")
        except AppError as error:
            record_failure("analysis", error)
            store_analysis_error(state, error.message, request_key=request_key)
            _say(state, error.message)
            status.update(label="분석을 완료하지 못했습니다.", state="error")
        except Exception as error:
            record_failure("analysis", error)
            message = "처리 중 문제가 발생했습니다. 선택 종목 재조회로 다시 시도해 주세요."
            store_analysis_error(state, message, request_key=request_key)
            _say(state, message)
            status.update(label="분석을 완료하지 못했습니다.", state="error")
        finally:
            finish_request(state, request_key)


def render_period_selector(card: dict) -> None:
    query_opts = card["result"].query_options
    current_range = query_opts.price_range if isinstance(query_opts, QueryOptions) else "3M"
    range_options = list(PRICE_RANGE_LABELS.keys())
    if current_range not in range_options:
        current_range = "3M"
    key = f"canvas_period_{card['canvas_id']}"
    if key not in st.session_state:
        st.session_state[key] = current_range
    st.selectbox(
        "새로 조회할 시세 기간",
        options=range_options,
        format_func=lambda key: PRICE_RANGE_LABELS.get(key, key),
        key=key,
        on_change=_on_range_change,
        args=(card["canvas_id"], card["stock_code"]),
    )
    st.caption("이 카드는 보관된 결과입니다. 기간을 변경하면 새 결과를 조회하며, 채팅의 ‘차트·근거 보기’로 엽니다.")


def render_guide_buttons() -> None:
    labels = {
        "find": "테마·종목 찾기",
        "risk": "위험 요인",
        "refresh": "재조회",
        "canvas": "차트·근거 보기",
    }
    keys = {
        "find": "guide_find",
        "risk": "guide_risk",
        "refresh": "refresh_selected",
        "canvas": "add_canvas",
    }
    callbacks = {
        "find": (_on_find, ()),
        "risk": (_fill_prompt, ("이 종목의 위험 요인을 현재 자료로 설명해줘",)),
        "refresh": (_on_refresh, ()),
        "canvas": (_on_add_canvas, ()),
    }
    actions = guide_actions(st.session_state)
    with st.expander("추가 작업"):
        for action in actions:
            callback, args = callbacks[action]
            st.button(labels[action], key=keys[action], on_click=callback, args=args)


def render_question_suggestions() -> None:
    if st.session_state.get("conversation_mode") == "theme_search":
        return
    prompts = suggested_prompts(st.session_state)
    if st.session_state.get("chat_messages"):
        prompts = prompts[:2]
    if prompts:
        st.caption("다음 질문" if st.session_state.get("chat_messages") else "예시 질문 · 선택 후 수정하여 보낼 수 있습니다.")
    for index, prompt in enumerate(prompts):
        st.button(
            prompt,
            key=f"suggested_prompt_{index}",
            on_click=_fill_prompt,
            args=(prompt,),
        )


def _queue_submission() -> None:
    state = st.session_state
    generation = int(state.get("composer_generation", 0))
    uploads = state.get(f"composer_files_{generation}") or []
    state["queued_submission"] = (
        state.get("composer_text", ""),
        [(item.name, bytes(item.getvalue())) for item in uploads],
        None,
    )


def _queue_theme_search() -> None:
    theme = st.session_state.get("composer_text", "")
    st.session_state["queued_submission"] = (theme, [], "discover")


def render_composer() -> None:
    mode = st.session_state.get("conversation_mode", "general")
    if mode == "theme_search":
        with st.form("theme_search_form", clear_on_submit=False, border=True):
            st.markdown("#### 종목 찾기")
            st.caption("찾고 싶은 테마를 입력하면 관련 후보를 확인합니다. 입력 전에는 외부 조회를 하지 않습니다.")
            st.text_input(
                "테마",
                key="composer_text",
                placeholder="예: 반도체, 방산, 원전, 로봇",
            )
            st.form_submit_button("테마 검색", key="composer_submit", on_click=_queue_theme_search)
            st.caption("검색 결과에서 분석할 종목을 직접 선택합니다.")
        st.button("대화로 돌아가기", key="cancel_search", on_click=lambda: st.session_state.update(conversation_mode="general"))
        return
    with st.form("composer_form", clear_on_submit=True):
        st.text_input(
            "메시지",
            key="composer_text",
            label_visibility="collapsed",
            placeholder="관심 테마, 종목 또는 금융 지표를 질문해 주세요",
        )
        st.form_submit_button("보내기", key="composer_submit", on_click=_queue_submission, type="primary")
    with st.expander("이미지·문서 첨부"):
        st.caption("TXT 내용은 답변에 참고합니다. 이미지와 PDF는 첨부 여부만 확인하며 본문은 읽지 않습니다.")
        st.file_uploader(
            "이미지 또는 문서 첨부",
            type=["png", "jpg", "jpeg", "webp", "txt", "pdf"],
            accept_multiple_files=True,
            max_upload_size=5,
            key=f"composer_files_{st.session_state.get('composer_generation', 0)}",
            help="파일당 5MB, 이미지·문서 각각 2개. txt는 읽을 수 있고 이미지·PDF 본문은 아직 읽지 않습니다.",
        )


def render_conversation() -> None:
    state = st.session_state
    messages = list(state.get("chat_messages", ()))
    if not messages:
        with st.container(key="chat_welcome"):
            st.markdown("### 어떤 종목이 궁금하십니까?")
            st.caption("관심 테마나 종목, 금융 지표를 질문해 주세요. 확인된 자료를 바탕으로 설명합니다.")
    prompt_index = -1
    discovery = state.get("candidate_result")
    for index, message in enumerate(messages):
        saved = message.get("discovery")
        if saved is not None and discovery is not None and (
            saved.theme == discovery.theme and saved.candidates == discovery.candidates
        ):
            prompt_index = index
    for index, message in enumerate(messages):
        with st.chat_message(message["role"]):
            if message.get("sent_at"):
                label = "질문 시각" if message["role"] == "user" else "답변 시각"
                st.caption(f"{label}: {time_label(message['sent_at'])}")
            if message.get("analysis_error"):
                st.error(message["analysis_error"])
            if message.get("news_missing"):
                st.info("뉴스 제목을 확보하지 못해 뉴스 기반 분석은 생성하지 않았습니다.")
            if message.get("text"):
                if message["role"] == "assistant":
                    render_answer(message)
                else:
                    st.markdown(escape_markdown(message["text"]), unsafe_allow_html=False)
            for attachment in message.get("attachments") or ():
                st.caption(f"첨부 {attachment['kind']}: {attachment['name']}")
            saved_result = get_result(state, message["result_id"]) if message.get("result_id") else None
            result_target = message.get("result_target") or (
                {"name": saved_result.financial.stock.name, "code": saved_result.target_code} if saved_result else None)
            if result_target:
                st.caption(f"분석 대상: {result_target['name']} ({result_target['code']})")
            elif message.get("target") and message["target"] != "일반 설명":
                st.caption("답변 대상: " + message["target"])
            if index == prompt_index and discovery is not None:
                render_related_candidate_buttons(discovery.candidates, state.get("selected_code"), key_prefix="msg_select")
                with st.expander("후보 상세 정보"):
                    render_candidates_table(discovery.candidates, state.get("selected_code"))
                    render_candidate_selector(discovery, state.get("selected_code"))
                if state.get("selected_code") is None:
                    st.info("분석할 종목을 선택해 주세요.")
            follow = message.get("follow_up")
            if message.get("role") == "assistant" and follow:
                st.markdown(follow)
            if message.get("result_id"):
                if saved_result is not None:
                    st.button("차트·근거 보기", key=f"message_canvas_{index}", on_click=_on_add_canvas, args=(message["result_id"],))
                else:
                    st.caption("이 답변의 상세 자료는 보관 범위를 벗어났습니다. 다시 조회하면 새로운 결과가 생성됩니다.")
                    if result_target and result_target.get("code"):
                        st.button("이 종목 재조회 질문 작성", key=f"expired_result_{index}", on_click=_fill_prompt,
                                  args=(f"{result_target['code']} 분석 자료를 다시 조회해줘",))
    if state.get("retry_submission") and not state.get("inflight_request"):
        st.button("마지막 요청 다시 시도", key="retry_last_request", on_click=_on_retry_submission)


def render_canvases() -> None:
    canvases = list(st.session_state.get("canvases") or [])
    if not canvases:
        return
    for card in canvases:
        with st.container(key=f"canvas_card_{card['canvas_id']}"):
            result = card["result"]
            st.subheader(card["title"])
            st.caption(
                f"{card['stock_name']} ({card['stock_code']}) · "
                f"조회 시각 {result.financial.retrieved_at:%Y-%m-%d %H:%M}"
            )
            st.button("캔버스 닫기", key=f"close_{card['canvas_id']}", on_click=_on_close_canvas, args=(card["canvas_id"],))
            render_period_selector(card)
            if card.get("export_error"):
                st.warning(card["export_error"])
            if not card.get("export_bytes"):
                st.button("엑셀 준비" if not card.get("export_error") else "엑셀 다시 준비", key=f"prepare_export_{card['canvas_id']}", on_click=_prepare_export, args=(card["canvas_id"],))
            render_dashboard(
                result,
                export_bytes=card.get("export_bytes"),
                export_filename=card.get("export_filename"),
                show_insights=False,
                key_prefix=card["canvas_id"],
                on_select=lambda code, card_id=card["canvas_id"]: select_canvas_candidate(st.session_state, card_id, code),
            )


def main() -> None:
    st.set_page_config(page_title="테마주 인사이트 리포트", layout="wide")
    st.html(WORKSPACE_CSS)
    with st.container(key="app_header"):
        title, reset = st.columns([5, 1])
        title.title("테마주 인사이트 리포트")
        reset.button("새 대화 시작", key="clear_results", on_click=reset_all_state, args=(st.session_state,))
        st.caption("테마와 종목을 대화로 탐색합니다. 분석 답변에서 ‘차트·근거 보기’를 누르면 상세 자료가 열립니다.")
    panel_height = panel_content_height()
    has_conversation = bool(st.session_state.get("chat_messages") or st.session_state.get("queued_submission") or st.session_state.get("queued_prompt"))
    canvases = list(st.session_state.get("canvases") or [])
    if canvases:
        chat_panel, data_panel = st.columns([2, 3], gap="large")
        chat_context = chat_panel
    else:
        chat_context = st.container()
        data_panel = None
    with chat_context:
        st.subheader("AI와 대화")
        # 첫 진입은 내용만큼만 사용한다. 대화가 시작된 뒤에만 스크롤 높이를 둔다.
        message_slot = (st.container(height=panel_height, key="chat_scroll", autoscroll=True)
                        if has_conversation else st.container(key="chat_scroll"))
        controls_slot = st.container(key="chat_controls")
    if data_panel is not None:
        with data_panel:
            st.subheader("차트·근거")
            canvas_slot = st.container(
                height=panel_height + 200,
                key=canvas_scroll_key(st.session_state.get("canvas_scroll_generation", 0)),
                autoscroll=False,
            )
    with message_slot:
        queued = st.session_state.pop("queued_prompt", None)
        submission = st.session_state.pop("queued_submission", None)
        if submission is not None:
            process_chat_message(*submission)
            st.session_state["composer_generation"] = int(st.session_state.get("composer_generation", 0)) + 1
        elif queued:
            process_chat_message(queued)
        analyze_pending_selection()
        render_conversation()
        if "latest_error" in st.session_state:
            st.error(st.session_state["latest_error"])
    with controls_slot:
        if st.session_state.get("chat_messages") or st.session_state.get("conversation_mode") == "theme_search":
            render_state_context()
        render_question_suggestions()
        render_composer()
        render_guide_buttons()
    if data_panel is not None:
        with canvas_slot:
            render_canvases()


if __name__ == "__main__":
    main()
