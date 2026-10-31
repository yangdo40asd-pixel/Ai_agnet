"""대화 답변의 자료 범위와 평가 기준. 원본 자료와 화면 출처는 변경하지 않는다."""
import json
import re
from dataclasses import dataclass, field
from src.agents.presentation import parse_presentation


QUALITY_CHECKS = {
    "evidence_match": "각 사실·수치·제목이 자신의 근거에 일치하며 계획을 실적이나 인과로 바꾸지 않았는가",
    "time_basis": "기사 발행/조회 시각을 사건 발생일·순서·실적 기간으로 추측하지 않았는가",
    "question_focus": "사용자가 물은 대상·범위에 답하고 무관한 지표나 별개 사건을 덧붙이지 않았는가",
    "explanation": "요약은 핵심 소식과 수집 범위를 짧게 전하면 충분하다. 분석 요청에만 사건 단계/의미와 미확인 범위 설명을 요구한다",
    "scope_disclosed": "본문과 실제 표시 출처를 함께 보아 자료 범위·비교 기간·기준이 확인되는가. 하단 출처에 있는 기간·연결/별도 기준을 본문에 중복할 의무는 없다",
    "context_consistent": "후속 질문의 대상을 유지하며 이전 AI 답변을 독립적인 사실 근거로 사용하지 않았는가",
}

_ORDINAL_NEWS = (
    (r"(?:첫\s*번째|1\s*번째|1\s*번)\s*(?:뉴스|기사|이슈|소식)", "NEWS_1"),
    (r"(?:두\s*번째|2\s*번째|2\s*번)\s*(?:뉴스|기사|이슈|소식)", "NEWS_2"),
    (r"(?:세\s*번째|3\s*번째|3\s*번)\s*(?:뉴스|기사|이슈|소식)", "NEWS_3"),
)


def ordinal_news_key(question: str) -> str:
    for pattern, key in _ORDINAL_NEWS:
        if re.search(pattern, question):
            return key
    return ""


@dataclass(frozen=True)
class EvidenceSelection:
    evidence: dict
    requirements: tuple[str, ...]
    reason: str
    required_ids: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    required_groups: dict = field(default_factory=dict)


def _financial_selection(question, evidence):
    """명시한 기간 또는 최신 동일 기준 비교를 선택한다. 원자료를 바꾸지 않는다."""
    fields = set()
    for field, pattern in (("revenue", "매출"), ("operating_income", "영업이익"),
                           ("net_income", "순이익"), ("operating_margin", "이익률|수익성|마진")):
        if re.search(pattern, question):
            fields.add(field)
    if not fields or re.search("실적|재무|수익성|왜|원인|이유|비결|요인|배경", question):
        fields.update(("revenue", "operating_income", "operating_margin"))
    wants_cost=bool(re.search(r'원가|판관비|판매관리비|왜|원인|이유|비결|요인',question))
    if wants_cost:
        fields.update(('cost_of_sales_ratio','selling_expenses_ratio'))
    years = {int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?:년)?", question)}
    wants_comparison = bool(
        re.search(r"좋아|좋은|나빠|나쁜|괜찮|양호|어떤\s*편|개선|악화|증가|감소|성장|상승|하락|비교|변화|추이|전년|늘|줄|왜|원인|이유", question)
    )
    entries = {k: v for k, v in evidence.items() if v.get("kind") in {"annual_comparison", "annual_financial"}
               and v.get("item") in fields}
    if wants_cost and any(v.get('cost_bridge_reconciled') for v in entries.values()):
        keep={'cost_of_sales_ratio','selling_expenses_ratio','operating_margin'}
        # 원인 설명에 필요한 비용만 고르더라도 사용자가 비교한 피연산자는 지우지 않는다.
        if re.search(r'보다|대비|더|증가|늘|줄|감소',question):
            if re.search(r'매출(?!원가)',question):
                keep.add('revenue')
            if re.search(r'영업이익(?!률)',question):
                keep.add('operating_income')
        entries={k:v for k,v in entries.items() if v.get('item') in keep}
    if years:
        entries = {
            k: v
            for k, v in entries.items()
            if set(v["years"]) <= years
            or (wants_comparison and v.get("kind") == "annual_comparison" and max(v["years"]) in years)
        }
    elif entries:
        latest = max(max(v["years"]) for v in entries.values())
        entries = {k: v for k, v in entries.items() if max(v["years"]) == latest}
    # 연결/별도 중 데이터가 있다는 이유로 임의 우선순위를 부여하지 않는다.
    # 복수 기준이면 둘 다 보존하고 각각의 기준을 명시하도록 요구한다.
    compared = {(v["item"], v["fs_div"]) for v in entries.values() if v["kind"] == "annual_comparison"}
    entries = {k: v for k, v in entries.items()
               if v["kind"] == "annual_comparison" or (v["item"], v["fs_div"]) not in compared}
    # 부채·자본·현금흐름 또는 원인·요인 질문은 기존 재무 Fact도 포함한다.
    if re.search("부채|자산|자본|현금|재무|왜|원인|이유|비결|요인", question) or not entries:
        entries.update({k: v for k, v in evidence.items() if k.startswith("FACT_")
                        and (not years or any(str(y) in v.get("period", "") for y in years))})
    missing = tuple(sorted(fields - {v.get("item") for v in entries.values()}))
    if "FINANCIAL_STATUS" in evidence:
        entries["FINANCIAL_STATUS"] = evidence["FINANCIAL_STATUS"]
    return entries, missing


