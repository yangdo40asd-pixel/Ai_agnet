"""이용 허용 범위 내 일별 주가·거래량 이력(OHLCV) 수집·정규화 및 관련 후보 요약."""

from datetime import datetime

import pandas as pd

from src.data.stock import finite_number
from src.models import (
    AppError,
    KST,
    PriceBar,
    PriceHistory,
    RelatedStockSummary,
    StockCandidate,
    now_kst,
)

PRICE_RANGE_MAP: dict[str, str] = {
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "3Y": "3y",
    "5Y": "5y",
}

PRICE_RANGE_LABELS: dict[str, str] = {
    "1M": "최근 1개월",
    "3M": "최근 3개월",
    "6M": "최근 6개월",
    "1Y": "최근 1년",
    "3Y": "최근 3년",
    "5Y": "최근 5년",
}

REQUIRED_OHLCV_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


def resolve_range_key(range_key: object) -> str:
    if isinstance(range_key, str) and range_key.strip().upper() in PRICE_RANGE_MAP:
        return range_key.strip().upper()
    return "3M"


def _extract_ticker_columns(frame: pd.DataFrame, expected_ticker: str) -> pd.DataFrame | None:
    """MultiIndex 열이 있을 때 요청 종목과 일치하는 열만 추출한다."""
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame
    expected = expected_ticker.upper()
    for level in range(frame.columns.nlevels):
        level_values = {str(val).upper() for val in frame.columns.get_level_values(level)}
        if level_values & ({"OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"}):
            continue
        if expected not in level_values:
            return None
        sliced = frame.xs(expected_ticker, axis=1, level=level, drop_level=True)
        return sliced if isinstance(sliced, pd.DataFrame) else None
    return None


def normalize_price_history(
    stock: StockCandidate,
    frame: object,
    range_key: str = "3M",
    *,
    currency: str = "KRW",
    timezone_name: str = "Asia/Seoul",
    adjusted: bool = False,
    source: str = "Yahoo Finance (yfinance)",
    retrieved_at: datetime | None = None,
) -> PriceHistory:
    """일별 OHLCV DataFrame을 검증·정규화한다. 휴장일을 임의 값으로 채우지 않는다."""
    if not stock.verified or not stock.ticker or not stock.code:
        raise AppError("stock_unconfirmed", "상장 여부와 시장이 확인된 종목만 시세 이력을 조회할 수 있습니다.")
    normalized_range = resolve_range_key(range_key)
    fetched_at = retrieved_at or now_kst()

    if currency != "KRW":
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency=str(currency or ""),
            timezone=timezone_name,
            adjusted=adjusted,
            range_key=normalized_range,
            source=source,
            retrieved_at=fetched_at,
            status="failed",
            message="가격 이력의 통화가 원화로 확인되지 않아 차트를 표시하지 않습니다.",
        )

    if frame is None or not isinstance(frame, pd.DataFrame):
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency="KRW",
            timezone=timezone_name,
            adjusted=adjusted,
            range_key=normalized_range,
            source=source,
            retrieved_at=fetched_at,
            status="empty",
            message="선택한 기간의 일별 시세 이력이 없습니다.",
        )

    unwrapped = _extract_ticker_columns(frame, stock.ticker)
    if unwrapped is None:
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency="KRW",
            timezone=timezone_name,
            adjusted=adjusted,
            range_key=normalized_range,
            source=source,
            retrieved_at=fetched_at,
            status="failed",
            message="시세 이력의 종목코드가 선택 종목과 일치하지 않습니다.",
        )

    if unwrapped.empty:
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency="KRW",
            timezone=timezone_name,
            adjusted=adjusted,
            range_key=normalized_range,
            source=source,
            retrieved_at=fetched_at,
            status="empty",
            message="선택한 기간의 일별 시세 이력이 없습니다.",
        )

    if not REQUIRED_OHLCV_COLUMNS.issubset(set(unwrapped.columns)):
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency="KRW",
            timezone=timezone_name,
            adjusted=adjusted,
            range_key=normalized_range,
            source=source,
            retrieved_at=fetched_at,
            status="failed",
            message="일별 시세 이력의 필수 열(시가·고가·저가·종가·거래량)을 확인하지 못했습니다.",
        )

    ref_date = fetched_at.astimezone(KST).date()
    by_date: dict[str, PriceBar] = {}

    for raw_idx, row in unwrapped.iterrows():
        try:
            ts = pd.Timestamp(raw_idx)
        except (ValueError, TypeError):
            continue
        if pd.isna(ts):
            continue
        if ts.tzinfo is not None:
            trade_dt = ts.tz_convert(KST).date()
        else:
            trade_dt = ts.date()
        # 미래 날짜의 잘못된 행은 제외한다.
        if trade_dt > ref_date:
            continue

        open_val = finite_number(row["Open"])
        high_val = finite_number(row["High"])
        low_val = finite_number(row["Low"])
        close_val = finite_number(row["Close"])
        vol_val = finite_number(row["Volume"])

        if (
            open_val is None or open_val <= 0
            or high_val is None or high_val <= 0
            or low_val is None or low_val <= 0
            or close_val is None or close_val <= 0
            or vol_val is None or vol_val < 0
        ):
            continue
        if high_val < max(open_val, close_val, low_val) or low_val > min(open_val, close_val, high_val):
            continue

        trade_date_str = trade_dt.strftime("%Y-%m-%d")
        by_date[trade_date_str] = PriceBar(
            trade_date=trade_date_str,
            open=open_val,
            high=high_val,
            low=low_val,
            close=close_val,
            volume=int(round(vol_val)),
        )

    sorted_bars = tuple(by_date[d] for d in sorted(by_date.keys()))
    if not sorted_bars:
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency="KRW",
            timezone=timezone_name,
            adjusted=adjusted,
            range_key=normalized_range,
            source=source,
            retrieved_at=fetched_at,
            status="empty",
            message="유효한 일별 주가·거래량 데이터가 없습니다.",
        )

    return PriceHistory(
        code=stock.code,
        ticker=stock.ticker,
        bars=sorted_bars,
        currency="KRW",
        timezone=timezone_name,
        adjusted=adjusted,
        range_key=normalized_range,
        source=source,
        retrieved_at=fetched_at,
        status="ok",
        message="",
    )


