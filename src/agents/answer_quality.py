"""대화 답변의 자료 범위와 평가 기준. 원본 자료와 화면 출처는 변경하지 않는다."""
import re


QUALITY_CHECKS = {
    "evidence_match": "각 사실·수치·제목이 자신의 근거에 일치하며 계획을 실적이나 인과로 바꾸지 않았는가",
    "time_basis": "기사 발행/조회 시각을 사건 발생일·순서·실적 기간으로 추측하지 않았는가",
    "question_focus": "사용자가 물은 대상·범위에 답하고 무관한 지표나 별개 사건을 덧붙이지 않았는가",
    "explanation": "요약은 핵심 소식과 수집 범위를 짧게 전하면 충분하다. 분석 요청에만 사건 단계/의미와 미확인 범위 설명을 요구한다",
    "scope_disclosed": "뉴스 제목 기준/기사 제목에 한정 등 같은 뜻의 범위 고지를 인정한다. 지표 해석에는 기준 기간/시각 미확인 여부를 확인한다",
    "context_consistent": "후속 질문의 대상을 유지하며 이전 AI 답변을 독립적인 사실 근거로 사용하지 않았는가",
}


def answer_context(question, messages, evidence, required):
    """명시적인 단일 자료 질문만 좁힌다. 복합·모호한 요청은 자료를 보존한다."""
    news_question = bool(re.search(r"뉴스|기사|이슈", question))
    financial_question = bool(re.search(r"PER|PBR|ROE|EPS|BPS|주가|가격|차트|거래량|재무|매출|수익성", question, re.I))
    broad = bool(re.search(r"종합|전체|함께|연결|비교", question))
    last_user = next((str(m.get("text", "")) for m in reversed(messages) if m.get("role") == "user"), "")
    news_followup = bool(re.search(r"그\s*(?:발표|계획|기사|뉴스)|그러면", question) and re.search(r"뉴스|기사|발표", last_user))
    selected = evidence
    mode = "general"
    if (news_question and not financial_question and not broad) or (news_followup and not financial_question and not broad):
        mode = "news"
        selected = {key: item for key, item in evidence.items() if key.startswith("NEWS_")}
        # 이전 사용자 질문의 고유 단어가 하나의 기사만 가리킬 때만 좁힌다.
        # 모델 답변의 새 주장은 대상 선택이나 사실 근거로 사용하지 않는다.
        if news_followup:
            words = set(re.findall(r"[가-힣A-Za-z]{2,}", last_user)) - {"이", "종목의", "뉴스는", "무엇입니까", "알려줘", "뉴스", "기사", "발표"}
            matches = {key for key, item in selected.items() if key != "NEWS_STATUS"
                       and any(word in item["text"] for word in words)}
            if len(matches) == 1:
                selected = {key: item for key, item in selected.items() if key in matches or key == "NEWS_STATUS"}
    elif required and not news_question and not broad and not re.search(r"실적|재무|차트|거래량|원인|위험", question):
        mode = "metric"
        selected = {key: item for key, item in evidence.items() if key in required}

    instructions = ["질문의 핵심에 바로 답하며 정중한 입니다·합니다체로 작성합니다."]
    if mode == "news":
        instructions += [
            "수집된 뉴스 제목을 기준으로 답하며, 이 자료 범위를 자연스럽게 한 번 밝힙니다. 기사 본문·실제 공시 원문은 확인하지 않았습니다.",
            "발행일과 사건 시점은 별개입니다. 제목이 확인하지 않는 사건 발생 순서·원인·실적 영향을 추측하지 않습니다.",
            "분석 요청은 제목 반복으로 끝내지 않고 그 사건 단계에서 확정할 수 있는 것과 추가로 확인할 것을 설명합니다.",
            "제목의 사실이 참이어도 덧붙인 해석은 거짓일 수 있다면 회사의 사실로 쓰지 않습니다. 확인할 항목을 이미 진행된 상태로 표현하지 않습니다.",
            "미확인은 이번에 확보한 자료의 한계입니다. '이 제목만으로는 확인할 수 없습니다'처럼 범위를 한정하고, 실제로 사건이 없었다는 뜻으로 쓰지 않습니다.",
            "제목이 보도한 사실은 '제목에 따르면'으로 전달합니다. 원인·규모가 없다는 이유로 보도된 사건 자체까지 근거 없이 부정하거나 같은 문단에서 번복하지 않습니다.",
            "같은 한계를 표현만 바꿔 반복하지 않습니다. 보도 내용과 질문에 필요한 미확인 사항을 연결하고, 추가 확인 자료는 필요한 것만 간결하게 제시합니다.",
        ]
    if mode == "metric":
        instructions += ["확인된 값과 그 의미를 먼저 설명하고, 이 값만으로 판단할 수 없는 점을 짧게 덧붙입니다.",
                         "근거의 기준 기간/자료 시각이 미확인이면 그 한계도 본문에 알립니다. 누락 원인을 만들지 않습니다."]
    if news_followup:
        instructions.append("이전 사용자 질문에서 이어지는 사건에 집중하고 별개 사건으로 주제를 넓히지 않습니다.")
    if re.search(r"(?:세|3)\s*줄", question):
        instructions.append("줄바꿈으로 나눈 세 줄 이내의 요약입니다. 각 줄은 한 문장으로 작성하며 blocks는 비웁니다.")
    return selected, instructions


