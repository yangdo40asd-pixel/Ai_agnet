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
from src.data.news import safe_news_url
from src.agents.chat import answer_question, normalize_message, route_message
from src.config import load_settings
from src.models import AnalysisResult, AppError, CandidateDiscoveryResult, QueryOptions, StockCandidate
from src.pipeline import analyze_selected_stock, discover_theme_candidates
from src.ui.dashboard import render_dashboard, render_insights
from src.ui.state import (
    build_request_key,
    append_chat_message,
    ensure_export_bundle,
    reset_all_state,
    reset_selection_result,
    select_candidate,
    store_analysis_error,
    store_analysis_result,
    store_candidate_discovery,
    trigger_refresh,
    update_query_options,
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


def _on_range_change() -> None:
    chosen_range = st.session_state.get("price_range_selector")
    if isinstance(chosen_range, str) and chosen_range in PRICE_RANGE_LABELS:
        update_query_options(st.session_state, price_period=chosen_range)


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
    query_opts = st.session_state.get("query_options")
    current_range = query_opts.price_range if isinstance(query_opts, QueryOptions) else "3M"
    range_options = list(PRICE_RANGE_LABELS.keys())
    if current_range not in range_options:
        current_range = "3M"
    st.session_state["price_range_selector"] = current_range
    st.selectbox(
        "일별 시세 차트 기간",
        options=range_options,
        format_func=lambda key: PRICE_RANGE_LABELS.get(key, key),
        key="price_range_selector",
        on_change=_on_range_change,
    )
    if selected_code in code_to_stock:
        st.button(
            "선택 종목 재조회",
            key="refresh_selected",
            on_click=trigger_refresh,
            args=(st.session_state,),
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


def show_result(result: AnalysisResult, *, show_candidates_table: bool = True) -> None:
    selected_code = result.target_code
    if show_candidates_table:
        render_candidates_table(result.candidates, selected_code)
    export_bytes, export_filename = ensure_export_bundle(st.session_state, result)
    render_dashboard(
        result,
        export_bytes=export_bytes,
        export_filename=export_filename,
        show_insights=False,
    )


def process_chat_message(raw_text: str) -> None:
    state = st.session_state
    try:
        text = normalize_message(raw_text)
    except AppError as error:
        st.error(error.message)
        return
    history = list(state.get("chat_messages", ()))
    append_chat_message(state, "user", text)
    try:
        intent = route_message(
            text, state.get("candidate_result"), state.get("selected_code"), history, load_settings()
        )
        if intent.action == "greeting":
            append_chat_message(state, "assistant", "안녕하세요. 관심 테마나 종목을 알려 주세요. 분석 후에는 지표와 뉴스에 관해 이어서 질문할 수 있습니다.")
        elif intent.action == "clarify":
            append_chat_message(state, "assistant", "분석할 테마 또는 후보 종목 하나를 알려 주세요. 종목을 선택하면 그 종목에 대해 이어서 질문할 수 있습니다.")
        elif intent.action == "discover":
            reset_all_state(state, keep_conversation=True)
            with st.status("관련 종목 후보를 탐색하고 있습니다.", expanded=False) as status:
                discovery = discover_theme_candidates(intent.theme, lambda message: status.update(label=message))
                store_candidate_discovery(state, discovery)
                if discovery.failure_reason:
                    store_analysis_error(state, discovery.failure_reason)
                    append_chat_message(state, "assistant", discovery.failure_reason)
                    status.update(label="종목 후보를 확인하지 못했습니다.", state="error")
                else:
                    names = ", ".join(s.name for s in discovery.selectable_candidates)
                    append_chat_message(state, "assistant", f"{discovery.theme} 관련 후보: {names}. 분석할 종목을 선택해 주세요. 종목명을 채팅으로 입력해도 됩니다.")
                    status.update(label="관련 종목 후보를 확인했습니다.", state="complete")
        elif intent.action == "select":
            select_candidate(state, intent.code)
            append_chat_message(state, "assistant", "선택한 종목의 분석 결과를 확인하겠습니다.")
        elif intent.action == "refresh":
            trigger_refresh(state)
            append_chat_message(state, "assistant", "현재 종목의 자료를 다시 조회하겠습니다.")
        else:
            result = state.get("dashboard_result")
            with st.spinner("질문과 분석 자료를 확인하고 있습니다."):
                answer, evidence = answer_question(text, result, history, load_settings())
            append_chat_message(state, "assistant", answer, evidence=evidence,
                                target=result.financial.stock.name if result else "일반 설명")
    except AppError as error:
        # 대화 응답 실패는 이미 조회한 종목과 엑셀을 지우지 않는다.
        append_chat_message(state, "assistant", error.message)
        st.error(error.message)
    except Exception:
        message = "대화를 처리하지 못했습니다. 잠시 후 다시 질문해 주세요."
        append_chat_message(state, "assistant", message)
        st.error(message)


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
    reset_selection_result(state)
    with st.status("선택 종목을 분석하고 있습니다.", expanded=False) as status:
        try:
            result = analyze_selected_stock(
                discovery.theme, discovery.candidates, selected_code, options,
                lambda message: status.update(label=message),
            )
            store_analysis_result(state, result, request_key)
            append_chat_message(
                state, "assistant",
                f"{result.financial.stock.name} ({result.target_code}) 분석 결과입니다. 지표나 위험 요인에 관해 이어서 질문해 주세요.",
                report=result,
            )
            status.update(label="조회 결과를 표시합니다.", state="complete" if result.complete else "error")
        except AppError as error:
            store_analysis_error(state, error.message, request_key=request_key)
            append_chat_message(state, "assistant", error.message)
            status.update(label="분석을 완료하지 못했습니다.", state="error")
        except Exception:
            message = "처리 중 문제가 발생했습니다. 선택 종목 재조회로 다시 시도해 주세요."
            store_analysis_error(state, message, request_key=request_key)
            append_chat_message(state, "assistant", message)
            status.update(label="분석을 완료하지 못했습니다.", state="error")


def render_conversation() -> None:
    for message in st.session_state.get("chat_messages", ()):
        with st.chat_message(message["role"]):
            st.markdown(escape_markdown(message["text"]))
            if message.get("target"):
                st.caption("답변 대상: " + message["target"])
            if message.get("report") is not None:
                report = message["report"]
                st.caption(f"분석 기준: {report.theme} · {report.financial.stock.name} · {report.financial.retrieved_at:%Y-%m-%d %H:%M}")
                render_insights(report)
                with st.expander("이 리포트의 뉴스·재무 근거"):
                    for article in report.news.articles:
                        st.markdown(escape_markdown(f"뉴스 {article.id}: {article.title}"))
                        url = safe_news_url(article.url)
                        if url:
                            st.link_button("리포트 근거 원문", url)
                    for fact in report.financial_facts:
                        st.text(f"{fact.fact_id} · {fact.item}: {fact.display_value} {fact.unit} · {fact.period} · {fact.fs_div} · {fact.source}")
            for item in message.get("evidence", ()):
                st.markdown(escape_markdown(f"[{item['id']}] {item['text']}"))
                st.caption(" · ".join(str(item[key]) for key in ("source", "period", "fs_div", "published_at", "retrieved_at") if item.get(key)))
                url = safe_news_url(item.get("url"))
                if url:
                    st.link_button("답변 근거 원문", url)


def main() -> None:
    st.set_page_config(page_title="테마주 인사이트 리포트", layout="wide")
    st.title("테마주 인사이트 리포트")
    st.write("관심 테마를 이야기하고, 선택한 종목의 지표와 뉴스에 관해 이어서 질문하세요.")
    st.caption("예: 반도체 테마주 분석해줘 → 종목 선택 → 이 종목의 위험 요인은? · 대화는 현재 세션에서 최근 40개까지 보관합니다.")
    if st.button("새 대화 시작", key="clear_results"):
        reset_all_state(st.session_state)
    prompt = st.chat_input("테마·종목 또는 궁금한 내용을 입력하세요")
    if prompt is not None:
        process_chat_message(prompt)
    analyze_pending_selection()
    chat_panel, data_panel = st.columns([1, 1.4], gap="large")
    with chat_panel:
        st.subheader("AI와 대화")
        render_conversation()
        discovery = st.session_state.get("candidate_result")
        if discovery is not None:
            render_candidates_table(discovery.candidates, st.session_state.get("selected_code"))
            render_candidate_selector(discovery, st.session_state.get("selected_code"))
    with data_panel:
        if "latest_error" in st.session_state and "dashboard_result" not in st.session_state:
            st.error(st.session_state["latest_error"])
        if "dashboard_result" in st.session_state:
            show_result(st.session_state["dashboard_result"], show_candidates_table=False)
        elif discovery is not None and "latest_error" not in st.session_state:
            st.info("분석할 종목을 선택해 주세요. 후보 선택창 또는 아래 후보 버튼을 눌러 상세 분석을 시작합니다.")
            render_related_candidate_buttons(discovery.candidates, None, key_prefix="waiting_related")


if __name__ == "__main__":
    main()
