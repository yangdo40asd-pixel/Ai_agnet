"""선택 종목 대시보드 렌더러 모듈.

상단 4개 핵심 지표(주가·PER·PBR·ROE)와 보조 지표(EPS·BPS),
일별 주가·거래량 차트, 기업 실적·재무 요약/상세, 관련 종목 비교,
AI 인사이트·뉴스, 엑셀 다운로드 영역을 책임별로 분리해 표시한다.
"""

from decimal import Decimal
import pandas as pd
import streamlit as st

from src.data.news import safe_news_url
from src.models import AnalysisResult, MetricValue, Statement
from src.ui.charts import (
    build_annual_performance_figure,
    build_balance_sheet_figure,
    build_mini_sparkline_figure,
    build_price_volume_figure,
    build_quarter_performance_figure,
)
from src.ui.formatting import (
    format_change_summary,
    format_eok,
    format_multiple,
    format_per_share_krw,
    format_percent,
    format_price,
    format_timestamp,
)
from src.ui.state import select_candidate


def show_statement(title: str, statement: Statement | None):
    st.markdown(f"**{title}**")
    if statement is None:
        st.caption("관련 뉴스 제목 근거가 부족해 이 항목을 생성하지 않았습니다.")
        return
    st.write(statement.text)
    if statement.news_ids:
        refs = ", ".join(f"뉴스 {news_id}" for news_id in statement.news_ids)
        st.caption(f"근거: {refs}")
    if statement.fact_ids:
        fact_refs = ", ".join(statement.fact_ids)
        st.caption(f"재무 근거: {fact_refs}")


def _resolve_roe_metric(result: AnalysisResult) -> MetricValue | None:
    if result.financial_ratios and result.financial_ratios.roe is not None:
        return result.financial_ratios.roe
    if result.financial.roe_metric is not None:
        return result.financial.roe_metric
    return None


def render_metrics(result: AnalysisResult):
    """상단 4카드(주가·PER·PBR·ROE)와 보조 지표(EPS·BPS) 및 기준 시각·출처를 표시한다."""
    financial = result.financial
    roe_metric = _resolve_roe_metric(result)
    roe_value = roe_metric.value if (roe_metric and roe_metric.status == "ok") else None

    st.subheader(f"핵심 금융 지표 — {financial.stock.name} ({financial.stock.code})")
    top_cols = st.columns(4)
    top_cols[0].metric("주가", format_price(financial.price))
    top_cols[1].metric("PER", format_multiple(financial.per))
    top_cols[2].metric("PBR", format_multiple(financial.pbr))
    top_cols[3].metric("ROE", format_percent(roe_value))

    with st.expander("보조 지표 (주당 가치: EPS · BPS)", expanded=True):
        aux_cols = st.columns(2)
        aux_cols[0].metric("EPS (주당순이익)", format_per_share_krw(financial.eps))
        aux_cols[1].metric("BPS (주당순자산)", format_per_share_krw(financial.bps))
        if financial.eps_metric:
            eps_meta = financial.eps_metric
            eps_desc = f"EPS 단위: {eps_meta.unit} · 기준: {eps_meta.period or '미확인'} · 출처: {eps_meta.source} ({eps_meta.raw_field})"
            if eps_meta.reason:
                eps_desc += f" · 안내: {eps_meta.reason}"
            st.caption(eps_desc)
        if financial.bps_metric:
            bps_meta = financial.bps_metric
            bps_desc = f"BPS 단위: {bps_meta.unit} · 기준: {bps_meta.period or '미확인'} · 출처: {bps_meta.source} ({bps_meta.raw_field})"
            if bps_meta.reason:
                bps_desc += f" · 안내: {bps_meta.reason}"
            st.caption(bps_desc)

    st.caption(
        f"금융 출처: {financial.source} · 조회 시각: {format_timestamp(financial.retrieved_at)} · "
        f"가격 자료 시각: {format_timestamp(financial.price_at)}"
    )
    if financial.per_eps is not None and financial.per_period_end:
        st.caption(
            f"PER 계산 기준: Yahoo Finance 제공 주가와 최근 12개월 희석 EPS"
            f"({financial.per_eps:,.0f}원, {financial.per_period_end} 종료)로 계산"
        )
    if financial.pbr_metric:
        pbr_meta = financial.pbr_metric
        pbr_caption = f"PBR 기준: {pbr_meta.period or '미확인'} · 출처: {pbr_meta.source}"
        if pbr_meta.formula:
            pbr_caption += f" · 산식: {pbr_meta.formula}"
        if pbr_meta.reason:
            pbr_caption += f" ({pbr_meta.reason})"
        st.caption(pbr_caption)
    if roe_metric and roe_metric.status == "ok":
        roe_basis = "공식 지표 제공" if roe_metric.basis == "provided" else f"자체 계산({roe_metric.formula})"
        st.caption(
            f"ROE 기준: {roe_metric.period or '기간 미확인'} · 구분: {roe_basis} · 출처: {roe_metric.source}"
        )
    else:
        roe_reason = roe_metric.reason if (roe_metric and roe_metric.reason) else "재무제표/주요지표 미수집 또는 해당 기간 값 없음"
        st.caption(f"ROE 안내: 정보 없음 ({roe_reason})")

    for warning in financial.warnings:
        st.warning(warning)
    if financial.stock.ticker:
        st.link_button("금융 자료 출처 열기", f"https://finance.yahoo.com/quote/{financial.stock.ticker}/")


