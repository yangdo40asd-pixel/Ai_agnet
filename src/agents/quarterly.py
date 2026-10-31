"""분기 근거 선택과 수치 검사 어댑터. 연간 근거·검증 규칙을 바꾸지 않는다."""
import re
from decimal import Decimal

from src.data.report_period import quarter_request
from src.models import AppError

KINDS = {"quarterly_financial", "quarterly_comparison"}
LABELS = {"매출": "revenue", "매출액": "revenue", "영업이익": "operating_income",
          "순이익": "net_income", "당기순이익": "net_income", "영업이익률": "operating_margin"}


def contextual_quarter(question, messages=()):
    explicit = quarter_request(question)
    if explicit is not None:
        return explicit
    from src.agents.followup import is_restatement
    if is_restatement(question):
        last = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
        refs = last.get("evidence", ()) if last else ()
        periods = {(max(e.get("years") or [0]), e.get("quarter"), e.get("fs_div"))
                   for e in refs if e.get("kind") in KINDS}
        if len(periods) == 1 and all(e.get("kind") in KINDS for e in refs):
            year, quarter, basis = next(iter(periods))
            from src.data.report_period import QuarterRequest
            # auto/CFS는 자료를 재수집할 이유가 아니다. 직전 명시 요청의 기준 토큰을 유지한다.
            for message in reversed(messages):
                if message.get("role") == "user":
                    prior = quarter_request(str(message.get("text", "")))
                    if prior and not prior.reason and (prior.year, prior.quarter) == (year, quarter):
                        return prior
            return QuarterRequest(year, quarter, basis)
        return None
    # 새 연도·연간·다른 주제는 이전 분기를 승계하지 않는다.
    if (re.search(r"20\d{2}|연간|올해|작년|뉴스|기사|PER|PBR|ROE|주가", question, re.I)
            or not re.search(r"매출|실적|영업이익|이익률|수익성|좋은|괜찮|마진", question)
            or len(question) > 65):
        return None
    value = re.sub(r"[.!?。！？]", "", question).strip()
    followup = (r"(?:그럼|그러면|그\s*회사|이\s*회사|이\s*종목)?\s*"
                r"(?:매출(?:액)?|영업이익률?|이익률|수익성|실적|마진)(?:은|는|이|가)?\s*"
                r"(?:얼마(?:야)?|어때|어떤\s*편(?:이야)?|좋은\s*편(?:이야)?|괜찮(?:아)?|좋아졌어|개선됐어|설명해줘)?")
    evaluation = r"(?:그\s*정도면|그럼|그러면|이\s*정도면)?\s*(?:괜찮(?:아|은\s*실적이야)|좋은\s*편이야|양호한\s*편이야)"
    if not re.fullmatch(followup, value) and not re.fullmatch(evaluation, value):
        return None
    for message in reversed(messages[-8:]):
        if message.get("role") != "user":
            continue
        text = str(message.get("text", ""))
        prior = quarter_request(text)
        if prior is not None:
            return prior
        if re.search(r"연간|20\d{2}|뉴스|기사|PER|주가", text, re.I):
            break
    return None


def market_evidence(question, evidence):
    """복합 요청에서 분기 이외에 명시한 현재 지표·시세 계열도 보존한다."""
    keys = set(re.findall(r"(?<![A-Z])(?:PER|PBR|ROE|EPS|BPS)(?![A-Z])", question.upper()))
    if re.search(r"주가|가격|현재가", question):
        keys.add("PRICE")
    if re.search(r"차트|추이|거래량|주가.{0,15}왜|왜.{0,15}주가", question):
        keys.add("HISTORY")
    return {key: evidence[key] for key in keys if key in evidence}


