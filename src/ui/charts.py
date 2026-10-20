"""Plotly 기반 주가·거래량 차트, 후보 미니 차트 및 기업 재무 차트 생성 모듈.

차트 생성 함수 안에서 외부 API를 호출하지 않으며, 검증·정규화된 모델 자료만 사용한다.
"""

from decimal import Decimal
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.data.history import PRICE_RANGE_LABELS
from src.models import (
    AnnualFinancialSummary,
    PriceHistory,
    QuarterlyFinancialSummary,
    RelatedStockSummary,
    StockCandidate,
)


def _to_eok(amount_won: int | float | Decimal | None) -> float | None:
    if isinstance(amount_won, bool) or amount_won is None:
        return None
    try:
        return round(float(Decimal(str(amount_won)) / Decimal("100000000")), 2)
    except Exception:
        return None


def build_price_volume_figure(
    stock: StockCandidate,
    history: PriceHistory,
) -> go.Figure | None:
    """일별 종가 선(상단)과 거래량 막대(하단)를 공유 날짜축의 상하 패널로 구성한다."""
    if (
        history is None
        or history.status != "ok"
        or not history.bars
        or history.currency != "KRW"
        or (stock.code and history.code != stock.code)
    ):
        return None

    dates = [bar.trade_date for bar in history.bars]
    opens = [bar.open for bar in history.bars]
    highs = [bar.high for bar in history.bars]
    lows = [bar.low for bar in history.bars]
    closes = [bar.close for bar in history.bars]
    volumes = [bar.volume for bar in history.bars]
    customdata = list(zip(opens, highs, lows, volumes))

    range_label = PRICE_RANGE_LABELS.get(history.range_key, history.range_key)
    adj_label = "수정주가" if history.adjusted else "무수정 시세(auto_adjust=False)"
    title_text = (
        f"{stock.name} ({stock.code}) 일별 주가·거래량 추이 "
        f"[{range_label} · {history.currency} · {adj_label}]"
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.68, 0.32],
        subplot_titles=("일별 종가 (단위: 원, KRW)", "일별 거래량 (단위: 주)"),
    )

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=closes,
            mode="lines+markers",
            name="종가 (원)",
            customdata=customdata,
            line={"color": "#1f77b4", "width": 2},
            marker={"size": 4},
            hovertemplate=(
                "거래일: %{x}<br>"
                "시가: %{customdata[0]:,.0f}원<br>"
                "고가: %{customdata[1]:,.0f}원<br>"
                "저가: %{customdata[2]:,.0f}원<br>"
                "종가: %{y:,.0f}원<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=dates,
            y=volumes,
            name="거래량 (주)",
            marker_color="#7f8c8d",
            hovertemplate="거래일: %{x}<br>거래량: %{y:,.0f}주<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.update_yaxes(title_text="주가 (원)", tickformat=",", row=1, col=1)
    fig.update_yaxes(title_text="거래량 (주)", tickformat=",", row=2, col=1)
    # 실제 거래일 문자열만 범주형으로 표시해 휴장일 공백이나 가짜 봉을 만들지 않는다.
    fig.update_xaxes(type="category", tickangle=-30, row=1, col=1)
    fig.update_xaxes(title_text="거래일 (KST)", type="category", tickangle=-30, row=2, col=1)
    fig.update_layout(
        title={"text": title_text, "font": {"size": 15}},
        height=460,
        margin={"l": 55, "r": 25, "t": 65, "b": 45},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1.0},
        hovermode="x unified",
    )
    return fig


def build_mini_sparkline_figure(summary: RelatedStockSummary) -> go.Figure | None:
    """검증된 실제 일별 종가 이력이 2개 이상 있을 때만 미니 차트를 생성한다."""
    if (
        summary is None
        or summary.status != "ok"
        or len(summary.sparkline_closes) < 2
        or len(summary.sparkline_dates) != len(summary.sparkline_closes)
    ):
        return None

    dates = list(summary.sparkline_dates)
    closes = list(summary.sparkline_closes)
    first_val = closes[0]
    last_val = closes[-1]
    line_color = "#d62728" if last_val > first_val else ("#1f77b4" if last_val < first_val else "#7f8c8d")

    fig = go.Figure(
        data=[
            go.Scatter(
                x=dates,
                y=closes,
                mode="lines",
                name=f"{summary.stock.name} 종가",
                line={"color": line_color, "width": 2},
                hovertemplate="거래일: %{x}<br>종가: %{y:,.0f}원<extra></extra>",
            )
        ]
    )
    fig.update_xaxes(visible=False, type="category")
    fig.update_yaxes(visible=False)
    fig.update_layout(
        height=85,
        margin={"l": 4, "r": 4, "t": 4, "b": 4},
        showlegend=False,
    )
    return fig


