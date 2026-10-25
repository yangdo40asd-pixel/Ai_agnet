"""후보 확인과 주가·PER 조회. 종목을 임의로 대체하지 않는다."""

import math
import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from numbers import Real

import pandas as pd

from src.models import AppError, FinancialData, KST, MetricValue, StockCandidate, now_kst
from src.formatting import format_multiple, format_per_share_krw, format_price


def normalize_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).split())


def validate_candidate_names(names: object) -> tuple[str, ...]:
    if not isinstance(names, list) or len(names) != 3:
        raise AppError("candidate_format", "AI가 종목 후보 세 개를 올바르게 제안하지 못했습니다. 테마를 다시 입력해 주세요.")
    if any(not isinstance(name, str) or not name.strip() or len(name) > 80 for name in names):
        raise AppError("candidate_format", "종목 후보에 비어 있거나 잘못된 이름이 있습니다. 다시 입력해 주세요.")
    cleaned = tuple(normalize_name(name) for name in names)
    if len(set(name.casefold() for name in cleaned)) != 3:
        raise AppError("candidate_duplicate", "AI가 같은 종목을 중복 제안했습니다. 테마를 다시 입력해 주세요.")
    return cleaned


def yahoo_ticker(code: str, market: str) -> str | None:
    suffix = {"KOSPI": "KS", "KOSDAQ": "KQ", "KOSDAQ GLOBAL": "KQ"}.get(market.upper())
    return f"{code}.{suffix}" if suffix else None