def select_evidence(question, messages, evidence, required, *, strict=False):
    """명시적인 단일 자료 질문만 좁힌다. 복합·모호한 요청은 자료를 보존한다."""
    from src.agents.followup import restatement_evidence
    focused = restatement_evidence(question, messages, evidence)
    if focused is not None:
        instructions = (
            "직전 답변에서 실제 사용한 현재 근거만 요약합니다. 다른 지표·기간·뉴스로 범위를 넓히지 않습니다.",
            "새 분석을 예고하거나 같은 수치를 두 번 말하지 않고, 핵심 결과와 의미를 요청 분량 안에 합칩니다.",
            "과거 AI 문장은 사실 근거가 아닙니다. 선택된 원자료와 일치하는 주장만 정중한 입니다·합니다체로 답합니다.",
            *parse_presentation(question).instructions(),
        )
        if focused and all(k.startswith("NEWS_") and v.get("scope") in {"headline_only","article_excerpt"} for k,v in focused.items()):
            instructions += ("언론 보도 요약입니다. 첫 문장 안에서 '관련 보도에 따르면'처럼 귀속하고, 회사가 설명한 이유는 회사 설명으로 전달합니다. 보도된 연관성을 확인된 인과관계로 바꾸지 않습니다.",)
        # 여러 근거의 요약은 실제 쓴 근거만 인용할 수 있다. 원자료 범위는 고정하되
        # 짧은 요약에 이전 답변의 모든 ID/숫자를 다시 넣으라고 강제하지 않는다.
        required_ids=tuple(focused) if len(focused)==1 else tuple(k for k in required if k in focused)
        groups={"summary_source":{"mode":"any","ids":list(focused)}}
        if all(k.startswith("NEWS_") and k!="NEWS_STATUS" for k in focused):
            from src.agents.issues import group_issues, card_groups
            groups={f"summary_issue_{i}":{"mode":"any","ids":list(g.evidence_ids)}
                    for i,g in enumerate(card_groups(group_issues(focused)))} or groups
            instructions += ("요약할 여러 뉴스 사건의 핵심은 유지하되, 같은 사건의 중복 기사 ID를 모두 인용하거나 모든 숫자를 되풀이할 의무는 없습니다.",)
        return EvidenceSelection(focused, instructions, "restatement", required_ids, required_groups=groups)
    from src.agents.followup import is_conversation_summary_request, conversation_summary_evidence
    if is_conversation_summary_request(question):
        summary_ev = conversation_summary_evidence(question, messages, evidence)
        if summary_ev is not None:
            instructions = (
                "지금까지 대화에서 다룬 핵심 결론과 근거, 유리한 요인과 부담 요인을 종합해 정중하고 간결하게 정리합니다.",
                "대화에서 다루지 않은 새로운 수치를 추가하지 않고 요청 분량을 지킵니다.",
                "과거 AI 문장의 결론을 확인된 현재 사실로 승격하지 않고, 실제 원자료 근거와 일치하게 요약합니다.",
                *parse_presentation(question).instructions(),
            )
            required_ids = tuple(summary_ev) if len(summary_ev) <= 2 else ()
            groups = {"conversation_summary": {"mode": "any", "ids": list(summary_ev)}}
            return EvidenceSelection(summary_ev, instructions, "conversation_summary", required_ids, required_groups=groups)
    from src.agents.quarterly import selection_data
    quarterly = selection_data(question, messages, evidence)
    if quarterly is not None:
        requirements = (*quarterly["requirements"], *parse_presentation(question).instructions())
        return EvidenceSelection(**{**quarterly, "requirements": requirements})
    from src.agents.outlook import select_background
    outlook = select_background(question, evidence, required, messages=messages)
    if outlook is not None:
        return EvidenceSelection(**outlook)
    news_question = bool(re.search(r"뉴스|기사|이슈|공시", question))
    financial_question = bool(re.search(r"PER|PBR|ROE|EPS|BPS|주가|가격|차트|거래량|재무|매출|수익성|실적|영업이익|순이익|원가|판관비|판매관리비", question, re.I))
    annual_question = bool(re.search(r"재무|매출|수익성|실적|영업이익|순이익|부채|자본|현금흐름|원가|판관비|판매관리비", question))
    broad = bool(re.search(r"종합|전체|함께|연결|비교", question))
    from src.agents.question_goal import question_goal
    overview = question_goal(question).company_overview
    last_user = next((str(m.get("text", "")) for m in reversed(messages) if m.get("role") == "user"), "")
    causal_question = bool(re.search(r"왜|원인|이유|비결|요인|배경", question))
    last_answer = next((m for m in reversed(messages) if m.get("role") == "assistant"), {})
    causal_financial_context = causal_question and any(
        item.get("kind") in {"annual_comparison", "quarterly_comparison"}
        for item in last_answer.get("evidence", ()) if isinstance(item, dict))
    if causal_financial_context and not news_question:
        annual_question = financial_question = True
    last_evidence_ids = {item.get("id") for item in last_answer.get("evidence", ()) if isinstance(item, dict)}
    causal_news_context = causal_question and not causal_financial_context and any(
        k.startswith("NEWS_") and k != "NEWS_STATUS" for k in last_evidence_ids
    )
    if causal_question and not news_question and re.search(r"증가|감소|개선|악화|상승|하락|실적|이익|매출|마진|흑자|적자", question + " " + last_user):
        annual_question = True
        financial_question = True
    explicit_event_ref = bool(re.search(r"그\s*(?:발표|계획|기사|뉴스)", question))
    has_news_context = any(k.startswith("NEWS_") and k != "NEWS_STATUS" for k in evidence) or any(
        re.search(r"뉴스|기사|발표|계획|소식", str(m.get("text", ""))) for m in messages
    )
    news_followup = (explicit_event_ref and has_news_context) or bool(
        re.search(r"그러면", question) and re.search(r"뉴스|기사|발표", last_user)
    ) or (causal_news_context and not financial_question)
    ambiguous_event = bool(re.search(r"그\s*(?:발표|계획|기사|뉴스)|(?:그러면|그럼|그래서).*(?:확정|영향|반영)", question))
    selected = evidence
    mode = "general"
    missing = ()
    instructions_note = ""
    required_ids = tuple(required)
    strict_event_followup = (strict and news_followup and ambiguous_event and not broad
                            and not re.search("매출|영업이익|순이익|수익성|재무", question))
    preliminary_request=bool(re.search(r'잠정|실적\s*발표|확정\s*(?:실적|발표)',question))
    preliminary={k:v for k,v in evidence.items() if k.startswith('NEWS_') and any(
        f.get('status')=='verified' and f.get('qualifier')=='provisional' for f in v.get('structured_facts',()))}
    if preliminary_request and preliminary and not broad:
        requested_years=set(re.findall(r'20\d{2}',question))
        requested_quarters=set(re.findall(r'([1-4])분기',question))
        def relevant(item):
            periods=[str(f.get('financial_period') or '') for f in item.get('structured_facts',()) if f.get('qualifier')=='provisional']
            return any((not requested_years or any(year in period for year in requested_years))
                       and (not requested_quarters or any(q+'분기' in period for q in requested_quarters)) for period in periods)
        matching={k:v for k,v in preliminary.items() if relevant(v)}
        if matching:
            def financial_period(item):
                periods=[re.search(r'(20\d{2})년\s*(?:([1-4])분기)?',str(f.get('financial_period') or ''))
                         for f in item.get('structured_facts',()) if f.get('qualifier')=='provisional']
                return max(((int(m[1]),int(m[2] or 0)) for m in periods if m),default=(0,0))
            latest=max(financial_period(item) for item in matching.values())
            selected={k:v for k,v in matching.items() if financial_period(v)==latest}
            mode='news'
            required_ids=tuple(required)
            selected.update({k:evidence[k] for k in required if k in evidence})
            news_question=True
        else:
            mode='news'
            news_question=True
            selected={'NEWS_STATUS':{'text':'이번 조회 자료에서 요청한 기간의 잠정 실적을 확인하지 못했습니다. 다른 기간의 값으로 대신하지 않습니다.',
                                     'status':'period_unconfirmed','source':'현재 수집 자료'}}
    elif preliminary_request and preliminary:
        news_question=True
    if mode=='news':
        selected.update({k:evidence[k] for k in required if k in evidence})
    elif (news_question and not financial_question and not broad) or (news_followup and not financial_question and not broad) or strict_event_followup:
        mode = "news"
        selected = {key: item for key, item in evidence.items() if key.startswith("NEWS_")}
        from src.agents.followup import displayed_issue_ids
        displayed = displayed_issue_ids(question, messages, selected)
        ord_key = ordinal_news_key(question)
        if displayed is not None:
            if displayed:
                selected = {key: item for key, item in selected.items() if key in displayed or key == "NEWS_STATUS"}
                required_ids = tuple(dict.fromkeys((*required_ids, *displayed)))
            else:
                selected = {"NEWS_STATUS": {"text": "요청한 순서의 이전 이슈를 현재 근거와 연결할 수 없습니다.",
                            "status": "displayed_issue_unavailable", "source": "대화 카드 연결 확인"}}
                instructions_note = "이전 카드의 순서를 다른 기사 번호로 바꾸지 않습니다. 요청한 카드가 없거나 원자료가 바뀌었음을 짧게 설명합니다."
        elif ord_key and ord_key in selected:
            selected = {key: item for key, item in selected.items() if key == ord_key or key == "NEWS_STATUS"}
            required_ids = tuple(dict.fromkeys((*required_ids, ord_key)))
        elif news_followup:
            ref_text = last_user if re.search(r"뉴스|기사|발표|계획|소식", last_user) else " ".join(
                str(m.get("text", "")) for m in reversed(messages) if m.get("role") in {"user", "assistant"}
            )
            words = set(re.findall(r"[가-힣A-Za-z]{2,}", ref_text)) - {"이", "종목의", "뉴스는", "무엇입니까", "알려줘", "뉴스", "기사", "발표"}
            matches = {key for key, item in selected.items() if key != "NEWS_STATUS"
                       and any(word in item["text"] for word in words)}
            if len(matches) == 1:
                selected = {key: item for key, item in selected.items() if key in matches or key == "NEWS_STATUS"}
    elif overview:
        mode = "overview"
        selected, missing = _financial_selection(question, evidence)
        selected = {k: v for k, v in selected.items()
                    if v.get("kind") != "annual_comparison" or v.get("item") in {"revenue", "operating_income", "operating_margin"}}
        selected.update({k: v for k, v in evidence.items() if k.startswith("NEWS_") or k in {"PRICE", "PER"}})
    elif strict and news_question and financial_question:
        mode = "mixed"
        selected = {k: v for k, v in evidence.items() if k.startswith("NEWS_")}
        if annual_question:
            financial, missing = _financial_selection(question, evidence)
            selected.update(financial)
        selected.update({k: evidence[k] for k in required if k in evidence})
        if re.search("차트|거래량|추이", question):
            selected.update({k: v for k, v in evidence.items() if k.startswith("HISTORY")})
    elif annual_question and not news_question and not news_followup and not ambiguous_event and not re.search("종합|전체", question):
        mode = "financials"
        selected, missing = _financial_selection(question, evidence)
        selected.update({k: evidence[k] for k in required if k in evidence})
        if re.search("주가|가격|차트|거래량", question):
            selected.update({k: v for k, v in evidence.items() if k == "PRICE" or k.startswith("HISTORY")})
        required_ids = tuple(dict.fromkeys((*required, *(k for k, v in selected.items()
                             if v.get("kind") == "annual_comparison"))))[:16]
    elif required and not news_question and not re.search(r"종합|전체|함께|연결|실적|재무|차트|거래량|원인|위험|올해|내년|전망|향후|앞으로|어떨|사도|살까|매수|투자", question):
        mode = "metric"
        selected = {key: item for key, item in evidence.items() if key in required}

    # 수집 원본 20건은 결과에 보존한다. 모델에 보내는 근거는 네 건으로 제한하며 명시 ID는 보존한다.
    news_keys = [k for k in selected if k.startswith('NEWS_') and k != 'NEWS_STATUS']
    if len(news_keys) > 4:
        terms = set(re.findall(r'[가-힣A-Za-z]{2,}', question)) - {'뉴스','기사','이슈','알려줘','요약해'}
        ranked = sorted(news_keys, key=lambda k: (
            k in required_ids,
            bool('공시' in question and selected[k].get('scope')=='official_disclosure'),
            sum(term in selected[k].get('text','') for term in terms)), reverse=True)
        from src.agents.issues import group_issues, card_groups
        issue_candidates=card_groups(group_issues({k:selected[k] for k in ranked}))
        representatives=[g.evidence_ids[0] for g in issue_candidates]
        ranked=list(dict.fromkeys([*(k for k in ranked if k in required_ids),*representatives,*ranked]))
        keep = set(ranked[:4]) | set(required_ids)
        selected = {k:v for k,v in selected.items() if k not in news_keys or k in keep}

    if mode == "general":
        selected = _fit_general_evidence(selected, required_ids)
    instructions = ["질문의 핵심에 바로 답하며 정중한 입니다·합니다체로 작성합니다.",
                    "질문하지 않은 결측 지표·무관한 뉴스·형식적인 주의문을 덧붙이지 않습니다. 필요한 한계만 한 번 설명합니다."]
    if overview:
        instructions.append("기업의 현재 상황을 묻는 종합 질문입니다. 확인된 실적과 관련 소식 중 중요한 근거로 핵심 상황을 먼저 평가하고 의미를 설명합니다. 가격·PER만 답하거나 모든 수치를 나열하지 않습니다. 과거 연간 실적을 최신 분기 상황으로 표현하지 않으며 사업 원인은 별도 근거가 있어야 합니다.")
    if mode == "news":
        if instructions_note:
            instructions.append(instructions_note)
        instructions += [
            "각 근거의 scope에 따라 제목(headline_only), 검색 발췌(article_excerpt), 확보한 공식 원문(official_disclosure)만 사용합니다. 검색 발췌는 기사 본문 전체가 아니며, 보도는 '관련 보도에 따르면'처럼 귀속합니다.",
            "발행일과 사건 시점은 별개입니다. 원문이 확인하지 않는 사건 발생 순서·원인·실적 영향을 추측하지 않습니다. 공식 원문 한 건을 읽었다고 전체 정정 이력의 최신 유효 값까지 확인한 것으로 쓰지 않습니다.",
            "분석 요청은 제목 반복으로 끝내지 않고 그 사건 단계에서 확정할 수 있는 것과 추가로 확인할 것을 설명합니다.",
            "제목의 사실이 참이어도 덧붙인 해석은 거짓일 수 있다면 회사의 사실로 쓰지 않습니다. 확인할 항목을 이미 진행된 상태로 표현하지 않습니다.",
            "미확인은 이번에 확보한 자료의 한계입니다. '이 제목만으로는 확인할 수 없습니다'처럼 범위를 한정하고, 실제로 사건이 없었다는 뜻으로 쓰지 않습니다.",
            "보도된 사실은 보도에 귀속합니다. 원인·규모가 없다는 이유로 보도된 사건 자체까지 근거 없이 부정하거나 같은 문단에서 번복하지 않습니다.",
            "같은 한계를 표현만 바꿔 반복하지 않습니다. 보도 내용과 질문에 필요한 미확인 사항을 연결하고, 추가 확인 자료는 필요한 것만 간결하게 제시합니다.",
            "관련 기사가 1~2건뿐이거나 동일 사건 중복 기사이면 억지로 3개를 채우지 않고 확인된 건수만큼만 통합 요약하며, 제목에 없는 구체적 목적·효과를 임의 단정하지 않습니다.",
        ]
        if re.search(r'자세|상세|구체',question):
            instructions.append("상세 후속은 확인 사실과 원문에 실제 적힌 설명을 연결합니다. 같은 내용을 표현만 바꿔 두 번 쓰거나 주어·이유 없는 '긍정적으로 작용했다고 설명했습니다'로 분량을 늘리지 않습니다. 발췌에 추가 내용이 없으면 확인된 설명만 간결하게 답하고 새 사실을 만들지 않습니다.")
        if preliminary_request and preliminary:
            instructions.append('확보한 잠정값과 그 의미부터 답합니다. 확정 발표에서 확인할 항목은 앞으로의 점검 사항이며 이미 발표된 사업부 실적/원인으로 만들지 않습니다.')
    if mode == "metric":
        relative_assessment=bool(re.search(r"어떤\s*편|어느\s*정도|수준|높은\s*편|낮은\s*편|적정|비싼|싼\s*편|저평가|고평가|비교",question))
        opening=("조회값과 상대 평가 질문에 직접 답합니다. 이미 설명한 지표의 정의·공식을 반복하지 않습니다. 필요한 비교 자료와 판단 의미에 집중합니다." if relative_assessment else
                 "확인된 값과 그 의미를 먼저 설명하고, 이 값만으로 판단할 수 없는 점을 짧게 덧붙입니다.")
        instructions += [opening,
                         "기준 기간/자료 시각은 출처 상세로 확인할 수 있습니다. 비교 판단에 실제 영향을 주는 한계만 본문에 씁니다. 누락 원인을 만들지 않습니다.",
                         "비교값이 제공되지 않으면 과거 PER·업종 평균을 만들어 비교하지 않습니다. 확인한 값의 의미를 설명합니다."]
        if relative_assessment:
            instructions.append(
                "상대적 수준·평가 질문입니다. 동종 업계 평균이나 과거 시계열 비교 자료가 제공되지 않았다면 '무난한 수준'이나 '고평가·저평가'로 단정하지 말고 상대 평가를 유보한 뒤, 적정 수준 판단을 위해 동종 기업 멀티플·과거 추이 비교가 추가로 필요함을 정중히 안내합니다. 비교 자료가 제공된 경우에만 동일 산출 기준에서 배수 차이(단위: 배, '%p'·'배p' 금지)를 비교합니다."
            )
    if mode == "financials":
        cost_available=any(item.get('cost_bridge_reconciled') for item in selected.values())
        instructions += [
            "비교 자료가 있으면 개선·악화·혼재 결론부터 자연스러운 문장으로 답한 뒤 핵심 수치를 함께 설명합니다. 일반 주의문부터 시작하지 않습니다.",
            ("같은 기간의 원가율·판관비율과 이익률 관계를 먼저 설명합니다. 확보한 비용 구성을 다시 조사하라고 넘기지 않으며 생산 효율/판가/제품 믹스라는 사업 원인은 자료 없이 추가하지 않습니다." if cost_available else
             "동일 기준 연간 비교(CMP)의 매출·영업이익·영업이익률 증감률(change_pct, delta_pp)을 빠짐없이 제시하며, 임의 재계산이나 전년도 자료 부재 주장을 하지 않습니다."),
            ("비용 비중의 상승/하락/유지와 이익률 변화를 실제 계산 방향대로 연결해 자연스러운 문장으로 설명합니다." if cost_available else
             "비교 수치는 '매출은 증감률% 증가했고 영업이익은 증감률% 증가했으며 영업이익률은 차이%p 상승해 실적이 개선되었습니다.'처럼 자연스러운 한국어 문장으로 쓰고 번역투를 피합니다."),
            ("원가 구성의 회계적 관계는 지금 설명할 수 있습니다. 실제 판가/제품 믹스/원재료 가격 같은 경영상 배경은 별도 자료 없이 단정하지 않습니다." if cost_available else
             "매출·영업이익 증감 폭 차이와 영업이익률(%p) 변화를 연결해 수익성 개선·약화·흑자전환 의미를 설명하되, 근거 없는 원가·판관비 등 세부 비용 원인을 지어내지 않고, 문장 끝에 '추가 확인이 필요합니다' 같은 습관적인 회피 문구를 덧붙이지 않습니다."),
            "비교 기간·연결/별도 기준은 하단 출처에 표시되므로 본문 반복 의무는 없으나 복수 기준은 구별하며, 음수/영 분모 성장률 대신 제공된 전환 상태를 씁니다.",
            "빈 비교 항목은 선택 기간 미확인 값이며 다른 연도나 API 미지원으로 단정하지 않습니다.",
        ]
        if causal_question:
            instructions.append(
                "인과·원인 질문입니다. 재무적 결과를 원인으로 순환 논증하지 않습니다. "
                + ("자세한 설명 요청입니다. 원인→계산 근거→매출에서 이익으로 남기는 비중의 변화를 연결해 설명합니다. 검증 문장 나열로 끝내지 않습니다. 사용자 지정 분량은 지킵니다. "
                   if re.search(r'자세|상세|구체|풀어서',question) else "핵심 원인과 의미를 간결하게 설명하며 사용자 지정 분량을 지킵니다. ")
                + ("이번에는 항등식으로 대조한 원가/판관비 비중이 있으므로 그 변화와 이익률을 직접 설명합니다. 사업상 배경은 별도 자료 없이 단정하지 않습니다." if cost_available else
                   "판가·수요·원가 등 구체적 사업 원인은 확인된 사실(매출과 이익 증감 폭의 차이, 마진 변화) 범위 내에서만 설명하며, 지어내거나 '추가 확인이 필요합니다'라는 회피성 면책 문구를 덧붙이지 않습니다.")
            )
    groups = {}
    if strict and mode in {"mixed", "financials"}:
        financial_ids = [k for k, v in selected.items() if v.get("kind") == "annual_comparison"]
        financial_ids += [k for k in required if k in selected and k not in financial_ids]
        if not financial_ids:
            financial_ids = [k for k in selected if k == "HISTORY" or k.startswith("FACT_")]
        if not financial_ids and annual_question and "FINANCIAL_STATUS" in selected:
            financial_ids = ["FINANCIAL_STATUS"]
        groups["financial"] = {"mode": "all", "ids": financial_ids}
        if mode == "mixed":
            instructions.append("복합 질문입니다. 선택한 재무/지표 자료와 관련 뉴스의 두 범위에 모두 직접 답합니다(본문 text에 핵심 실적 비교와 뉴스 요약을 제시하고 blocks에는 관련 뉴스 이슈만 간결히 작성합니다). 한 범위를 생략하거나 무관한 지표로 채우지 않습니다.")
        else:
            instructions.append("비교가 확보됐으면 그 결과로 답변을 마칩니다. 이미 확인된 영업이익·이익률을 사용자에게 다시 확인하라고 하거나 근거 없는 비용 원인을 덧붙이지 않습니다.")
    if strict and (mode in {"mixed", "news"} or news_question):
        news_ids = [k for k in selected if k.startswith("NEWS_") and k != "NEWS_STATUS"]
        if news_ids:
            groups["news"] = {"mode": "any", "ids": news_ids}
        elif "NEWS_STATUS" in selected and selected["NEWS_STATUS"].get("status") != "displayed_issue_unavailable":
            selected = {**selected, "NEWS_STATUS": {**selected["NEWS_STATUS"], "admission_status": "no_supported_articles",
                         "text": "이번에 확보한 제목에서는 요청 대상과 연결해 채택할 기사를 확인하지 못했습니다. 사건 없음이나 제공자 미지원이라는 뜻은 아닙니다."}}
            groups["news"] = {"mode": "all", "ids": ["NEWS_STATUS"]}
            instructions.append("요청한 뉴스 범위는 NEWS_STATUS로 짧게 설명하되 확인된 다른 자료의 분석은 유지합니다. 기사가 원래 없거나 API가 지원하지 않는다고 추측하지 않습니다.")
    if news_followup:
        instructions.append("이전 사용자 질문에서 이어지는 사건에 집중하고 별개 사건으로 주제를 넓히지 않습니다.")
    instructions.extend(parse_presentation(question,has_news=any(k.startswith('NEWS_') and k!='NEWS_STATUS' for k in selected)).instructions())
    return EvidenceSelection(selected, tuple(instructions), mode, required_ids, missing, groups)


