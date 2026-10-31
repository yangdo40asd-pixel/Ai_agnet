"""요청 분기 수집과 근거 구성. 기존 정규화·3개월 계산 및 Decimal 증감 계산을 재사용한다."""
from decimal import Decimal, InvalidOperation
import re
import time

from src.config import Settings
from src.data.dart import fetch_corp_codes, fetch_statement, resolve_corp_code
from src.data.financial_comparison import amount_change
from src.data.financials import build_quarter_comparison, normalize_statement
from src.data.report_period import QuarterRequest
from src.formatting import format_eok, format_percent
from src.models import AppError, StockCandidate

ITEMS = {"revenue": "매출", "operating_income": "영업이익", "net_income": "당기순이익",
         "operating_margin": "영업이익률"}


def collect_quarterly_financials(stock: StockCandidate, request: QuarterRequest, settings: Settings) -> dict:
    bundle = {"status": "empty", "request": request.token, "statements": (), "summaries": (), "calls": ()}
    if request.reason or not stock.selectable or not settings.dart_api_key:
        return dict(bundle, message=request.reason or "분기 재무자료를 조회할 설정 또는 종목 정보가 없습니다.")
    try:
        corp = resolve_corp_code(stock.code, fetch_corp_codes(settings))
    except AppError as error:
        return dict(bundle, status="failed", message=error.message)
    calls = []

    def fetch_series(basis):
        responses = []
        for year, code in request.reports:
            started = time.perf_counter()
            response = fetch_statement(corp, year, code, basis, settings=settings)
            calls.append({"year": year, "report": code, "basis": basis,
                          "status": response.get("status"),
                          "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
            responses.append(response)
            if response.get("status") in {"auth_error", "rate_limit"}:
                break
        return responses

    responses = fetch_series(request.fs_div or "CFS")
    # 오류나 일부 결측을 근거로 기준을 바꾸지 않는다. 명시한 CFS도 OFS로 대체하지 않는다.
    fallback = (request.fs_div is None and responses
                and all(r.get("status") == "empty" for r in responses))
    if fallback:
        responses = fetch_series("OFS")
    statements = tuple(normalize_statement(stock.code, r, is_separate_fallback=fallback)
                       for r in responses if r.get("status") == "ok")
    summaries = tuple(q for q in build_quarter_comparison(statements)
                      if q.period_label == f"{request.year} {request.quarter}Q"
                      or q.period_label == f"{request.year - 1} {request.quarter}Q")
    current = any(q.bsns_year == str(request.year) for q in summaries)
    failed = any(r.get("status") not in {"ok", "empty"} for r in responses)
    previous = any(q.bsns_year == str(request.year - 1) for q in summaries)
    status = "partial" if current and (failed or not previous) else "ok" if current else "failed" if failed else "empty"
    return dict(bundle, status=status, statements=statements, summaries=summaries,
                calls=tuple(calls), message="" if current else "요청한 분기의 공시 재무수치를 확인하지 못했습니다.")


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def quarterly_evidence(summaries, *, stock_code: str, result_id: str, statements=()) -> dict:
    """당분기와 전년 동기의 동일 기준만 연결한다. 입력 중복·단위·결측을 임의 보정하지 않는다."""
    grouped = {}
    for q in summaries:
        match = re.fullmatch(r"(20\d{2}) ([1-4])Q", q.period_label)
        if (not match or q.bsns_year != match[1] or q.currency != "KRW"
                or q.fs_div not in {"CFS", "OFS"} or q.period_type != "quarter_3m"
                or not q.is_standalone_quarter):
            continue
        grouped.setdefault((int(match[1]), int(match[2]), q.fs_div), []).append(q)
    values = {}
    result = {}
    for (year, quarter, basis), entries in grouped.items():
        if len(entries) != 1:
            continue
        q = entries[0]
        fields = {item: _decimal(getattr(q, item)) for item in ITEMS if item != "operating_margin"}
        revenue, income = fields["revenue"], fields["operating_income"]
        fields["operating_margin"] = income / revenue * 100 if revenue is not None and revenue > 0 and income is not None else None
        values[(year, quarter, basis)] = fields
        receipt = str(q.rcept_no or "")
        parents = [{"receipt": s.rcept_no, "report": s.reprt_code, "year": s.bsns_year,
                    "retrieved_at": s.retrieved_at.isoformat()}
                   for s in statements if s.bsns_year == q.bsns_year and s.fs_div == basis
                   and s.reprt_code in ({"11011", "11014"} if quarter == 4 else {q.reprt_code})]
        base = {"source": "OpenDART", "stock_code": stock_code, "result_id": result_id,
                "status": "ok", "years": [year], "quarter": quarter, "fs_div": basis,
                "currency": "KRW", "period_type": "quarter_3m", "kind": "quarterly_financial",
                "period": f"{year}년 {quarter}분기(3개월)", "derivation_note": q.derivation_note,
                "parents": parents,
                "retrieved_at": max((p["retrieved_at"] for p in parents), default=""),
                "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + receipt if re.fullmatch(r"\d{14}", receipt) else ""}
        for item, value in fields.items():
            if value is None:
                continue
            display = format_percent(value) if item == "operating_margin" else format_eok(value)
            key = f"QFIN_{year}_{quarter}_{basis}_{item.upper()}"
            result[key] = dict(base, item=item, value=str(value), value_text=display,
                               text=f"{base['period']} {ITEMS[item]}: {display}")
    for (year, quarter, basis), fields in values.items():
        previous = values.get((year - 1, quarter, basis))
        if previous is None:
            continue
        for item, current in fields.items():
            before = previous[item]
            if before is None or current is None:
                continue
            base = result[f"QFIN_{year}_{quarter}_{basis}_{item.upper()}"]
            older = result[f"QFIN_{year-1}_{quarter}_{basis}_{item.upper()}"]
            delta, pct, state = amount_change(before, current, profit=item != "revenue")
            margin = item == "operating_margin"
            if margin:
                pct = None
                state = "상승" if delta > 0 else "하락" if delta < 0 else "변동 없음"
                change = f"{abs(delta):.2f}%p {state}"
            else:
                change = f"{abs(pct):.2f}% {state}" if pct is not None else state
            display = format_percent if margin else format_eok
            result[f"Q_CMP_{year-1}_{year}_{quarter}_{basis}_{item.upper()}"] = dict(
                base, kind="quarterly_comparison", years=[year - 1, year],
                period=f"{year-1}년 {quarter}분기 → {year}년 {quarter}분기(각 3개월)",
                parents=[*older["parents"], *base["parents"]],
                previous=str(before), current=str(current), change_pct=str(pct) if pct is not None else None,
                delta_pp=str(delta) if margin else None, change_state=state,
                value_text=f"{display(before)} → {display(current)} ({change})",
                text=f"{ITEMS[item]}: {display(before)} → {display(current)} ({change})")
    return result
