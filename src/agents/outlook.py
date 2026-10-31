"""전망 질문의 근거 선택과 설명 기준. 예측 수치·회사 전망을 생성하지 않는다."""
import re

_OUTLOOK = re.compile(r"올해|내년|전망|향후|앞으로|어떨")


def is_outlook(question):
    return bool(_OUTLOOK.search(question))


def is_investment_judgement(question):
    return bool(re.search(r"사도|살까|사야|매수해도|매수할까|투자해도|투자할까",question))


def uses_judgement_style(question):
    return is_outlook(question) or is_investment_judgement(question)


def _price_focus(question, messages=None):
    if not "주가" in question and re.search(r"판매\s*가격|제품\s*가격|원재료\s*가격",question):
        return False
    if bool(re.search(r"주가|가격",question) or
            re.search(r"오를|상승",question) and not re.search(r"실적|매출|이익|수익|마진",question)):
        return True
    if messages and not re.search(r"실적|매출|이익|수익|마진|성장", question):
        last_user = next((str(m.get("text", "")) for m in reversed(messages) if m.get("role") == "user"), "")
        if last_user and _price_focus(last_user):
            return True
    return False


def _sentence_focus(question, messages=None):
    if _price_focus(question, messages=messages):
        # 판매 가격은 주가 질문의 답이 아니다.
        return r"주가|주식\s*(?:가격|시세|값)" if "주가" in question else r"주가|(?<!판매)(?<!제품)가격"
    return r"올해|내년|향후|앞으로|지속|이어질|판단|전망"


def requirements(question, messages=None):
    price=_price_focus(question, messages=messages)
    return (
        "전망 질문입니다. 먼저 확인된 개선 흐름이 앞으로도 이어질지에 답합니다. '향후 수요에 따라 결정될 전망입니다'라는 일반론으로 시작하지 않습니다. 과거 실적만으로 지속 여부를 판단할 수 없으면 그 경계를 짚고 판단 조건을 설명합니다.",
        "앞선 대화에서 설명한 과거 실적 숫자는 반복하지 않고 핵심 흐름만 짧게 연결합니다. 처음 필요한 숫자를 인용하더라도 질문에 필요한 한 가지 정도만 골라 설명하며 전 지표를 다시 나열하지 않습니다.",
        "아직 오지 않은 해의 확정 실적이 없다거나 회사 계획이 포함되어 있지 않다는 식의 불필요한 부재 해명 문장은 절대 작성하지 않습니다. 미래 전망은 확인된 과거 실적 흐름과 향후 지속 여부를 결정짓는 핵심 요인(수요·판매가격·비용 구조 등)으로만 간결하게 설명합니다.",
        "일반적인 판단 조건은 '지속 여부는 수요·판매가격·비용 구조에 달려 있습니다'처럼 핵심 요인으로 간결하게 설명합니다. '그 요인에 따라 결정될 전망입니다'라는 회사의 예측으로 바꾸지 않으며, '추가 자료 확인이 필요합니다' 같은 습관적 면책·안내 문구를 덧붙이지 않습니다. 원문에 없는 제품군·회사 계획·투자 진행을 보태지 않습니다.",
        ("과거 실적 개선이 미래 주가 상승을 보장하지 않는 이유와 앞으로 볼 이익 기대·현재 가격의 관계를 간결하게 설명합니다. '~에 따라 결정될 전망입니다'처럼 단정하거나 예측하지 말고, '과거 실적 개선이 주가 상승을 보장하지 않으므로, 향후 이익에 대한 기대와 현재 가격 수준을 함께 살펴 판단해야 합니다'처럼 관찰할 조건으로 설명합니다. 근거 없는 주가 방향·투자심리·확률을 만들지 않습니다." if price else
         "과거 개선 흐름과 앞으로 지속될 조건을 구별합니다. 수요·가격·비용·회사 계획은 확인된 자료가 있을 때만 실제 회사 상황으로 설명하고 없으면 판단할 조건으로만 제시합니다."),
    )


def concept_reference():
    return {"전망 판단 원리": (
        "확인된 과거 실적은 이미 발생한 결과이며 다음 해 실적이나 주가의 확정 예측이 아니다.",
        "PER 조회값은 주가/주당순이익의 배수다. 동종·과거의 같은 기준 비교가 없으면 그 값이 낮다거나 주가가 이익 대비 낮은 수준이라고 평가할 수 없다. 사용자의 낮다는 표현을 확인된 상대 평가로 받아들이지 않는다.",
        "주가를 판단할 때는 미래 이익에 대한 기대와 그 기대에 비해 현재 가격이 어떤 수준인지 함께 본다. 과거 이익 증가만으로 저평가나 향후 주가 상승이 보장되지 않는다.",
        "실적 개선의 지속 여부는 앞으로의 수요·판매가격·비용 구조와 같은 요인에 좌우된다. 이는 일반적인 판단 기준이며 해당 기업에서 실제 변화가 확인됐다는 주장이 아니다.",
    )}