def fetch_price_history(
    stock: StockCandidate,
    range_key: str = "3M",
    *,
    currency: str = "KRW",
) -> PriceHistory:
    """Yahoo Finance에서 일별 무수정 시세(auto_adjust=False)를 조회한다."""
    import yfinance as yf

    if not stock.verified or not stock.ticker or not stock.code:
        raise AppError("stock_unconfirmed", "상장 여부와 시장이 확인된 종목만 시세 이력을 조회할 수 있습니다.")
    normalized_range = resolve_range_key(range_key)
    yf_period = PRICE_RANGE_MAP[normalized_range]
    fetched_at = now_kst()
    try:
        ticker = yf.Ticker(stock.ticker)
        frame = ticker.history(period=yf_period, interval="1d", auto_adjust=False)
    except Exception:
        return PriceHistory(
            code=stock.code,
            ticker=stock.ticker,
            bars=(),
            currency=currency,
            timezone="Asia/Seoul",
            adjusted=False,
            range_key=normalized_range,
            source="Yahoo Finance (yfinance)",
            retrieved_at=fetched_at,
            status="failed",
            message="일별 주가·거래량 이력 조회에 실패했습니다.",
        )
    return normalize_price_history(
        stock,
        frame,
        normalized_range,
        currency=currency,
        timezone_name="Asia/Seoul",
        adjusted=False,
        source="Yahoo Finance (yfinance)",
        retrieved_at=fetched_at,
    )


def build_related_stock_summary(
    stock: StockCandidate,
    history: PriceHistory | None = None,
) -> RelatedStockSummary:
    """검증된 동일 조정 기준(일별 무수정 종가) 이력에서 후보 요약·등락·미니 차트 계열을 구성한다."""
    if not stock.selectable:
        return RelatedStockSummary(
            stock=stock,
            status="unverified",
            message=stock.reason or "상장 종목 미확인",
        )
    if (
        history is None
        or history.code != stock.code
        or history.currency != "KRW"
        or history.status != "ok"
        or not history.bars
    ):
        msg = history.message if (history and history.message) else "일별 시세 요약 정보가 없습니다."
        return RelatedStockSummary(
            stock=stock,
            status=history.status if history else "empty",
            message=msg,
        )

    recent_bars = history.bars[-20:]
    last_bar = recent_bars[-1]
    spark_dates = tuple(b.trade_date for b in recent_bars)
    spark_closes = tuple(b.close for b in recent_bars)
    adj_label = "수정 종가" if history.adjusted else "무수정 종가"

    if len(recent_bars) >= 2:
        prev_bar = recent_bars[-2]
        change = finite_number(last_bar.close - prev_bar.close)
        change_pct = (
            finite_number((change / prev_bar.close) * 100.0)
            if (change is not None and prev_bar.close > 0)
            else None
        )
        basis = f"일별 종가 비교 ({prev_bar.trade_date} → {last_bar.trade_date}, {adj_label} 기준)"
    else:
        change = None
        change_pct = None
        basis = f"비교 가능한 직전 거래일 없음 ({last_bar.trade_date} {adj_label})"

    return RelatedStockSummary(
        stock=stock,
        price=last_bar.close,
        change=change,
        change_pct=change_pct,
        comparison_basis=basis,
        sparkline_dates=spark_dates,
        sparkline_closes=spark_closes,
        currency="KRW",
        source=history.source,
        status="ok",
        message="",
    )


def fetch_related_stock_summaries(
    candidates: tuple[StockCandidate, ...],
    selected_code: str | None = None,
    selected_history: PriceHistory | None = None,
    *,
    fetch_unselected: bool = False,
) -> tuple[RelatedStockSummary, ...]:
    """최대 3개 후보의 요약 정보를 구성한다. 미선택 후보에 대해 DART·뉴스·AI를 호출하지 않는다."""
    summaries: list[RelatedStockSummary] = []
    for candidate in candidates[:3]:
        if not candidate.selectable:
            summaries.append(build_related_stock_summary(candidate, None))
            continue
        if selected_code and candidate.code == selected_code and selected_history is not None:
            summaries.append(build_related_stock_summary(candidate, selected_history))
            continue
        if fetch_unselected:
            cand_history = fetch_price_history(candidate, "1M")
            summaries.append(build_related_stock_summary(candidate, cand_history))
        else:
            summaries.append(
                RelatedStockSummary(
                    stock=candidate,
                    status="ready",
                    message="종목 선택 시 상세 시세·차트를 조회합니다.",
                )
            )
    return tuple(summaries)