def render_price_chart(result: AnalysisResult):
    """선택 종목의 일별 주가·거래량 상하 패널 차트를 표시한다."""
    st.subheader("일별 주가·거래량 추이")
    history = result.price_history
    if history is None:
        st.info("표시할 일별 주가·거래량 이력이 없습니다.")
        return
    if history.status == "failed":
        st.warning(history.message or "일별 주가·거래량 이력을 불러오지 못했습니다.")
        return
    if history.status != "ok" or not history.bars:
        st.info(history.message or "선택한 기간의 일별 시세 이력이 없습니다.")
        return

    fig = build_price_volume_figure(result.financial.stock, history)
    if fig is None:
        st.info("차트를 구성할 수 있는 유효한 원화 시세 이력이 없습니다.")
        return

    st.plotly_chart(fig, width="stretch", key=f"price_vol_chart_{result.financial.stock.code}_{history.range_key}")
    first_date = history.bars[0].trade_date
    last_date = history.bars[-1].trade_date
    adj_text = "수정주가" if history.adjusted else "무수정 시세(auto_adjust=False)"
    st.caption(
        f"시세 이력 출처: {history.source} · 기간: {first_date} ~ {last_date} ({len(history.bars)}거래일) · "
        f"통화: {history.currency} · 시간대: {history.timezone} · 기준: {adj_text} · "
        f"조회 시각: {format_timestamp(history.retrieved_at)}"
    )


