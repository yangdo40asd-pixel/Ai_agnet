"""동일 연간 기준의 실적 비교. 외부 조회와 AI 문장 생성 없이 계산한다."""
from decimal import Decimal, InvalidOperation

from src.formatting import format_eok, format_percent


ITEMS = {"revenue": "매출액", "operating_income": "영업이익", "net_income": "당기순이익"}


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _change(before, after, *, profit=True):
    """음수/영 분모의 성장률은 만들지 않고 변화 상태를 돌려준다."""
    delta = after - before
    if not profit and (before < 0 or after < 0):
        return delta, None, "음수 매출이 있어 증감률 계산 제외"
    if before < 0 <= after:
        return delta, None, "흑자 전환" if after > 0 else "손익분기 도달"
    if before >= 0 > after:
        return delta, None, "적자 전환"
    if before < 0 and after < 0:
        return delta, None, "적자 축소" if delta > 0 else "적자 확대" if delta < 0 else "변동 없음"
    if before == 0:
        return delta, None, "전기 값이 영이므로 증감률 계산 제외"
    pct = delta / before * 100
    return delta, pct, "증가" if delta > 0 else "감소" if delta < 0 else "변동 없음"


def annual_comparison_evidence(summaries, *, stock_code, result_id):
    """중복 연도·기준 혼합·중간 연도 누락을 전년 비교로 해석하지 않는다."""
    result = {}
    grouped = {}
    for summary in summaries:
        if summary.reprt_code != "11011" or not str(summary.bsns_year).isdigit():
            continue
        key = (summary.fs_div, summary.currency)
        grouped.setdefault(key, {}).setdefault(int(summary.bsns_year), []).append(summary)
    for (fs_div, currency), years in grouped.items():
        # 현재 표시 단위는 원→억원이다. 다른 통화는 환산 없이 섞지 않는다.
        if currency != "KRW":
            continue
        for year in sorted(years):
            if len(years[year]) != 1:
                continue
            current = years[year][0]
            base = {"source": "OpenDART", "period": f"{year}년 연간", "fs_div": fs_div,
                    "stock_code": stock_code, "result_id": result_id, "years": [year],
                    "currency": currency, "kind": "annual_financial"}
            for field, label in ITEMS.items():
                value = _decimal(getattr(current, field))
                if value is not None:
                    result[f"FIN_{year}_{fs_div}_{field.upper()}"] = dict(
                        base, item=field, value=str(value), value_text=format_eok(value),
                        text=f"{year}년 {label}: {format_eok(value)}", status="ok")
            if year - 1 not in years or len(years[year - 1]) != 1:
                continue
            previous = years[year - 1][0]
            common = dict(base, period=f"{year - 1}년 → {year}년 연간", years=[year - 1, year],
                          kind="annual_comparison", formula="동일 연간·연결/별도 기준 비교")
            for field, label in ITEMS.items():
                before, after = _decimal(getattr(previous, field)), _decimal(getattr(current, field))
                if before is None or after is None:
                    continue
                delta, pct, state = _change(before, after, profit=field != "revenue")
                change = f"{format_percent(abs(pct))} {state}" if pct is not None and pct else state
                value_text = f"{year - 1}년 {format_eok(before)} → {year}년 {format_eok(after)} ({change})"
                result[f"CMP_{year - 1}_{year}_{fs_div}_{field.upper()}"] = dict(
                    common, item=field, text=f"{label}: {value_text}", value_text=value_text,
                    previous=str(before), current=str(after), delta=str(delta),
                    change_pct=str(pct) if pct is not None else None, change_state=state, status="ok")
            old_revenue, revenue = _decimal(previous.revenue), _decimal(current.revenue)
            old_income, income = _decimal(previous.operating_income), _decimal(current.operating_income)
            if (old_revenue is not None and revenue is not None and old_revenue > 0 and revenue > 0
                    and old_income is not None and income is not None):
                old_margin, margin = old_income / old_revenue * 100, income / revenue * 100
                delta = margin - old_margin
                value_text = (f"{year - 1}년 {format_percent(old_margin)} → {year}년 {format_percent(margin)} "
                              f"({abs(delta):.2f}%p {'상승' if delta > 0 else '하락' if delta < 0 else '변동 없음'})")
                result[f"CMP_{year - 1}_{year}_{fs_div}_OPERATING_MARGIN"] = dict(
                    common, item="operating_margin", text=f"영업이익률: {value_text}", value_text=value_text,
                    previous=str(old_margin), current=str(margin), delta_pp=str(delta), status="ok",
                    formula="영업이익 / 매출액 × 100; 이익률 차이는 %p")
    return result
