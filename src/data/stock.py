"""후보 확인과 주가·PER 조회. 종목을 임의로 대체하지 않는다."""

import math
import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from numbers import Real

import pandas as pd

from src.models import AppError, FinancialData, KST, StockCandidate, now_kst


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
    if not candidates[0].ticker:
        raise AppError("market_unsupported", "첫 번째 후보의 시장은 현재 주가 조회에서 지원하지 않습니다. 테마를 다시 입력해 주세요.")
    return candidates[0]


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
    return FinancialData(stock=stock, price=price, per=per, retrieved_at=now_kst(),
                         price_at=price_at, warnings=tuple(warnings))


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
    if financial.per is not None or financial.price is None or info.get("financialCurrency") != "KRW":
        return financial
    try:
        income = ticker.get_income_stmt(freq="trailing")
    except Exception:
        return financial
    return supplement_trailing_per(financial, income)


def supplement_trailing_per(financial: FinancialData, income: object) -> FinancialData:
    """최근 12개월 희석 EPS로만 보완한다. 예상 PER·연간 EPS를 대신 쓰지 않는다."""
    if (financial.per is not None or financial.price is None
            or not isinstance(income, pd.DataFrame) or income.empty
            or "DilutedEPS" not in income.index or not income.index.is_unique
            or not income.columns.is_unique):
        return financial
    try:
        periods = [(pd.Timestamp(column), column) for column in income.columns]
        # 가장 최신 기간의 값이 없다고 이전 기간으로 몰래 대체하지 않는다.
        if any(pd.isna(date) for date, _ in periods):
            return financial
        date, column = max(periods, key=lambda item: item[0].value)
        reference = financial.price_at or financial.retrieved_at
        if date.date() > reference.date():
            return financial
        eps = finite_number(income.loc["DilutedEPS", column])
        if eps is None or eps == 0:
            return financial
        per = finite_number(financial.price / eps)
        if per is None:
            return financial
    except (ValueError, TypeError, KeyError, OverflowError):
        return financial
    warnings = [x for x in financial.warnings if x != "PER 정보가 없습니다."]
    if per <= 0:
        warnings.append("최근 12개월 희석 EPS가 음수여서 PER가 음수입니다. 단순히 저평가라고 해석할 수 없습니다.")
    return replace(financial, per=per, warnings=tuple(warnings), per_eps=eps,
                   per_period_end=date.strftime("%Y-%m-%d"))
