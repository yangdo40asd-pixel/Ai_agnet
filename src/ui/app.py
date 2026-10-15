"""사용자 입력, 조회 결과, 근거와 누락 안내를 표시하는 화면."""

import re
import sys
from pathlib import Path

import streamlit as st

# Streamlit이 파일 경로로 실행해도 프로젝트의 src 모듈을 찾을 수 있게 한다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models import AnalysisResult, AppError, Statement
from src.pipeline import analyze_theme


def escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>$~])", r"\\\1", text)


def price_label(value: float | None) -> str:
    if value is None:
        return "정보 없음"
    return f"{value:,.2f}".rstrip("0").rstrip(".") + "원"


def per_label(value: float | None) -> str:
    return "정보 없음" if value is None else f"{value:,.2f}배"


def show_statement(statement: Statement) -> None:
    st.markdown(escape_markdown(statement.text))
    st.caption("근거 뉴스: " + ", ".join(str(item) for item in statement.news_ids) + " · 제목 기반 AI 해석")


def show_result(result: AnalysisResult) -> None:
    financial = result.financial
    target = financial.stock
    commentary = result.commentary
    if result.complete:
        st.success("자료 조회와 AI 설명 생성이 완료되었습니다.")
    elif commentary is None:
        st.warning("AI 설명을 완성하지 못했습니다. 조회된 자료만 표시합니다.")
    else:
        st.warning("누락 정보 또는 지표 해석 시 확인할 사항이 있습니다. 아래 안내와 출처를 함께 확인해 주세요.")
    if result.ai_error:
        st.error(result.ai_error)
    for warning in financial.warnings:
        st.warning(warning)
    if result.news.status != "ok":
        st.warning(result.news.message)

    st.subheader("1. 테마 동향")
    if commentary and commentary.theme_trend:
        for statement in commentary.theme_trend:
            show_statement(statement)
    elif not result.news.articles:
        st.info("뉴스 제목을 확보하지 못해 테마 동향을 설명하지 않습니다.")
    else:
        st.info("검증된 AI 동향 설명이 없습니다. 아래 뉴스 제목과 원문을 확인해 주세요.")

    st.subheader("2. 관련 종목 후보")
    st.dataframe([
        {"후보": index, "종목명": stock.name, "종목코드": stock.code or "미확인",
         "시장": stock.market or "미확인",
         "상장 확인": "확인" if stock.verified else "미확인",
         "분석 대상": "대표 종목" if index == 1 else "후보",
         "안내": stock.reason or "상장 종목명·코드 확인"}
        for index, stock in enumerate(result.candidates, 1)
    ], hide_index=True, width="stretch")
    st.caption("AI가 제안한 순서이며 투자 우선순위가 아닙니다. 초기 버전은 첫 번째 후보만 분석합니다. 상장 확인은 테마 연관성을 보증하지 않습니다.")

    st.subheader("3. 대표 종목 분석")
    st.markdown(f"**{escape_markdown(target.name)} · {target.code} · {target.market}**")
    price_column, per_column = st.columns(2)
    price_column.metric("조회된 주가", price_label(financial.price))
    per_column.metric("PER (최근 실적 기준)", per_label(financial.per))
    st.caption("숫자는 조회 자료를 기준으로 표시하며, 직접 계산한 값은 계산 근거를 별도로 표시합니다. 소수점 둘째 자리까지 표시합니다.")
    if financial.per_eps is not None:
        st.caption(
            f"PER는 제공자의 PER 항목이 없어 조회 주가 ÷ 최근 12개월 희석 EPS로 계산했습니다. "
            f"희석 EPS: {financial.per_eps:,.4f}원 · 실적 기간 종료일: {financial.per_period_end} · "
            "출처: Yahoo Finance 최근 12개월 손익계산서. 예상 실적 기준 PER와 다릅니다."
        )
    st.caption(f"자료 출처: {financial.source} · 조회 시각: {financial.retrieved_at:%Y-%m-%d %H:%M:%S} KST")
    if financial.price_at:
        st.caption(f"가격 자료 시각: {financial.price_at:%Y-%m-%d %H:%M:%S} KST · 조회 시각과 다르며, 실시간 여부를 보장하지 않습니다.")
    else:
        st.caption("가격 자료 시각: 확인되지 않음")
    st.link_button("금융 자료 출처 열기", f"https://finance.yahoo.com/quote/{target.ticker}/")
    st.caption("상장 종목 확인: FinanceDataReader의 KRX 목록.")
    if financial.per_period_end is None:
        st.caption("제공된 PER의 정확한 실적 기준일은 현재 응답에서 별도로 확보하지 않습니다.")
    if commentary:
        st.markdown(escape_markdown(commentary.stock_comment))

    st.subheader("4. 핵심 인사이트")
    if commentary and commentary.opportunity:
        for label, statement in (("기회", commentary.opportunity), ("위험", commentary.risk), ("종합 의견", commentary.summary)):
            st.markdown(f"**{label}**")
            show_statement(statement)
    else:
        st.info("근거를 연결한 AI 인사이트가 없습니다. 조회 자료만으로 판단을 단정하지 않습니다.")

    st.subheader("관련 뉴스와 출처")
    order = "발행일순" if result.news.sort == "date" else "관련도순"
    st.caption(f"{result.news.source} · {order} · 조회 시각: {result.news.retrieved_at:%Y-%m-%d %H:%M:%S} KST")
    st.caption("기사 제목만 수집합니다. 아래 AI 근거 번호는 해당 뉴스 번호와 연결됩니다.")
    for article in result.news.articles:
        st.markdown(f"**뉴스 {article.id}. {escape_markdown(article.title)}**")
        st.caption(f"발행 시각: {article.published_at or '확인되지 않음'} · 원문 사이트: {article.publisher_domain or '확인되지 않음'}")
        if article.url:
            st.link_button("기사 원문 / 제공 링크 열기", article.url)
        else:
            st.caption("기사 링크가 제공되지 않았습니다.")
    if not result.news.articles:
        st.info(result.news.message or "표시할 뉴스가 없습니다.")
    st.caption("AI 해석의 뉴스 번호와 숫자 형식은 코드로 검사하지만, 문장의 의미와 기사와의 연관성을 완전히 검증하는 것은 아닙니다.")