def selection_data(question, messages, evidence):
    request = contextual_quarter(question, messages)
    if request is None or request.reason:
        return None
    fields = set()
    for item, pattern in (("revenue", "매출"), ("operating_income", r"영업이익(?!률)"),
                          ("net_income", "순이익"), ("operating_margin", "이익률|마진|수익성")):
        if re.search(pattern, question):
            fields.add(item)
    if not fields or re.search(r"실적|재무|왜|원인|이유", question):
        fields.update(("revenue", "operating_income", "operating_margin"))
    selected = {k: v for k, v in evidence.items()
                if v.get("kind") in KINDS and v.get("status") == "ok"
                and v.get("quarter") == request.quarter and v.get("years", [0])[-1] == request.year
                and (request.fs_div is None or v.get("fs_div") == request.fs_div)
                and v.get("item") in fields}
    compared = {(v["item"], v["fs_div"]) for v in selected.values() if v["kind"] == "quarterly_comparison"}
    selected = {k: v for k, v in selected.items()
                if v["kind"] == "quarterly_comparison" or (v["item"], v["fs_div"]) not in compared}
    missing = tuple(sorted(fields - {v["item"] for v in selected.values()}))
    extra = market_evidence(question, evidence)
    if extra and not selected:
        selected["QUARTER_STATUS"] = {"text": f"요청한 {request.year}년 {request.quarter}분기 재무수치는 이번 자료에서 확인하지 못했습니다.",
                                      "value_text": f"요청한 {request.year}년 {request.quarter}분기 재무수치는 이번 자료에서 확인하지 못했습니다",
                                      "status": "period_unconfirmed", "source": "이번 수집 자료"}
    collection = evidence.get("Q_COLLECTION_STATUS", {})
    if ("QUARTER_STATUS" in selected and collection.get("request_token") == request.token
            and collection.get("status") == "failed"):
        selected["QUARTER_STATUS"].update(
            text="이번 분기 재무자료 조회에 실패했습니다. 확인된 시세 자료는 별도로 표시합니다.",
            value_text="이번 분기 재무자료 조회에 실패했습니다. 확인된 시세 자료는 별도로 표시합니다")
    selected.update(extra)
    return dict(evidence=selected, reason="quarterly", required_ids=tuple(selected), missing=missing,
                requirements=(
                    "실적 평가라면 확인된 개선·악화·혼재 결론부터 답하고 핵심 수치와 의미를 연결합니다. 정중한 입니다·합니다체를 씁니다.",
                    f"요청 범위는 {request.year}년 {request.quarter}분기 3개월 실적입니다. 누적·연간·전분기와 바꾸지 않습니다.",
                    "quarterly_comparison은 동일 분기의 전년 동기 비교입니다. 제공된 verified_sentence 또는 값 자리표시자를 사용하고 %와 %p를 구분합니다.",
                    "단일 지표 조회는 수치·변화·의미를 합쳐 간결하게 답합니다. 회사명·연도·현재값으로 도입한 뒤 같은 값의 비교 문장을 다시 붙이지 않습니다.",
                    "이익률의 뜻은 매출에서 영업이익으로 남기는 비중으로 풀어 설명합니다. 앞서 표시한 비교 기간을 의미 문장에 다시 붙여 '대비'를 겹쳐 쓰지 않습니다.",
                    "이익률 근거만 있으면 매출에서 영업이익으로 남긴 비중을 설명합니다. 매출과 영업이익 각각의 증가 여부나 구체적 사업 원인을 이익률만으로 단정하지 않습니다.",
                    "같은 수치나 변화폭을 여러 문장에서 반복하지 않습니다. 단일 지표 후속 질문은 확인된 수치 변화 한 번과 의미 설명으로 간결하게 답합니다.",
                    "당기 금액만 있으면 그 값을 설명합니다. 전년값이나 증가율을 만들지 않으며 질문하지 않은 결측 항목을 나열하지 않습니다.",
                    "QUARTER_STATUS가 있으면 그 자리표시자로 해당 분기 미확보를 짧게 알리고 확인된 주가·지표 답변은 유지합니다. 전기/다른 연간 값으로 대체하지 않습니다.",
                    "주가·PER 등도 질문했다면 해당 근거를 빠뜨리지 않습니다. 현재 시세·배수의 기준일을 분기 실적의 기간과 혼동하지 않으며 실적만으로 주가 변화 원인을 단정하지 않습니다.",
                    "자료에 없는 사업부·제품·원가 원인을 추가하지 않습니다. 기간·회계 기준은 출처에 표시하며 필요한 경우만 본문에 적습니다.",
                ))


