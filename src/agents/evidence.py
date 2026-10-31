"""분석 결과를 근거 자료로 변환한다. 질문·LLM·화면에 의존하지 않는다."""
from src.models import AnalysisResult, resolve_roe_metric
from src.data.financial_comparison import annual_comparison_evidence
from src.data.text_facts import source_facts, fact_payload


def article_evidence(article, stock_name, *, known_names=(), include_excerpt=True, relationships=(), stock_code=None):
    from src.data.relations import article_relationships, relationship_payload
    key=f'NEWS_{article.id}'
    facts=source_facts(article.title,key,stock_name,published_at=article.published_at,known_names=known_names)
    if article.description and include_excerpt:
        facts+=source_facts(article.description,key,stock_name,scope='article_excerpt',published_at=article.published_at,known_names=known_names)
    return {'text':article.title,'url':article.url,'scope':'article_excerpt' if article.description and include_excerpt else 'headline_only','stock_name':stock_name,
            'structured_facts':[fact_payload(f) for f in facts],
            **({'relationship_proofs':[relationship_payload(p) for p in article_relationships(article,stock_name,relationships,target_code=stock_code)]} if relationships else {}),
            **({'excerpt':article.description,'excerpt_scope':'article_excerpt'} if article.description and include_excerpt else {})}


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
        evidence[f"NEWS_{article.id}"] = {**article_evidence(article, financial.stock.name, known_names=tuple(s.name for s in result.candidates),relationships=result.news.relationships,stock_code=result.target_code), "source": result.news.source,
            "publisher_domain": article.publisher_domain,
            "published_at": article.published_at, "retrieved_at": result.news.retrieved_at.isoformat()}
    for document in result.source_documents:
        if document.stock_code != result.target_code or document.scope!='official_disclosure':
            continue
        # 각 문서의 사실만 보존하며, 여러 정정 공시 중 현재 유효 문서를 결정하지 않는다(Y 범위).
        text=document.text
        facts=source_facts(text,document.evidence_id,document.stock_name,scope=document.scope,
                           published_at=document.published_at,known_names=tuple(s.name for s in result.candidates))
        verified=[f for f in facts if f.status=='verified'][:16]
        contexts=[]
        for fact in verified:
            a,b=fact.span
            contexts.append(text[max(0,a-100):min(len(text),b+100)])
        evidence[document.evidence_id]={'text':document.title,'source':document.source,'url':document.url,
            'scope':document.scope,'stock_code':document.stock_code,'stock_name':document.stock_name,
            'document_id':document.document_id,'published_at':document.published_at,
            'retrieved_at':document.retrieved_at.isoformat(),'source_excerpt':'\n'.join(dict.fromkeys(contexts))[:2400],
            'structured_facts':[fact_payload(f) for f in facts], 'validity':'document_only',
            'extraction_scope':'원문 앞 6000자의 명시적 수치만 검사; 전체 정정 이력 미확인'}
    if result.news.admission is not None:
        from src.agents.news_relevance import matches
        if matches(result.news.admission, result.news, financial.stock, result.theme, result.result_id):
            for assessment in result.news.admission.assessments:
                key = "NEWS_" + str(assessment.article_id)
                if key in evidence:
                    evidence[key].update(relation=assessment.relation, admitted=assessment.accepted,
                                         subject_quote=assessment.subject_quote, support_quote=assessment.support_quote)
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
    from src.data.quarterly import quarterly_evidence
    evidence.update(quarterly_evidence(result.quarterly_summaries, stock_code=result.target_code,
                                      result_id=result.result_id, statements=result.financial_statements))
    if result.section_status.get("quarterly_request"):
        evidence["Q_COLLECTION_STATUS"] = {"status": result.section_status.get("dart_quarterly"),
            "request_token": result.section_status["quarterly_request"], "source": "OpenDART",
            "text": result.section_status.get("quarterly_message", "분기 재무자료 조회 상태")}
    from src.data.cost_structure import cost_structure_evidence
    evidence.update(cost_structure_evidence(result.financial_statements,stock_code=result.target_code,result_id=result.result_id,annual_summaries=result.annual_summaries))
    evidence["FINANCIAL_STATUS"] = {"text": "연간 재무자료 수집 상태", "status": result.section_status.get("dart", "unknown"),
                                    "source": "OpenDART", "years_available": sorted({a.bsns_year for a in result.annual_summaries})}
    return evidence