def answer_context(question, messages, evidence, required):
    """기존 호출자의 두 값 반환 계약을 유지한다."""
    selection = select_evidence(question, messages, evidence, required)
    return selection.evidence, list(selection.requirements)


# 로컬 모델 문맥(8192토큰)에서 지시문·출력 여유를 뺀 근거 입력의 문자 수 예산. 한국어 JSON은 약 2.2자/토큰이다.
GENERAL_EVIDENCE_CHAR_BUDGET = 11000


def _size(item):
    return len(json.dumps(item, ensure_ascii=False, default=str))


def _fit_general_evidence(selected, required_ids=()):
    """전체 근거를 보내는 일반 질문에서 입력이 문맥을 넘지 않도록 우선순위 순서로 근거를 줄인다.

    버리는 순서: 결측 지표, 비교 근거와 중복되는 원본 재무 사실, 이전 연도 비교, 오래된 시세 이력 외 나머지.
    명시 ID와 최신 연도 비교·주가·PER 같은 핵심 지표는 마지막까지 보존한다.
    """
    protected = set(required_ids)
    if sum(_size(v) for v in selected.values()) <= GENERAL_EVIDENCE_CHAR_BUDGET:
        return selected
    result = dict(selected)

    def drop(keys):
        for key in keys:
            if key not in protected and key in result:
                result.pop(key)
                if sum(_size(v) for v in result.values()) <= GENERAL_EVIDENCE_CHAR_BUDGET:
                    return True
        return False

    if drop([k for k, v in result.items() if v.get("status") == "missing"]):
        return result
    comparisons = {k: v for k, v in result.items() if v.get("kind") == "annual_comparison"}
    if comparisons:
        if drop([k for k, v in result.items() if k.startswith(("FIN_", "FACT_FIN_"))]):
            return result
        latest = max(max(v.get("years") or [0]) for v in comparisons.values())
        if drop([k for k, v in comparisons.items() if max(v.get("years") or [0]) < latest]):
            return result
    if drop([k for k in result if k.startswith("FIN_") or k.startswith("FACT_")]):
        return result
    drop([k for k in result if k.startswith("HISTORY")])
    return result