def render_financial_summary(result: AnalysisResult):
    """기업 실적 차트·재무 요약표 및 상세 재무제표(BS/CF/비율/공시링크)를 표시한다."""
    st.subheader("기업 실적 및 재무 분석")
    dart_status = result.section_status.get("dart", "empty")
    has_financials = bool(
        result.annual_summaries
        or result.quarterly_summaries
        or result.financial_statements
        or result.financial_ratios
    )

    if not has_financials:
        if dart_status == "failed":
            st.warning("기업 재무제표(OpenDART) 조회에 실패했습니다. 주가·뉴스 자료는 정상 표시됩니다.")
        else:
            st.info("공시된 기업 재무제표 자료가 없거나 아직 조회되지 않았습니다. 임의의 추정 실적을 표시하지 않습니다.")
        return

    if result.annual_summaries:
        annual_fig = build_annual_performance_figure(result.financial.stock, result.annual_summaries)
        if annual_fig is not None:
            st.plotly_chart(
                annual_fig,
                width="stretch",
                key=f"annual_perf_chart_{result.financial.stock.code}",
            )

        summary_rows = []
        for item in result.annual_summaries:
            summary_rows.append(
                {
                    "사업연도": f"{item.bsns_year}년",
                    "연결구분": item.fs_div,
                    "매출액(억원)": format_eok(item.revenue),
                    "영업이익(억원)": format_eok(item.operating_income),
                    "당기순이익(억원)": format_eok(item.net_income),
                    "영업이익률(%)": format_percent(item.operating_margin),
                    "순이익률(%)": format_percent(item.net_margin),
                    "부채비율(%)": format_percent(item.debt_ratio),
                    "ROE(%)": format_percent(item.roe),
                }
            )
        st.markdown("**연도별 손익·주요 비율 요약 (단위: 억원, %)**")
        st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")
        fs_divs = ", ".join(sorted({item.fs_div for item in result.annual_summaries if item.fs_div}))
        st.caption(
            f"재무 출처: OpenDART · 기준 구분: {fs_divs or 'CFS'} · 금액 단위: 억원(원 단위 공시 금액을 표시 시점에 변환)"
        )

    if result.quarterly_summaries:
        q_fig = build_quarter_performance_figure(result.financial.stock, result.quarterly_summaries)
        if q_fig is not None:
            st.plotly_chart(
                q_fig,
                width="stretch",
                key=f"quarter_perf_chart_{result.financial.stock.code}",
            )

    if result.financial_ratios:
        ratios = result.financial_ratios
        ratio_rows = []
        for label, metric in (
            ("ROE (자기자본이익률)", ratios.roe),
            ("영업이익률", ratios.operating_margin),
            ("순이익률", ratios.net_margin),
            ("부채비율", ratios.debt_ratio),
        ):
            if metric is None:
                continue
            ratio_rows.append(
                {
                    "지표": label,
                    "값": format_percent(metric.value) if metric.status == "ok" else "정보 없음",
                    "기준 기간": metric.period or "-",
                    "산출 구분": "공식 제공" if metric.basis == "provided" else "자체 계산",
                    "산식/근거": metric.formula or metric.raw_field or "-",
                    "해석/상태": metric.reason or ("정상" if metric.status == "ok" else metric.status),
                }
            )
        if ratio_rows:
            st.markdown(f"**수익성·안정성 비율 ({ratios.bsns_year}년 {ratios.reprt_code} · {ratios.fs_div or '기준 확인'})**")
            st.dataframe(pd.DataFrame(ratio_rows), hide_index=True, width="stretch")
            if ratios.interpretation_notes:
                for note in ratios.interpretation_notes:
                    st.caption(f"비율 해석 안내: {note}")

    with st.expander("상세 재무제표 (재무상태표 · 현금흐름표 · 공시 원문)", expanded=False):
        if result.annual_summaries:
            bs_fig = build_balance_sheet_figure(result.financial.stock, result.annual_summaries)
            if bs_fig is not None:
                st.plotly_chart(
                    bs_fig,
                    width="stretch",
                    key=f"bs_chart_{result.financial.stock.code}",
                )
            detail_rows = []
            for item in result.annual_summaries:
                detail_rows.append(
                    {
                        "사업연도": f"{item.bsns_year}년",
                        "연결구분": item.fs_div,
                        "자산총계(억원)": format_eok(item.total_assets),
                        "부채총계(억원)": format_eok(item.total_liabilities),
                        "자본총계(억원)": format_eok(item.total_equity),
                        "영업활동현금흐름(억원)": format_eok(item.operating_cash_flow),
                        "투자활동현금흐름(억원)": format_eok(item.investing_cash_flow),
                        "재무활동현금흐름(억원)": format_eok(item.financing_cash_flow),
                        "접수번호": item.rcept_no or "-",
                    }
                )
            st.dataframe(pd.DataFrame(detail_rows), hide_index=True, width="stretch")
            st.caption("현금흐름표의 음수(−)는 현금 유출을 의미하며 단순 적자나 오류가 아닙니다.")
            for item in result.annual_summaries:
                if item.rcept_no:
                    dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.rcept_no}"
                    st.link_button(
                        f"{item.bsns_year}년 공시 원문 보기 ({item.rcept_no})",
                        dart_url,
                    )
        else:
            st.caption("상세 재무상태표·현금흐름표 데이터가 없습니다.")


def render_related_stocks(result: AnalysisResult, on_select=None):
    """관련 종목 후보 가격·등락·미니 차트 및 동일 선택 동작 버튼을 표시한다."""
    st.subheader("관련 종목 후보 및 빠른 전환")
    st.caption("후보 순서는 투자 추천 순위가 아닙니다. 등락은 동일 조정 기준 일별 종가 비교(+/−)로 표시합니다.")

    summary_by_code = {
        item.stock.code: item
        for item in result.related_stocks
        if item.stock and item.stock.code
    }
    selected_code = result.financial.stock.code
    cols = st.columns(max(1, len(result.candidates[:3])))

    for idx, candidate in enumerate(result.candidates[:3]):
        with cols[idx]:
            is_current = bool(candidate.code and candidate.code == selected_code)
            badge = "대표 종목 (선택됨)" if is_current else ("선택 가능" if candidate.selectable else "선택 불가")
            st.markdown(f"**{candidate.name}** ({candidate.code or '미확인'})")
            st.caption(f"시장: {candidate.market or '미확인'} · 상태: {badge}")

            summary = summary_by_code.get(candidate.code) if candidate.code else None
            if summary and summary.status == "ok" and summary.price is not None:
                st.write(f"종가: **{format_price(summary.price)}**")
                st.write(f"등락: `{format_change_summary(summary.change, summary.change_pct)}`")
                st.caption(summary.comparison_basis)
                spark_fig = build_mini_sparkline_figure(summary)
                if spark_fig is not None:
                    st.plotly_chart(
                        spark_fig,
                        width="stretch",
                        key=f"spark_{candidate.code}",
                    )
            elif not candidate.selectable:
                st.caption(f"안내: {candidate.reason or '상장 종목 미확인'}")
            elif summary and summary.message:
                st.caption(summary.message)

            if candidate.selectable and candidate.code:
                button_label = (
                    f"{candidate.name} ({candidate.code}) · 현재 선택됨"
                    if is_current
                    else f"{candidate.name} ({candidate.code}) 분석 보기"
                )
                clicked = st.button(
                    button_label,
                    key=f"result_related_{candidate.code}",
                    disabled=is_current,
                    on_click=select_candidate,
                    args=(st.session_state, candidate.code),
                    width="stretch",
                )
                if clicked and on_select is not None:
                    on_select(candidate.code)
            else:
                st.button(
                    f"{candidate.name} (선택 불가)",
                    key=f"result_related_disabled_{candidate.name}",
                    disabled=True,
                    width="stretch",
                )