def model_evidence(evidence):
    """뉴스 발행·조회 시각/URL은 UI 전용이다. 제목 자체의 날짜는 그대로 둔다."""
    return {key: {field: value for field, value in item.items()
                  if not (item.get("scope") == "headline_only" and field in {"published_at", "retrieved_at", "url", "publisher_domain"})}
            for key, item in evidence.items()}


def failed_checks(verdict):
    checks = verdict.get("checks") if isinstance(verdict, dict) else None
    if not isinstance(checks, dict) or set(checks) != set(QUALITY_CHECKS):
        return list(QUALITY_CHECKS)
    return [key for key in QUALITY_CHECKS if checks[key] is not True]


def review_units(response, evidence):
    """문장과 명시적 연결 절을 코드에서 나눈다. 완전한 한국어 구문 분석은 아니다."""
    sections = [("intro", response.intro, response.lead_evidence_ids)]
    sections += [(f"block_{i}", f"{block.title}\n{block.text}", block.evidence_ids) for i, block in enumerate(response.blocks)]
    units = []
    for section, body, ids in sections:
        # '단정이며, 실제 여부는 미확인'을 한 문장으로 심사하면 뒷절만 평가할 수 있다.
        # 표시 문장은 보존하고 명시적인 연결 어미 뒤의 쉼표만 검토 단위로 나눈다.
        boundary = r"(?<=[.!?。！？])\s+|\n+|(?:(?<=이며)|(?<=이고)|(?<=하며)|(?<=지만)|(?<=으며)|(?<=는데)),\s*"
        for index, sentence in enumerate(re.split(boundary, body)):
            if sentence.strip():
                units.append({"id": f"{section}_{index}", "statement": sentence.strip(),
                              "evidence": model_evidence({key: evidence[key] for key in ids})})
    return units


def failed_unit_reviews(verdict, units):
    """검토 누락·중복·미지 ID를 거절한다. 의미 판정의 정확성은 별도 검수 대상이다."""
    expected = [unit["id"] for unit in units]
    reviews = verdict.get("unit_reviews") if isinstance(verdict, dict) else None
    if not isinstance(reviews, list) or len(reviews) != len(expected):
        return expected
    by_id = {}
    for item in reviews:
        if (not isinstance(item, dict) or set(item) != {"id", "reason", "supported"}
                or not isinstance(item["id"], str) or item["id"] not in expected
                or item["id"] in by_id or not isinstance(item["reason"], str)
                or not item["reason"].strip()):
            return expected
        by_id[item["id"]] = item
    return [key for key in expected if by_id[key]["supported"] is not True]