def model_evidence(evidence):
    """뉴스 발행·조회 시각/URL은 UI 전용이다. 제목 자체의 날짜는 그대로 둔다."""
    result={}
    from src.agents.financial_numbers import use_rate_sentences, verified_sentence
    rates=use_rate_sentences(evidence)
    bases = {(tuple(v.get('years',())),v.get('fs_div'),v.get('stock_code'))
             for v in evidence.values() if v.get('kind')=='annual_comparison'}
    for key,item in evidence.items():
        result[key]={field:value for field,value in item.items()
                     if not (item.get('scope') in {'headline_only','article_excerpt','official_disclosure'}
                             and field in {'published_at','retrieved_at','url','publisher_domain'})}
        if (rates or len(bases)==1) and item.get('kind')=='annual_comparison' or item.get('kind')=='quarterly_comparison':
            sentence=verified_sentence(item)
            if sentence:
                result[key]['verified_sentence']=sentence
        if 'structured_facts' in item:
            fields={'fact_id','item','target','value','unit','direction','financial_period','scope','qualifier','validity','ownership_basis'}
            result[key]['structured_facts']=[{k:v for k,v in f.items() if k in fields and v is not None}
                                             for f in item['structured_facts'] if f.get('status')=='verified'][:8]
            for fact in result[key]['structured_facts']:
                fact['status']='verified'
        if item.get('relationship_proofs'):
            result[key]['relationship_proofs']=[{k:v for k,v in proof.items() if k in
                {'fact_id','subject_name','target_name','relation','quote','source_id','source','scope','published_at','validity'}} for proof in item['relationship_proofs'][:4]]
    return result


