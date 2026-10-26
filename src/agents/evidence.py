"""분석 결과를 근거 자료로 변환한다. 질문·LLM·화면에 의존하지 않는다."""
from src.models import AnalysisResult, resolve_roe_metric
from src.data.financial_comparison import annual_comparison_evidence


def build_evidence(result: AnalysisResult | None) -> dict[str, dict]:
    """값·자료 기준일·조회일·누락 상태와 차트 요약을 같은 결과에서 구성한다."""
    if result is None:
        return {}
    financial = result.financial
    roe = resolve_roe_metric(result)
    evidence = {}
    for key, value, unit in (
        ("PRICE", financial.price, "원"), ("PER", financial.per, "배"),
        ("PBR", financial.pbr, "배"), ("EPS", financial.eps, "원"),
        ("BPS", financial.bps, "원"), ("ROE", roe.value if roe and roe.status == "ok" else None, "%"),
    ):
        metric = getattr(financial, key.lower() + "_metric", None) if key != "ROE" else roe
        if metric is not None and metric.status != "ok":
            value = None
        value_text = "정보 없음" if value is None else f"{value:,.2f}{unit}"
        as_of = metric.as_of if metric else financial.price_at if key == "PRICE" else None
        period = metric.period if metric else financial.per_period_end if key == "PER" else ""
        evidence[key] = {"text": f"{financial.stock.name} · {key}: {value_text}", "value_text": value_text,
                         "value": value, "status": metric.status if metric else "ok" if value is not None else "missing",
                         "reason": metric.reason if metric else "", "source": metric.source if metric else financial.source,
                         "formula": metric.formula if metric else "주가 / 최근 12개월 희석 EPS" if key == "PER" and financial.per_eps is not None else "",
                         "period": period or "기준 기간 미확인", "as_of": as_of.isoformat() if as_of else "자료 기준 시각 미확인",
                         "retrieved_at": (metric.retrieved_at if metric else financial.retrieved_at).isoformat(),
                         "stock_code": result.target_code, "result_id": result.result_id}
    for article in result.news.articles:
        evidence[f"NEWS_{article.id}"] = {"text": article.title, "url": article.url, "source": result.news.source,
            "publisher_domain": article.publisher_domain,
            "published_at": article.published_at, "retrieved_at": result.news.retrieved_at.isoformat(), "scope": "headline_only"}
    evidence["NEWS_STATUS"] = {"text": result.news.message or result.news.status, "status": result.news.status,
        "source": result.news.source, "retrieved_at": result.news.retrieved_at.isoformat()}
    for fact in result.financial_facts:
        evidence[f"FACT_{fact.fact_id}"] = {"text": f"{fact.stock_name} · {fact.item}: {fact.display_value}",
            "value_text": fact.display_value, "source": fact.source, "period": fact.period, "fs_div": fact.fs_div}
    history = result.price_history
    if history and history.status == "ok" and history.bars and history.code == result.target_code:
        bars = history.bars
        first, last = bars[0], bars[-1]
        change = (last.close / first.close - 1) * 100 if first.close else None
        evidence["HISTORY"] = {"text": f"{first.trade_date}~{last.trade_date}: 종가 {first.close:,.2f}원 → {last.close:,.2f}원, 첫날 거래량 {first.volume:,}주 → 마지막 거래량 {last.volume:,}주",
            "source": history.source, "period": f"{first.trade_date}~{last.trade_date}", "retrieved_at": history.retrieved_at.isoformat(),
            "first_close": first.close, "last_close": last.close, "change_pct": change,
            "first_volume": first.volume, "last_volume": last.volume, "observations": len(bars),
            "adjusted": history.adjusted, "currency": history.currency,
            "series": [{"date": b.trade_date, "close": b.close, "volume": b.volume} for b in bars[-60:]],
            "scope": "조회된 거래일 계열, 요약의 첫날·마지막날 비교는 전체 구간 단조 증가/감소를 뜻하지 않음"}
        for key, label, value in (
            ("START", "첫 거래일", first.trade_date), ("END", "마지막 거래일", last.trade_date),
            ("FIRST_CLOSE", "첫 종가", f"{first.close:,.2f}원"),
            ("LAST_CLOSE", "마지막 종가", f"{last.close:,.2f}원"),
            ("FIRST_VOLUME", "첫날 거래량", f"{first.volume:,}주"),
            ("LAST_VOLUME", "마지막 거래량", f"{last.volume:,}주"),
            ("CHANGE", "구간 종가 변화율", f"{change:+.2f}%" if change is not None else "계산 불가"),
        ):
            evidence[f"HISTORY_{key}"] = {"text": f"{label}: {value}", "value_text": value,
                "source": history.source, "period": evidence["HISTORY"]["period"],
                "stock_code": result.target_code, "result_id": result.result_id}
    for annual in result.annual_summaries:
        evidence[f"ANNUAL_{annual.bsns_year}_{annual.fs_div}"] = {
            "text": f"{annual.bsns_year}년 {annual.fs_div} 매출 {annual.revenue}, 영업이익 {annual.operating_income}, 순이익 {annual.net_income} (원)",
            "source": "OpenDART", "period": annual.bsns_year, "fs_div": annual.fs_div,
            "revenue": str(annual.revenue) if annual.revenue is not None else None, "operating_income": str(annual.operating_income) if annual.operating_income is not None else None, "net_income": str(annual.net_income) if annual.net_income is not None else None}
    evidence.update(annual_comparison_evidence(result.annual_summaries,
                    stock_code=result.target_code, result_id=result.result_id))
    evidence["FINANCIAL_STATUS"] = {"text": "연간 재무자료 수집 상태", "status": result.section_status.get("dart", "unknown"),
                                    "source": "OpenDART", "years_available": sorted({a.bsns_year for a in result.annual_summaries})}
    return evidence