def select_background(question,evidence,required,messages=None):
    if not is_outlook(question):
        return None
    from src.agents.issues import group_issues
    # 회사 실적 전망에 마케팅/순위 기사로 인과를 채우지 않는다.
    allowed=set()
    for group in group_issues(evidence):
        if group.kind in {"earnings","contract","investment","regulatory","legal","product"}:
            for key in group.evidence_ids:
                if not re.search(r"품질만족|수상|순위|세계\s*\d+위|브랜드\s*가치",evidence[key].get("text","")):
                    allowed.add(key)
    comparisons={k:v for k,v in evidence.items() if v.get("kind")=="annual_comparison"
                 and v.get("item") in {"revenue","operating_income","operating_margin"}}
    selected={**comparisons,**{k:v for k,v in evidence.items() if k in allowed or k in required}}
    if not comparisons:
        selected.update({k:v for k,v in evidence.items() if k=="FINANCIAL_STATUS"})
    background=[k for k in selected if k not in required and k!="FINANCIAL_STATUS"]
    groups={"outlook_background":{"mode":"any","ids":background}} if background else {}
    return {"evidence":selected,"requirements":requirements(question,messages=messages),"reason":"outlook",
            "required_ids":tuple(required),"required_groups":groups}


def answer_context(question,evidence,messages=None):
    """모델에 줄 주장 역할을 구분한다. 확인 자료 없는 예측값을 보충하지 않는다."""
    horizon="올해" if "올해" in question else "내년" if "내년" in question else "향후"
    return {"requested_horizon":horizon,"preserve_horizon":"다른 연도로 바꾸지 않습니다. 미래 확정 실적이 없다는 당연한 문구 대신 필요한 전망 자료의 범위만 씁니다.",
            "focus":"investment_judgement" if is_investment_judgement(question) else "price_outlook" if _price_focus(question,messages=messages) else "earnings_outlook",
            "historical_facts":"과거 확인 결과로만 짧게 사용하며 미래의 결과로 바꾸지 않습니다.",
            "future_claim":"요청 기간의 회사 계획·예상치 등 실제 근거가 있어야 주장할 수 있습니다.",
            "criteria":"일반 원리는 앞으로 확인할 판단 기준입니다. 회사의 실제 상황·예측으로 서술하지 않습니다."}


GENERATION_INSTRUCTION = """확인된 자료로 한국어 금융 전망·투자 판단 질문에 직접 답합니다. 입니다·합니다체를 씁니다.
질문과 outlook_answer_context의 역할 구분을 따릅니다. 첫 문장에서 과거 개선과 앞으로의 지속 여부를 구분해 직접 답하고, 앞으로 확인할 판단 조건을 자연스럽게 연결합니다. 앞서 설명한 재무 숫자·PER 뜻을 다시 나열하지 않습니다. 사용자가 숫자를 요청하지 않은 전망 후속에서는 과거 흐름을 말로 짧게 설명하면 충분합니다.
확인된 과거 결과, 확보한 회사 계획·보도, 일반적인 판단 기준은 서로 다릅니다. 판단 기준은 확인할 항목으로만 쓰고 실제 회사 상황·진행 중인 계획·확정 예측으로 만들지 않습니다. 원문에 없는 제품군·사업 원인·목표주가·미래 수치·투자심리를 보태지 않습니다. 과거 실적만으로 미래 상승을 보장하거나 매매를 지시하지 않습니다.
자료가 부족하면 현재 질문에 꼭 필요한 회사 계획·최신 자료의 미확보 범위만 한 번 짧게 설명합니다. 미래 확정 연간 실적이 없다는 당연한 안내, 요청하지 않은 결측 지표, 반복 경고를 붙이지 않습니다.
evidence의 회사·기간·회계기준·단위·값·방향·잠정/확정 범위를 유지합니다. 실제 사용한 자료의 ID를 evidence_ids에 인용합니다. 일반 원리는 concept_reference로 대조하며 과거 AI 문장은 사실 근거가 아닙니다. 숫자를 요청했을 때도 임의 수치/동종 평균을 만들지 않고, 금융 지표는 실제 키의 {{PER}} 같은 자리표시자, 연간 비교는 확인된 값과 방향, 뉴스는 확보한 원문 표기만 씁니다.
지표 이름은 PER처럼 글자로 쓴 다음 {{PER}} 값을 붙입니다. '현재 {{PER}}은'처럼 값으로 지표 이름을 대신하지 않으며 같은 값을 두 번 되풀이하지 않습니다.
PER 값만 보고 주가가 이익 대비 낮은 수준이라고 쓰지 않습니다. 사용자가 낮다고 말했더라도 비교 자료로 확인된 사실이 아닙니다. 배수의 뜻과 상대 평가를 구별하며 PER 정의를 앞 대화에서 설명했다면 다시 반복하지 않습니다.
보도는 보도에 귀속합니다. 검색 발췌를 공식 원문이나 확정 인과로 바꾸지 않습니다. 뉴스 관계/독립 사건 및 required_groups를 지킵니다. 주가 변화 원인을 실적만으로 단정하지 않습니다.
JSON 최상위는 text,evidence_ids,follow_up,blocks입니다. answer_style=plain이면 blocks=[]입니다. issues이면 blocks에 title,text,evidence_ids,implication을 쓰고 issue_groups 밖 사건은 만들지 않습니다. implication은 별도 근거가 없으면 null입니다. 후속 질문은 필요한 명확화 외에는 빈 문자열입니다. 본문에 근거 번호·URL을 직접 쓰지 않습니다.
기본은 짧은 두세 문장입니다. presentation의 사용자 문장/줄 수를 우선하고, summary_of_question이 있으면 원래 질문에 대한 직전 결론을 요약합니다. 숫자 나열로 전망의 핵심을 지우지 않습니다. 검증 피드백이 있으면 근거를 보존하며 해당 문제를 수정합니다."""


