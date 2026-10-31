"""화면과 답변 심사가 공유하는 간결한 데이터 출처 표기."""


def data_source_label(item):
    label = str(item.get("source") or "자료 출처")
    period = item.get("period")
    if period and "미확인" not in str(period):
        label += " · " + str(period)
    if item.get("fs_div"):
        label += " · " + {"CFS": "연결", "OFS": "별도"}.get(item["fs_div"], item["fs_div"])
    return label


def news_usage_label(result, article_id):
    """현재 결과에 묶인 판정만 표시한다. 원문을 AI 인용 목록으로 혼동하지 않는다."""
    from src.agents.news_relevance import matches
    admission = result.news.admission
    if not matches(admission, result.news, result.financial.stock, result.theme, result.result_id):
        return ""
    item = next((a for a in admission.assessments if a.article_id == article_id), None)
    if item is None:
        return ""
    if item.accepted:
        return "산업 맥락으로 채택" if item.relation == "industry" else "종목 소식으로 채택"
    return "분석 근거 미채택 · 연결 미확인" if item.relation != "unrelated" else "분석 근거 미채택 · 다른 주제"