def render_news(result: AnalysisResult):
    """선택 종목 관련 뉴스 목록과 원문 이동 링크를 표시한다."""
    news = result.news
    st.subheader("관련 뉴스")
    st.caption(
        f"뉴스 출처: {news.source} · 조회 시각: {format_timestamp(news.retrieved_at)} · "
        "기사 본문은 수집하지 않고 제목·발행 시각·원문 링크만 사용합니다."
    )
    if news.status != "ok" and news.message:
        st.warning(news.message)
    for article in news.articles:
        with st.container():
            st.markdown(f"**뉴스 {article.id}. {article.title}**")
            st.caption(
                f"발행 시각: {article.published_at or '확인되지 않음'} · "
                f"원문 사이트: {article.publisher_domain or '확인되지 않음'}"
            )
            url = safe_news_url(article.url)
            if url:
                st.link_button("원문 이동", url)
            else:
                st.caption("원문 링크가 확인되지 않았습니다.")
    if not news.articles:
        st.info(news.message or "표시할 뉴스가 없습니다.")


def render_insights(result: AnalysisResult):
    """AI 리포트 항목별 결과와 뉴스·재무 근거 번호를 표시한다."""
    st.subheader("AI 종합 분석 리포트")
    if result.commentary_error:
        st.error(result.commentary_error)
        return
    commentary = result.commentary
    if commentary is None:
        st.warning("AI 설명이 준비되지 않았습니다.")
        return

    st.markdown("**테마 동향**")
    if commentary.theme_trend:
        for idx, item in enumerate(commentary.theme_trend, start=1):
            show_statement(f"동향 {idx}", item)
    elif not result.news.articles:
        st.info("뉴스 제목을 확보하지 못해 테마 동향을 설명하지 않습니다.")
    else:
        st.info("검증된 AI 동향 설명이 없습니다. 아래 뉴스 제목과 원문을 확인해 주세요.")

    st.markdown("**선택 종목 금융 지표 설명**")
    st.write(commentary.stock_comment)

    if commentary.financial_commentary:
        st.markdown("**기업 재무제표 근거 설명**")
        for idx, item in enumerate(commentary.financial_commentary, start=1):
            show_statement(f"재무 분석 {idx}", item)

    show_statement("기회 요인", commentary.opportunity)
    show_statement("위험 요인", commentary.risk)
    show_statement("종합 의견", commentary.summary)


def render_export(
    result: AnalysisResult,
    export_bytes: bytes | None = None,
    export_filename: str | None = None,
):
    """선택 종목 분석 자료 엑셀 다운로드 영역을 표시한다."""
    st.subheader("분석 결과 엑셀 다운로드")
    stock = result.financial.stock
    price_range = result.query_options.price_range if result.query_options else "3M"
    st.caption(
        f"대상 종목: {stock.name} ({stock.code}) · 시세 기간: {price_range} · "
        f"생성 기준 시각: {format_timestamp(result.financial.retrieved_at)}"
    )
    if export_bytes and export_filename:
        st.download_button(
            label=f"📊 {stock.name} ({stock.code}) 분석 엑셀 다운로드 (.xlsx)",
            data=export_bytes,
            file_name=export_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"download_xlsx_{result.result_id or stock.code}",
            width="stretch",
        )
        st.caption(f"파일명: `{export_filename}` (화면과 동일한 분석 결과 객체에서 생성됨)")
    else:
        st.caption("엑셀 파일 생성 모듈 연결 시 현재 선택 종목의 통합 XLSX 다운로드가 활성화됩니다.")


def render_dashboard(
    result: AnalysisResult,
    *,
    on_select=None,
    export_bytes: bytes | None = None,
    export_filename: str | None = None,
    show_insights: bool = True,
):
    """우측 패널의 전체 선택 종목 대시보드를 순서대로 렌더링한다."""
    if result.complete:
        st.success("선택한 종목의 데이터 수집과 AI 분석이 완료되었습니다.")
    else:
        st.info("확인된 데이터만 먼저 표시합니다. 아래 안내에서 누락 또는 실패 항목을 확인해 주세요.")

    render_metrics(result)
    render_price_chart(result)
    render_financial_summary(result)
    render_related_stocks(result, on_select=on_select)

    if show_insights:
        render_insights(result)
    render_news(result)

    render_export(result, export_bytes=export_bytes, export_filename=export_filename)