def generation_request(request):
    """전망 생성에는 금액 문장 예시의 복사 유도를 제외한다. 검증·fallback 원본은 보존한다."""
    view=dict(request)
    view.pop("verified_sentence_examples",None)
    view.pop("comparison_style",None)
    view.pop("comparison_value_placeholders",None)
    if "answer_requirements" in view:
        view["answer_requirements"] = [
            r for r in view["answer_requirements"]
            if "comparison_value_placeholders" not in r
        ]
    history=list(request.get("conversation",()))
    if request.get("summary_of_question"):
        # 요약은 직전 답변을 대상으로 삼되 더 오래된 수치 문장을 복사하지 않는다.
        view["conversation"]=history[-2:]
    elif not re.search(r"아까|이전\s*답변|앞선\s*답변|왜\s*틀|답변.{0,10}문제",request.get("question","")):
        # 대상/기간/근거는 이미 현재 요청에 구조화돼 있다. 이전 AI의 서술을
        # 새 전망 초안으로 복사하지 않도록 전송 사본에서만 제외한다.
        view["conversation"]=[m for m in history if m.get("role")!="assistant"]
    return view


def enforce_scope(response,question,messages=None):
    """예측에 필요한 자료 부족과 당연한 미래 확정실적 부재를 구분한다."""
    from src.models import AppError
    if is_outlook(question):
        first=re.split(r'(?<=[.!?])\s+|\n+',response.intro)[0]
        if _price_focus(question,messages=messages) and not re.search(_sentence_focus(question,messages=messages),first):
            raise AppError("chat_outlook_scope","주가 질문의 첫 문장이 과거 실적 나열로 시작했습니다.")
        if not _price_focus(question,messages=messages) and not re.search(r"올해|내년|향후|앞으로|지속|이어질|판단|전망",first):
            raise AppError("chat_outlook_scope","전망 질문의 첫 문장이 과거 결과로만 끝났습니다.")
    if "확정" not in question:
        for sentence in re.split(r'(?<=[.!?])\s+|\n+',response.intro):
            if (re.search(r'(?:내년|미래|이후).{0,20}확정(?:된)?.{0,10}(?:연간\s*)?실적(?!\s*(?:계획|전망|예상))',sentence)
                    and re.search(r'없|미포함|포함되어\s*있지|미확보',sentence)):
                raise AppError("chat_outlook_scope","미래의 확정 실적 부재를 불필요하게 덧붙였습니다.")
    if "올해" in question and "내년" not in question and "내년" in response.intro and "올해" not in response.intro:
        raise AppError("chat_outlook_scope","올해 질문을 내년 전망으로 바꾸었습니다.")
    return response


def arrange_conclusion(response,question,messages=None):
    """생성한 문장 자체는 바꾸지 않고 질문에 답하는 문장을 앞에 배치한다.

    동일 도입의 인용 범위를 보존한다. 재배치한 표시 문장도 뒤의 의미 심사를
    통과해야 하며, 근거 없는 문장을 승인하거나 새 결론을 만들지 않는다.
    """
    from dataclasses import replace
    from src.agents.presentation import sentences
    if not is_outlook(question):
        return response
    parts=sentences(response.intro)
    focus=_sentence_focus(question,messages=messages)
    if not parts or re.search(focus,parts[0]):
        return response
    index=next((i for i,part in enumerate(parts[1:],1) if re.search(focus,part)),None)
    if index is None:
        return response
    separator="\n" if "\n" in response.intro else " "
    return replace(response,intro=separator.join([parts[index],*parts[:index],*parts[index+1:]]))