def mask_quarterly_numbers(text, evidence):
    """동일 분기의 검증된 숫자만 기존 산술 검사에 연결한다. 표시값·원본 kind는 유지한다."""
    facts = {k: v for k, v in evidence.items() if v.get("kind") in KINDS and v.get("status") == "ok"}
    if not facts:
        return text
    bases = {(v.get("quarter"), v.get("fs_div"), v.get("stock_code")) for v in facts.values()}
    if len(bases) != 1 or any(v.get("kind") == "annual_comparison" for v in evidence.values()):
        return text
    quarter = next(iter(bases))[0]
    years = {int(y) for v in facts.values() for y in v.get("years", ())}
    adapted = {k: dict(v, kind="annual_comparison") for k, v in facts.items()
               if v["kind"] == "quarterly_comparison"}
    if not adapted and len(years) != 1:
        return text
    period = re.compile(r"(?:(20\d{2})년\s*)?([1-4])\s*분기")
    def check_period(match):
        if int(match[2]) != quarter or match[1] and int(match[1]) not in years:
            raise AppError("chat_numbers", "분기 근거의 연도·분기가 답변과 일치하지 않습니다.")
        # 비교의 연도는 기존 항목/전기·당기 검사에 남긴다. 양쪽 연도가 존재해도 값을 바꿔 쓰면 거절한다.
        return f"{match[1]}년 " if adapted and match[1] else ""
    checked = period.sub(check_period, text)
    checked = re.sub(r"전년\s*동기\s*대비", "전년 대비", checked)
    # 숫자는 그대로 두고 '현재값으로, 전년 대비 변화폭'의 쉼표만 산술 검사의 기존 문형에 맞춘다.
    checked = re.sub(r"(로),\s*(?=(?:전년|동기)\s*대비)", r"\1 ", checked)
    if re.search(r"전분기|직전\s*분기", checked):
        raise AppError("chat_numbers", "전년 동기를 전분기 비교로 바꿀 수 없습니다.")
    # 연간 함수에는 숫자·방향 계산에 필요한 복사본만 전달한다. 원본/모델/출처는 quarterly kind를 유지한다.
    if all(v.get("period_type") == "quarter_3m" for v in facts.values()):
        checked = re.sub(r"(?<![\d.,])3\s*개월(?![\d])", "개월", checked)
    # 비교 없는 당분기 값은 정확한 항목·표시값의 단독 문장 또는 값 자리표시자로만 허용한다.
    if not adapted:
        pattern = re.compile(r"(?P<label>매출액|매출|영업이익률|영업이익|당기순이익|순이익)(?:은|는|이|가)\s*(?P<value>-?[0-9,]+(?:\.[0-9]+)?(?:억원|%))(?=\s*(?:입니다|였습니다|이었습니다))")
        def check_value(match):
            matches = [v for v in facts.values() if v["item"] == LABELS[match["label"]]]
            if len(matches) != 1 or matches[0]["value_text"] != match["value"]:
                raise AppError("chat_numbers", "당분기 항목과 금액을 확인하지 못했습니다.")
            return match["label"]
        checked = pattern.sub(check_value, checked)
    # '당기 영업이익률은 X%입니다'도 항목·당기 연도·표시값이 일치할 때만 허용한다.
    # 증감률·다른 항목의 %를 이 값으로 허용하지 않는다.
    margin_pattern = re.compile(r"(?:(?P<year>20\d{2})년\s*|(?<![가-힣A-Za-z]))"
                                r"영업이익률(?:은|이|는|가)\s*(?P<value>-?[0-9,]+(?:\.[0-9]+)?%)입니다")
    def current_margin(match):
        from src.formatting import format_percent
        candidates = [v for v in facts.values() if v.get("item") == "operating_margin"]
        if len(candidates) != 1:
            raise AppError("chat_numbers", "당분기 영업이익률의 근거를 확인하지 못했습니다.")
        fact = candidates[0]
        if (match["value"] != format_percent(Decimal(fact.get("current", fact.get("value"))))
                or match["year"] and int(match["year"]) != max(fact["years"])):
            raise AppError("chat_numbers", "당분기 영업이익률의 값·연도가 일치하지 않습니다.")
        return "영업이익률입니다"
    checked = margin_pattern.sub(current_margin, checked)
    from src.agents.financial_numbers import mask_verified_comparisons
    return mask_verified_comparisons(checked, adapted)