def load_listing():
    import FinanceDataReader as fdr

    try:
        listing = fdr.StockListing("KRX")
    except Exception:
        raise AppError("listing_failed", "상장 종목 목록을 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
    if not isinstance(listing, pd.DataFrame) or listing.empty or not {"Name", "Code", "Market"}.issubset(listing.columns):
        raise AppError("listing_format", "상장 종목 목록의 형식을 확인하지 못했습니다. 이번 분석을 중단합니다.")
    return listing


def resolve_candidates(names: tuple[str, ...], listing) -> tuple[StockCandidate, ...]:
    official_names = listing["Name"].map(lambda value: normalize_name(str(value)).casefold())
    results = []
    for name in names:
        rows = listing[official_names == normalize_name(name).casefold()]
        if len(rows) != 1:
            reason = "상장 종목명과 일치하지 않음" if rows.empty else "같은 이름이 여러 개여서 확인 필요"
            results.append(StockCandidate(name=name, reason=reason))
            continue
        row = rows.iloc[0]
        code = str(row["Code"]).strip().upper()
        # 숫자 코드는 앞의 0을 보존한다. 잘못된 float 문자열은 변환하지 않는다.
        if re.fullmatch(r"\d{1,6}", code):
            code = code.zfill(6)
        if not re.fullmatch(r"[A-Z0-9]{6}", code):
            results.append(StockCandidate(name=name, reason="종목코드 형식 확인 필요"))
            continue
        market = str(row["Market"]).strip().upper()
        ticker = yahoo_ticker(code, market)
        results.append(StockCandidate(
            name=str(row["Name"]), code=code, market=market, ticker=ticker,
            reason="" if ticker else "현재 금융 조회 경로에서 지원하지 않는 시장",
        ))
    return tuple(results)


def require_target(candidates: tuple[StockCandidate, ...]) -> StockCandidate:
    if not candidates or not candidates[0].verified:
        raise AppError("stock_unconfirmed", "첫 번째 후보를 실제 상장 종목으로 확인하지 못했습니다. 테마를 다시 입력해 주세요.")
    if not candidates[0].ticker or candidates[0].reason:
        raise AppError("market_unsupported", "첫 번째 후보의 시장은 현재 주가 조회에서 지원하지 않습니다. 테마를 다시 입력해 주세요.")
    return candidates[0]


def resolve_selected_target(
    candidates: tuple[StockCandidate, ...], selected_code: object
) -> StockCandidate:
    """사용자가 선택한 후보가 현재 테마 후보 목록에 속하며 조회 가능한 상장 종목인지 확인한다."""
    if not candidates:
        raise AppError("stock_unconfirmed", "확인된 종목 후보가 없습니다. 테마를 다시 입력해 주세요.")
    if not isinstance(selected_code, str) or not selected_code.strip():
        raise AppError("selection_required", "분석할 종목을 선택해 주세요.")
    cleaned = selected_code.strip()
    code_upper = cleaned.upper()
    matched = [
        candidate for candidate in candidates
        if (candidate.code is not None and candidate.code.upper() == code_upper)
        or normalize_name(candidate.name).casefold() == normalize_name(cleaned).casefold()
    ]
    if not matched:
        raise AppError("selection_invalid", "선택한 종목이 현재 테마의 후보 목록에 없습니다. 후보 목록에서 다시 선택해 주세요.")
    target = matched[0]
    prefix = "첫 번째 후보" if target == candidates[0] else "선택한 후보"
    if not target.verified:
        raise AppError("stock_unconfirmed", f"{prefix}({target.name})를 실제 상장 종목으로 확인하지 못했습니다. 다른 후보를 선택하거나 테마를 다시 입력해 주세요.")
    if not target.ticker or target.reason:
        raise AppError("market_unsupported", f"{prefix}({target.name})의 시장은 현재 주가 조회에서 지원하지 않습니다.")
    return target


def candidate_options(theme: str, candidates: tuple[StockCandidate, ...], listing) -> tuple[str, ...]:
    """재제안용 공식 명칭 참고 목록. 문자열 관련성은 테마 연관성을 보증하지 않는다."""
    names = [str(row.Name) for row in listing.itertuples()
             if yahoo_ticker(str(row.Code), str(row.Market))]
    confirmed = [stock.name for stock in candidates if stock.verified and not stock.reason]
    terms = [term for term in re.findall(r"[A-Za-z가-힣0-9]+", theme)
             if len(term) >= 2 and term not in {"테마주", "관련주", "분석해줘", "분석해주세요", "종목"}]
    prefixes = [normalize_name(name)[:2] for name in confirmed]
    theme_matches = [name for name in names if any(term.casefold() in name.casefold() for term in terms)]
    name_matches = [name for name in names if any(name.startswith(prefix) for prefix in prefixes)]
    options = tuple(dict.fromkeys(confirmed + theme_matches + name_matches))[:60]
    return options if len(options) >= 3 else ()


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _build_additional_metrics(
    info: dict[str, object],
    price: float | None,
    retrieved_at: datetime,
) -> tuple[MetricValue, MetricValue, MetricValue]:
    """EPS·BPS·PBR 지표를 원필드·통화·기준 기간·산식 메타와 함께 구성한다."""
    quote_is_krw = info.get("currency") == "KRW"
    fin_currency = info.get("financialCurrency")
    fin_is_krw = quote_is_krw and (fin_currency is None or fin_currency == "KRW")
    source = "Yahoo Finance (yfinance)"

    if not fin_is_krw:
        currency_reason = "통화가 원화로 확인되지 않아 표시하지 않습니다."
        return (
            MetricValue(
                name="EPS", value=None, unit="주당 원", currency="KRW", source=source,
                raw_field="trailingEps", retrieved_at=retrieved_at, status="missing",
                basis="provided", reason=currency_reason,
            ),
            MetricValue(
                name="BPS", value=None, unit="주당 원", currency="KRW", source=source,
                raw_field="bookValue", retrieved_at=retrieved_at, status="missing",
                basis="provided", reason=currency_reason,
            ),
            MetricValue(
                name="PBR", value=None, unit="배", currency="", source=source,
                raw_field="priceToBook", retrieved_at=retrieved_at, status="missing",
                basis="provided", reason=currency_reason,
            ),
        )

    raw_eps = finite_number(info.get("trailingEps"))
    if raw_eps is not None:
        eps_reason = "주당순이익이 0 이하(적자 또는 손익분기)입니다." if raw_eps <= 0 else ""
        eps_metric = MetricValue(
            name="EPS", value=raw_eps, unit="주당 원", currency="KRW", source=source,
            raw_field="trailingEps", period="최근 12개월(TTM)", retrieved_at=retrieved_at,
            status="ok", basis="provided", reason=eps_reason,
        )
    else:
        eps_metric = MetricValue(
            name="EPS", value=None, unit="주당 원", currency="KRW", source=source,
            raw_field="trailingEps", retrieved_at=retrieved_at, status="missing",
            basis="provided", reason="EPS 정보가 없습니다.",
        )

    raw_bps = finite_number(info.get("bookValue"))
    if raw_bps is not None:
        bps_reason = "주당순자산이 0 이하입니다." if raw_bps <= 0 else ""
        bps_metric = MetricValue(
            name="BPS", value=raw_bps, unit="주당 원", currency="KRW", source=source,
            raw_field="bookValue", period="최근 분기 기말", retrieved_at=retrieved_at,
            status="ok", basis="provided", reason=bps_reason,
        )
    else:
        bps_metric = MetricValue(
            name="BPS", value=None, unit="주당 원", currency="KRW", source=source,
            raw_field="bookValue", retrieved_at=retrieved_at, status="missing",
            basis="provided", reason="BPS 정보가 없습니다.",
        )

    raw_pbr = finite_number(info.get("priceToBook"))
    # 결측이나 잘못된 0값을 0배로 표시하지 않는다.
    if raw_pbr is not None and raw_pbr == 0:
        raw_pbr = None

    if raw_pbr is not None:
        pbr_reason = "PBR가 음수(자본잠식 등)입니다. 단순 저평가로 해석할 수 없습니다." if raw_pbr < 0 else ""
        pbr_metric = MetricValue(
            name="PBR", value=raw_pbr, unit="배", currency="", source=source,
            raw_field="priceToBook", period="최근 분기 기말 기준", retrieved_at=retrieved_at,
            status="ok", basis="provided", reason=pbr_reason,
        )
    elif price is not None and price > 0 and raw_bps is not None and raw_bps > 0:
        calc_pbr = finite_number(price / raw_bps)
        if calc_pbr is not None and calc_pbr > 0:
            pbr_metric = MetricValue(
                name="PBR", value=calc_pbr, unit="배", currency="",
                source="Yahoo Finance (yfinance) 원자료 기반 자체 계산",
                raw_field="regularMarketPrice / bookValue",
                period="현재 주가 / 최근 분기 BPS", retrieved_at=retrieved_at,
                status="ok", basis="calculated", formula="주가 / BPS",
                reason="제공 PBR가 없어 동일 원화 기준 주가와 BPS로 계산했습니다.",
            )
        else:
            pbr_metric = MetricValue(
                name="PBR", value=None, unit="배", currency="", source=source,
                raw_field="priceToBook", retrieved_at=retrieved_at, status="missing",
                basis="provided", reason="PBR 정보가 없습니다.",
            )
    else:
        pbr_reason = (
            "BPS가 0 이하여서 PBR를 계산하지 않습니다."
            if (raw_bps is not None and raw_bps <= 0)
            else "PBR 정보가 없습니다."
        )
        pbr_metric = MetricValue(
            name="PBR", value=None, unit="배", currency="", source=source,
            raw_field="priceToBook", retrieved_at=retrieved_at, status="missing",
            basis="provided", reason=pbr_reason,
        )

    return eps_metric, bps_metric, pbr_metric


def financial_from_info(stock: StockCandidate, info: object) -> FinancialData:
    """외부 응답을 검증한다. 조회 시각과 가격 자료 시각은 별도로 보관한다."""
    if not isinstance(info, dict) or not info:
        raise AppError("finance_empty", "금융 서비스가 종목 자료를 반환하지 않았습니다. 이번 분석을 중단합니다.")
    symbol = info.get("symbol")
    if not isinstance(symbol, str) or symbol.upper() != stock.ticker:
        raise AppError("finance_identity", "금융 자료의 종목코드를 확인하지 못했습니다. 이번 분석을 중단합니다.")
    warnings = []
    market_price = finite_number(info.get("regularMarketPrice"))
    if market_price is not None and market_price <= 0:
        market_price = None
    price = market_price if market_price is not None else finite_number(info.get("currentPrice"))
    if price is not None and price <= 0:
        price = None
    if info.get("currency") != "KRW":
        price = None
        warnings.append("가격 통화가 원화로 확인되지 않아 주가를 표시하지 않습니다.")
    if price is None:
        warnings.append("주가 정보가 없습니다.")
    per = finite_number(info.get("trailingPE"))
    if per is None:
        warnings.append("PER 정보가 없습니다.")
    elif per <= 0:
        warnings.append("PER가 0 이하입니다. 단순히 저평가라고 해석할 수 없습니다.")
    price_at = None
    timestamp = finite_number(info.get("regularMarketTime"))
    # regularMarketTime을 currentPrice의 시각으로 임의 연결하지 않는다.
    if price is not None and market_price is not None and timestamp is not None and timestamp > 0:
        try:
            price_at = datetime.fromtimestamp(timestamp, KST)
        except (ValueError, OverflowError, OSError):
            pass
    if price_at is None:
        warnings.append("가격 자료의 기준 시각을 확인하지 못했습니다.")
    if price is None and per is None:
        raise AppError("finance_missing", "주가와 PER를 모두 확인하지 못했습니다. 이번 분석을 중단합니다.")
    retrieved_at = now_kst()
    eps_metric, bps_metric, pbr_metric = _build_additional_metrics(info, price, retrieved_at)
    return FinancialData(
        stock=stock, price=price, per=per, retrieved_at=retrieved_at,
        price_at=price_at, warnings=tuple(warnings),
        pbr_metric=pbr_metric, eps_metric=eps_metric, bps_metric=bps_metric,
    )


def fetch_financial(stock: StockCandidate) -> FinancialData:
    import yfinance as yf

    if not stock.verified or not stock.ticker:
        raise AppError("stock_unconfirmed", "상장 여부와 시장이 확인된 종목만 조회할 수 있습니다.")
    try:
        ticker = yf.Ticker(stock.ticker)
        info = ticker.get_info()
    except Exception:
        raise AppError("finance_failed", "주가·PER 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.") from None
    financial = financial_from_info(stock, info)
    if (
        (financial.per is not None and financial.eps is not None)
        or financial.price is None
        or info.get("financialCurrency") != "KRW"
    ):
        return financial
    try:
        income = ticker.get_income_stmt(freq="trailing")
    except Exception:
        return financial
    if financial.per is None:
        financial = supplement_trailing_per(financial, income)
    if financial.eps is None:
        financial = supplement_trailing_eps(financial, income)
    return financial


def _extract_latest_diluted_eps(
    financial: FinancialData, income: object
) -> tuple[float, pd.Timestamp] | None:
    if (
        not isinstance(income, pd.DataFrame)
        or income.empty
        or "DilutedEPS" not in income.index
        or not income.index.is_unique
        or not income.columns.is_unique
    ):
        return None
    try:
        periods = [(pd.Timestamp(column), column) for column in income.columns]
        # 가장 최신 기간의 값이 없다고 이전 기간으로 몰래 대체하지 않는다.
        if any(pd.isna(date) for date, _ in periods):
            return None
        date, column = max(periods, key=lambda item: item[0].value)
        reference = financial.price_at or financial.retrieved_at
        if date.date() > reference.date():
            return None
        eps = finite_number(income.loc["DilutedEPS", column])
        if eps is None:
            return None
        return eps, date
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def supplement_trailing_eps(financial: FinancialData, income: object) -> FinancialData:
    """info에 trailingEps가 없을 때 최근 12개월 희석 EPS로 독립 EPS 지표를 보완한다."""
    if financial.eps is not None:
        return financial
    extracted = _extract_latest_diluted_eps(financial, income)
    if extracted is None:
        return financial
    eps, date = extracted
    period_str = date.strftime("%Y-%m-%d")
    eps_reason = (
        f"최근 12개월 희석 EPS({period_str} 종료)가 0 이하입니다."
        if eps <= 0
        else f"최근 12개월 희석 EPS({period_str} 종료) 기준입니다."
    )
    eps_metric = MetricValue(
        name="EPS", value=eps, unit="주당 원", currency="KRW",
        source="Yahoo Finance (yfinance)", raw_field="DilutedEPS",
        period=f"최근 12개월(TTM, {period_str} 종료)",
        retrieved_at=financial.retrieved_at, status="ok",
        basis="provided", reason=eps_reason,
    )
    return replace(financial, eps_metric=eps_metric)


def supplement_trailing_per(financial: FinancialData, income: object) -> FinancialData:
    """최근 12개월 희석 EPS로만 보완한다. 예상 PER·연간 EPS를 대신 쓰지 않는다."""
    if financial.per is not None or financial.price is None:
        return financial
    extracted = _extract_latest_diluted_eps(financial, income)
    if extracted is None:
        return financial
    eps, date = extracted
    if eps == 0:
        return financial
    try:
        per = finite_number(financial.price / eps)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return financial
    if per is None:
        return financial
    warnings = [x for x in financial.warnings if x != "PER 정보가 없습니다."]
    if per <= 0:
        warnings.append("최근 12개월 희석 EPS가 음수여서 PER가 음수입니다. 단순히 저평가라고 해석할 수 없습니다.")
    period_str = date.strftime("%Y-%m-%d")
    updated = replace(
        financial, per=per, warnings=tuple(warnings), per_eps=eps,
        per_period_end=period_str,
    )
    if updated.eps is None:
        updated = supplement_trailing_eps(updated, income)
    return updated


def reconcile_financial_metrics(
    financial: FinancialData, raw_info: dict[str, object] | None = None
) -> dict[str, dict[str, object]]:
    """원자료(raw field) → 정규화 값(FinancialData) → 화면 표시 값을 대조한다."""
    raw = raw_info if isinstance(raw_info, dict) else {}
    return {
        "price": {
            "raw_field": "regularMarketPrice/currentPrice",
            "raw_value": raw.get("regularMarketPrice", raw.get("currentPrice")),
            "normalized_value": financial.price,
            "display_value": format_price(financial.price),
            "unit": "원",
            "period": financial.price_at.strftime("%Y-%m-%d %H:%M:%S KST") if financial.price_at else "기준 시각 미확인",
            "basis": "provided",
        },
        "per": {
            "raw_field": "trailingPE" if financial.per_eps is None else "price / DilutedEPS",
            "raw_value": raw.get("trailingPE") if financial.per_eps is None else financial.per,
            "normalized_value": financial.per,
            "display_value": format_multiple(financial.per),
            "unit": "배",
            "period": f"최근 12개월({financial.per_period_end} 종료)" if financial.per_period_end else "최근 12개월(TTM)",
            "basis": "calculated" if financial.per_eps is not None else "provided",
        },
        "pbr": {
            "raw_field": financial.pbr_metric.raw_field if financial.pbr_metric else "priceToBook",
            "raw_value": raw.get("priceToBook"),
            "normalized_value": financial.pbr,
            "display_value": format_multiple(financial.pbr),
            "unit": "배",
            "period": financial.pbr_metric.period if financial.pbr_metric else "",
            "basis": financial.pbr_metric.basis if financial.pbr_metric else "provided",
        },
        "eps": {
            "raw_field": financial.eps_metric.raw_field if financial.eps_metric else "trailingEps",
            "raw_value": raw.get("trailingEps"),
            "normalized_value": financial.eps,
            "display_value": format_per_share_krw(financial.eps),
            "unit": "주당 원",
            "period": financial.eps_metric.period if financial.eps_metric else "",
            "basis": financial.eps_metric.basis if financial.eps_metric else "provided",
        },
        "bps": {
            "raw_field": financial.bps_metric.raw_field if financial.bps_metric else "bookValue",
            "raw_value": raw.get("bookValue"),
            "normalized_value": financial.bps,
            "display_value": format_per_share_krw(financial.bps),
            "unit": "주당 원",
            "period": financial.bps_metric.period if financial.bps_metric else "",
            "basis": financial.bps_metric.basis if financial.bps_metric else "provided",
        },
    }