def build_annual_performance_figure(
    stock: StockCandidate,
    summaries: tuple[AnnualFinancialSummary, ...],
    *,
    include_net_income: bool = True,
) -> go.Figure | None:
    """연도별 매출액·영업이익·당기순이익 비교 막대 차트 (단위: 억원)."""
    if not summaries:
        return None
    years = [item.bsns_year for item in summaries]
    fs_divs = {item.fs_div for item in summaries if item.fs_div}
    fs_label = "/".join(sorted(fs_divs)) if fs_divs else "CFS"
    revenues = [_to_eok(item.revenue) for item in summaries]
    op_incomes = [_to_eok(item.operating_income) for item in summaries]
    net_incomes = [_to_eok(item.net_income) for item in summaries]

    if all(v is None for v in revenues + op_incomes + net_incomes):
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=revenues,
            name="매출액 (억원)",
            marker_color="#2b5c8f",
            hovertemplate="%{x}년 매출액: %{y:,.1f}억원<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=op_incomes,
            name="영업이익 (억원)",
            marker_color="#3690c0",
            hovertemplate="%{x}년 영업이익: %{y:,.1f}억원<extra></extra>",
        )
    )
    if include_net_income:
        fig.add_trace(
            go.Bar(
                x=years,
                y=net_incomes,
                name="당기순이익 (억원)",
                marker_color="#67a9cf",
                hovertemplate="%{x}년 당기순이익: %{y:,.1f}억원<extra></extra>",
            )
        )

    fig.update_xaxes(title_text="사업연도", type="category")
    fig.update_yaxes(title_text="금액 (단위: 억원, KRW)", tickformat=",")
    fig.update_layout(
        title={
            "text": f"{stock.name} ({stock.code}) 연간 실적 추이 [{fs_label} · 단위: 억원 · 출처: OpenDART]",
            "font": {"size": 15},
        },
        barmode="group",
        height=360,
        margin={"l": 55, "r": 25, "t": 60, "b": 45},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1.0},
    )
    return fig


def build_quarter_performance_figure(
    stock: StockCandidate,
    quarters: tuple[QuarterlyFinancialSummary, ...],
    *,
    include_net_income: bool = True,
) -> go.Figure | None:
    """당분기(3개월) 기준이 검증된 분기 실적 비교 차트 (단위: 억원)."""
    verified_quarters = [q for q in quarters if q.period_type == "quarter_3m"]
    if not verified_quarters:
        return None

    labels = [q.period_label for q in verified_quarters]
    fs_divs = {q.fs_div for q in verified_quarters if q.fs_div}
    fs_label = "/".join(sorted(fs_divs)) if fs_divs else "CFS"
    revenues = [_to_eok(q.revenue) for q in verified_quarters]
    op_incomes = [_to_eok(q.operating_income) for q in verified_quarters]
    net_incomes = [_to_eok(q.net_income) for q in verified_quarters]

    if all(v is None for v in revenues + op_incomes + net_incomes):
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=revenues,
            name="매출액 (당분기, 억원)",
            marker_color="#2b5c8f",
            hovertemplate="%{x} 매출액: %{y:,.1f}억원<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=op_incomes,
            name="영업이익 (당분기, 억원)",
            marker_color="#3690c0",
            hovertemplate="%{x} 영업이익: %{y:,.1f}억원<extra></extra>",
        )
    )
    if include_net_income:
        fig.add_trace(
            go.Bar(
                x=labels,
                y=net_incomes,
                name="당기순이익 (당분기, 억원)",
                marker_color="#67a9cf",
                hovertemplate="%{x} 당기순이익: %{y:,.1f}억원<extra></extra>",
            )
        )

    fig.update_xaxes(title_text="분기 (당분기 3개월 기준)", type="category")
    fig.update_yaxes(title_text="금액 (단위: 억원, KRW)", tickformat=",")
    fig.update_layout(
        title={
            "text": f"{stock.name} ({stock.code}) 분기별 실적 비교 (당분기 3개월) [{fs_label} · 단위: 억원 · 출처: OpenDART]",
            "font": {"size": 15},
        },
        barmode="group",
        height=340,
        margin={"l": 55, "r": 25, "t": 60, "b": 45},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1.0},
    )
    return fig


def build_balance_sheet_figure(
    stock: StockCandidate,
    summaries: tuple[AnnualFinancialSummary, ...],
) -> go.Figure | None:
    """연도별 자산총계·부채총계·자본총계 비교 차트 (단위: 억원)."""
    if not summaries:
        return None
    years = [item.bsns_year for item in summaries]
    fs_divs = {item.fs_div for item in summaries if item.fs_div}
    fs_label = "/".join(sorted(fs_divs)) if fs_divs else "CFS"
    assets = [_to_eok(item.total_assets) for item in summaries]
    liabilities = [_to_eok(item.total_liabilities) for item in summaries]
    equities = [_to_eok(item.total_equity) for item in summaries]

    if all(v is None for v in assets + liabilities + equities):
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=assets,
            name="자산총계 (억원)",
            marker_color="#4a6fe3",
            hovertemplate="%{x}년 기말 자산총계: %{y:,.1f}억원<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=liabilities,
            name="부채총계 (억원)",
            marker_color="#e5873a",
            hovertemplate="%{x}년 기말 부채총계: %{y:,.1f}억원<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=years,
            y=equities,
            name="자본총계 (억원)",
            marker_color="#2ca02c",
            hovertemplate="%{x}년 기말 자본총계: %{y:,.1f}억원<extra></extra>",
        )
    )

    fig.update_xaxes(title_text="사업연도 (기말 잔액 기준)", type="category")
    fig.update_yaxes(title_text="금액 (단위: 억원, KRW)", tickformat=",")
    fig.update_layout(
        title={
            "text": f"{stock.name} ({stock.code}) 연도별 자산·부채·자본 구조 [{fs_label} · 단위: 억원 · 출처: OpenDART]",
            "font": {"size": 15},
        },
        barmode="group",
        height=350,
        margin={"l": 55, "r": 25, "t": 60, "b": 45},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1.0},
    )
    return fig
