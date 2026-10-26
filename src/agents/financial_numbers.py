"""연간 비교의 직접 쓴 숫자를 제한적으로 대조한다. 의미 검증을 대체하지 않는다."""
from decimal import Decimal, InvalidOperation
import re
from src.models import AppError


_ITEMS = {"매출": "revenue", "매출액": "revenue", "영업이익": "operating_income",
          "당기순이익": "net_income", "순이익": "net_income", "영업이익률": "operating_margin"}
_RATE = re.compile(
    r"(?<![가-힣A-Za-z])(?P<item>영업이익률|영업이익|당기순이익|순이익|매출액|매출)"
    r"(?:은|는|이|가|도)?\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>%p|%)\s*"
    r"(?P<direction>증가|감소|상승|하락)")
_PERIOD = re.compile(r"(?<!\d)(20\d{2})년\s*(?:대비|에서|→)\s*(20\d{2})년")
_YEAR = re.compile(r"(?<!\d)(20\d{2})년(?:에는|에도|에|의|은|는)?")


def mask_verified_comparisons(text, evidence):
    """일치한 표현의 숫자만 검사 사본에서 지운다. 표시 원문은 바꾸지 않는다.

    동일 항목·기간·연결/별도 근거가 하나일 때만 직접 수치를 허용한다.
    복수 비교 기준, 임의 금액, 절대 이익률은 기존 값 자리표시자를 사용한다.
    수치가 다른 항목에 존재한다는 이유로 허용하지 않는다.
    """
    # 비교 연도는 같은 문장의 수치 주장에만 귀속한다. 다른 사건의 연도를 빌리지 않는다.
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    return "\n".join(_mask_sentence(part, evidence) for part in parts)


def _mask_sentence(text, evidence):
    facts = [v for v in evidence.values() if v.get("kind") == "annual_comparison"
             and v.get("status") == "ok"]
    used, spans = [], []

    def reject():
        raise AppError("chat_numbers", "재무 수치의 항목·단위·기간·증감 방향을 확인하지 못했습니다.")

    def rate(match):
        candidates = [f for f in facts if f.get("item") == _ITEMS[match["item"]]]
        if len(candidates) != 1:
            return reject()
        fact = candidates[0]
        margin = fact["item"] == "operating_margin"
        if match["unit"] != ("%p" if margin else "%"):
            return reject()
        raw = fact.get("delta_pp" if margin else "change_pct")
        if raw is None:
            return reject()
        try:
            value = Decimal(str(raw))
            number = Decimal(match["number"])
            if not value.is_finite() or number != abs(value).quantize(Decimal("0.01")):
                return reject()
        except InvalidOperation:
            return reject()
        directions = {"증가", "상승"} if value > 0 else {"감소", "하락"} if value < 0 else set()
        if match["direction"] not in directions:
            return reject()
        used.append((match, fact))
        spans.append(match.span("number"))

    for match in _RATE.finditer(text):
        rate(match)
    # 연도는 실제 대조한 숫자의 공통 기간과 순서가 맞을 때만 인정한다.
    bases = {(tuple(f.get("years", [])), f.get("fs_div"), f.get("stock_code")) for _, f in used}
    if len(bases) == 1:
        years = next(iter(bases))[0]
        pairs = list(_PERIOD.finditer(text))
        for pair in pairs:
            if (int(pair[1]), int(pair[2])) != years:
                reject()
            if any(pair.end() <= claim.start()
                   and re.fullmatch(r"\s*(?:에는|에도|에|의|은|는)?\s*", text[pair.end():claim.start()])
                   for claim, _ in used):
                spans.extend((pair.span(1), pair.span(2)))
        for year in _YEAR.finditer(text):
            if any(pair.start() <= year.start() < pair.end() for pair in pairs):
                continue
            # '당기년 매출은 …' 또는 '매출이 … 증가한 당기년에도'만 허용한다.
            # 연도만 일치하는 무관한 공시/설립/계약 문장의 숫자는 남겨 거절한다.
            linked = any(
                (year.end() <= claim.start() and not text[year.end():claim.start()].strip())
                or (claim.end() <= year.start() and re.fullmatch(r"한\s*", text[claim.end():year.start()]))
                for claim, _ in used)
            if linked and years and int(year[1]) == years[-1]:
                spans.append(year.span(1))
    return "".join(char for index, char in enumerate(text)
                   if not (char.isdigit() and any(start <= index < end for start, end in spans)))