def failed_checks(verdict):
    checks = verdict.get("checks") if isinstance(verdict, dict) else None
    if not isinstance(checks, dict) or set(checks) != set(QUALITY_CHECKS):
        return list(QUALITY_CHECKS)
    return [key for key in QUALITY_CHECKS if checks[key] is not True]


def review_units(response, evidence):
    """문장과 명시적 연결 절을 코드에서 나눈다. 완전한 한국어 구문 분석은 아니다."""
    intro_ids = response.lead_evidence_ids
    if not intro_ids and getattr(response, "company_cards", None):
        intro_ids = tuple(k for k, v in evidence.items() if v.get("kind") == "company_profile" or k.startswith("BUSINESS_"))
    sections = [("intro", response.intro, intro_ids)]
    sections += [(f"block_{i}", f"{block.title}\n{block.text}"+ ('\n'+block.implication if block.implication else ''), block.evidence_ids) for i, block in enumerate(response.blocks)]
    if getattr(response, "company_cards", None):
        for card in response.company_cards:
            for s_idx, sec in enumerate(card.sections):
                sections.append((f"card_{card.stock_code}_{sec.role}_{s_idx}", sec.text, sec.evidence_ids))
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


def failed_unit_reviews(verdict, units, *, require_relevance=False):
    """검토 누락·중복·미지 ID를 거절한다. 의미 판정의 정확성은 별도 검수 대상이다."""
    expected = [unit["id"] for unit in units]
    reviews = verdict.get("unit_reviews") if isinstance(verdict, dict) else None
    if not isinstance(reviews, list) or len(reviews) != len(expected):
        return expected
    by_id = {}
    for item in reviews:
        fields = {"id", "reason", "supported", "on_topic", "relevance_evidence_ids"} if require_relevance else {"id", "reason", "supported"}
        if (not isinstance(item, dict) or set(item) != fields
                or not isinstance(item["id"], str) or item["id"] not in expected
                or item["id"] in by_id or not isinstance(item["reason"], str)
                or not item["reason"].strip()):
            return expected
        if require_relevance:
            refs = item["relevance_evidence_ids"]
            unit = next(unit for unit in units if unit["id"] == item["id"])
            if (type(item["on_topic"]) is not bool or not isinstance(refs, list)
                    or any(not isinstance(key, str) or key not in unit["evidence"] for key in refs)
                    or len(refs) != len(set(refs))):
                return expected
            news_ids = {key for key in unit["evidence"] if key.startswith("NEWS_") and key != "NEWS_STATUS"}
            if item["id"].startswith("block_") and news_ids and not (set(refs) & news_ids):
                return expected
        by_id[item["id"]] = item
    return [key for key in expected if by_id[key]["supported"] is not True
            or (require_relevance and by_id[key]["on_topic"] is not True)]