def main() -> None:
    st.set_page_config(page_title="테마주 인사이트 리포트", layout="wide")
    st.title("테마주 인사이트 리포트")
    st.write("관심 테마를 입력하면 관련 종목 후보, 주가·PER, 뉴스와 AI 설명을 함께 보여줍니다.")
    st.caption("예: 반도체 테마주 분석해줘 · 조회 가능한 자료와 뉴스 제목을 바탕으로 설명합니다.")
    if st.button("현재 결과 지우기"):
        for key in ("latest_theme", "latest_result", "latest_error"):
            st.session_state.pop(key, None)
    theme = st.chat_input("관심 테마를 입력하세요")
    if theme is not None:
        st.session_state["latest_theme"] = theme
        st.session_state.pop("latest_result", None)
        st.session_state.pop("latest_error", None)
        with st.status("분석을 준비하고 있습니다.", expanded=True) as status:
            try:
                result = analyze_theme(theme, lambda message: status.update(label=message))
                st.session_state["latest_result"] = result
                status.update(label="결과를 표시합니다." if result.complete else "누락·오류 안내와 조회 자료를 표시합니다.",
                              state="complete" if result.complete else "error", expanded=False)
            except AppError as error:
                st.session_state["latest_error"] = error.message
                status.update(label="분석을 완료하지 못했습니다.", state="error", expanded=False)
            except Exception:
                st.session_state["latest_error"] = "처리 중 예상하지 못한 문제가 발생했습니다. 설정을 확인하고 다시 시도해 주세요."
                status.update(label="분석을 완료하지 못했습니다.", state="error", expanded=False)
    if "latest_theme" in st.session_state:
        with st.chat_message("user"):
            st.markdown(escape_markdown(st.session_state["latest_theme"]))
    if "latest_error" in st.session_state:
        st.error(st.session_state["latest_error"])
    if "latest_result" in st.session_state:
        show_result(st.session_state["latest_result"])


if __name__ == "__main__":
    main()
