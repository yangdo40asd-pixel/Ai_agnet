"""연간 비교의 직접 쓴 숫자를 제한적으로 대조한다. 의미 검증을 대체하지 않는다."""
from decimal import Decimal, InvalidOperation
import re
from src.formatting import format_eok, format_percent
from src.models import AppError


_ITEMS = {"매출": "revenue", "매출액": "revenue", "영업이익": "operating_income",
          "당기순이익": "net_income", "순이익": "net_income", "영업이익률": "operating_margin",
          '매출원가율':'cost_of_sales_ratio','판매관리비율':'selling_expenses_ratio','판관비율':'selling_expenses_ratio'}
_PERCENT_ITEMS={'operating_margin','cost_of_sales_ratio','selling_expenses_ratio'}
_VAL = r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:조\s*원|조|억원|%)"
_RATE = re.compile(
    r"(?<![가-힣A-Za-z])(?P<item>매출원가율|판매관리비율|판관비율|영업이익률|영업이익|당기순이익|순이익|매출액|매출)"
    r"(?:\s*(?:증가율|감소율|상승폭|하락폭|변동폭))?(?:은|는|이|가|도|을|를)?\s*(?:(?:또한|역시)\s+)?"
    r"(?:(?:전년(?:도)?|전기|동기)\s*대비\s*)?"
    r"(?:20\d{2}년\s*대비\s*20\d{2}년(?:\s*(?:연간|연결))?(?:\s*기준)?\s*)?"
    rf"(?:(?:(?P<prev_year>20\d{{2}})년\s*)?(?P<prev>{_VAL})\s*(?:에서|→)\s*(?:(?P<curr_year>20\d{{2}})년\s*)?(?P<curr_pair>{_VAL})\s*(?:으로|로)?\s*(?:(?:전년(?:도)?|전기|동기)\s*대비\s*)?|"
    rf"(?P<curr_pre>{_VAL})\s*(?:으로|로)\s*(?:(?:전년(?:도)?|전기|동기)\s*대비\s*)?)?"
    r"(?:약\s*)?\(?(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>%p|%)\)?\s*"
    r"(?P<direction>증가|감소|상승|하락)"
    rf"(?:(?:한|해|하여)\s*(?:(?P<year_post>20\d{{2}})년\s*)?(?P<curr_post>{_VAL}))?")
_PAREN_RATE = re.compile(
    r"(?<![가-힣A-Za-z])(?P<item>매출원가율|판매관리비율|판관비율|영업이익률|영업이익|당기순이익|순이익|매출액|매출)\s*"
    r"(?P<direction>증가|감소|상승|하락)(?:율|폭)\s*\(\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>%p|%)\s*\)")
_AMOUNT = re.compile(
    r"(?:(?P<year>20\d{2})년\s*(?:연간\s*)?)?(?<![가-힣A-Za-z])(?P<item>영업이익률|영업이익|당기순이익|순이익|매출액|매출)(?:은|는|이|가)?\s*"
    r"(?P<amount>-?\d+(?:,\d{3})*(?:\.\d+)?(?:억원|%))\s*"
    r"(?P<verb>입니다|이었습니다|였습니다|으로\s*집계되었습니다|을\s*기록했습니다|를\s*기록했습니다|를\s*기록하며|을\s*기록하며|를\s*기록했으나|을\s*기록했으나|으로\s*적자(?:를\s*기록했습니다|가\s*지속되었습니다|입니다|폭이\s*(?:일부\s*)?(?:축소|확대|지속|되었|했)|가\s*(?:축소|확대|지속)(?:되었습니다|했습니다|되었으나|했으나)?)|으로|로)")
_DELTA = re.compile(
    r"(?:(?P<prev_year>20\d{2})년\s*(?P<prev>-?\d+(?:\.\d+)?억원)\s*대비\s*)?"
    r"(?:적자\s*(?:규모|폭)?(?:는|은)?\s*)?"
    r"(?P<amount>\d+(?:,\d{3})*(?:\.\d+)?억원)\s*(?P<kind>축소|확대|감소|증가)")
_YEAR_GAP = r"\s*(?:(?:연간|연결|실적|기준|대비|전년도|전년|확정|최근|잠정)\s*)*"
_YEAR_LABEL = re.compile(r"(?<!\d)(20\d{2})년\s*(?:(?:확정된|확정|확인된|연간|연결)\s*)*(?:영업\s*)?(?:실적|재무)")
_PERIOD = re.compile(r"(?<!\d)(20\d{2})년\s*(?:대비|에서|→)\s*(20\d{2})년")
_YEAR = re.compile(r"(?<!\d)(20\d{2})년(?:에는|에도|에|의|은|는)?")
_COMPARISON_MARKER = re.compile(
    r"(?<![가-힣A-Za-z])(?P<item>매출원가율|판매관리비율|판관비율|영업이익률|영업이익|당기순이익|순이익|매출액|매출)"
    r"(?:은|는|이|가|도)?\s*\{\{(?P<id>[A-Z0-9_a-z-]+)\}\}")
_COST_PAIR = re.compile(r'(?P<item>매출원가율|판매관리비율|판관비율)(?:은|는|이|가)?\s*'
    r'(?P<previous>\d+(?:\.\d+)?)%\s*(?:에서|→)\s*(?P<current>\d+(?:\.\d+)?)%\s*(?:로|으로)?\s*'
    r'(?P<direction>낮아|높아|하락|상승|유지|같)')
_COST_STABLE = re.compile(r'(?P<item>매출원가율|판매관리비율|판관비율)(?:은|는|이|가)?\s*'
    r'(?P<current>\d+(?:\.\d+)?)%\s*(?:로|으로)?\s*(?:유지|같)')
_MARGIN_PAIR = re.compile(
    r'(?P<item>영업이익률)(?:은|는|이|가)?\s*'
    r'(?P<previous>-?\d+(?:\.\d+)?)%\s*(?:에서|→)\s*(?P<current>-?\d+(?:\.\d+)?)%\s*(?:로|으로)?\s*'
    r'(?P<direction>상승|하락|개선|악화|유지)')

_TRANSITION = re.compile(
    r'(?P<item>영업이익|당기순이익|순이익)(?:은|는|이|가)?\s*'
    r'(?P<previous>-?\d+(?:,\d{3})*(?:\.\d+)?억\s*원)\s*에서\s*'
    r'(?P<current>-?\d+(?:,\d{3})*(?:\.\d+)?억\s*원)\s*(?:으로|로)\s*'
    r'(?P<state>적자|흑자)\s*(?:폭이\s*|폭\s*)?(?P<kind>전환|축소|지속|확대)')


def normalize_financial_units(text: str, evidence: dict) -> str:
    """영업이익률 변동폭(delta_pp) 수치가 정확히 일치할 때 %를 %p로 정규화한다."""
    if not isinstance(text, str) or not evidence:
        return text
    margins = [
        v for v in evidence.values()
        if isinstance(v, dict) and v.get("kind") == "annual_comparison"
        and v.get("status") == "ok" and v.get("item") == "operating_margin"
        and v.get("delta_pp") is not None
    ]
    if len(margins) != 1:
        return text
    try:
        expected = abs(Decimal(str(margins[0]["delta_pp"]))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return text

    def _fix_unit(match: re.Match) -> str:
        try:
            num = Decimal(match.group("number")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return match.group(0)
        if num == expected:
            return f"{match.group('prefix')}{match.group('number')}%p{match.group('suffix')}"
        return match.group(0)

    pattern = re.compile(
        r"(?P<prefix>영업이익률(?:은|는|이|가|도)?\s*(?:(?:전년(?:도)?|전기|동기)\s*대비\s*)?(?:\d+(?:\.\d+)?%\s*(?:에서|→)\s*\d+(?:\.\d+)?%\s*(?:으로|로)?\s*)?(?:약\s*)?)"
        r"(?P<number>\d+(?:\.\d+)?)\s*%(?!p)"
        r"(?P<suffix>\s*(?:증가|감소|상승|하락))"
    )
    return pattern.sub(_fix_unit, text)


def use_rate_sentences(evidence):
    """단일 기준의 유효한 증감률만 직접 문장 형식으로 제한한다."""
    comparisons = [item for item in evidence.values() if item.get("kind") == "annual_comparison"]
    bases = {(tuple(item["years"]), item["fs_div"], item.get("stock_code")) for item in comparisons}
    if not comparisons or len(bases) != 1:
        return False
    for item in comparisons:
        if item.get("status") != "ok":
            return False
        try:
            value = Decimal(str(item.get("delta_pp" if item["item"] in _PERCENT_ITEMS else "change_pct")))
        except (InvalidOperation, ValueError):
            return False
        # 0·계산 불가·복수 기준은 기존 완전 비교 표현으로 보존한다.
        if not value.is_finite() or value == 0:
            return False
    return True


def _amount_matches(text_amount: str, display_amount: str) -> bool:
    if not text_amount or not display_amount:
        return False
    t = re.sub(r"\s+", "", text_amount)
    d = re.sub(r"\s+", "", display_amount)
    if t == d:
        return True
    if ("조원" in t or "조" in t) and "억원" in d:
        try:
            num_t = Decimal(re.sub(r"[^\d.-]", "", t))
            num_d = Decimal(re.sub(r"[^\d.-]", "", d))
            jo_from_d = num_d / Decimal("10000")
            return (num_t == jo_from_d
                    or num_t == jo_from_d.quantize(Decimal("0.1"))
                    or num_t == jo_from_d.quantize(Decimal("0.01")))
        except Exception:
            return False
    if "억원" in t and "억원" in d:
        try:
            num_t = Decimal(re.sub(r"[^\d.-]", "", t))
            num_d = Decimal(re.sub(r"[^\d.-]", "", d))
            return num_t == num_d or num_t.quantize(Decimal("0.1")) == num_d.quantize(Decimal("0.1"))
        except Exception:
            return False
    return False

def _display_value(fact, field):
    raw = fact.get(field)
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
        if not value.is_finite():
            return None
    except InvalidOperation:
        return None
    return format_percent(value) if fact.get("item") in _PERCENT_ITEMS else format_eok(value)


_SENTENCE_LABELS = {"revenue": "매출", "operating_income": "영업이익", "net_income": "당기순이익",
                    "operating_margin": "영업이익률"}


def verified_sentence(fact):
    """검증기가 그대로 통과시키는 증감 문장을 만든다. 모델은 이 문장의 수치와 표현 형식을 따른다.

    검증 정규식과 같은 표시값(_display_value)·증감률 반올림을 쓰므로 모델이 숫자 형식을 추측하지 않아도 된다.
    """
    cost_label = {"cost_of_sales_ratio": "매출원가율", "selling_expenses_ratio": "판매관리비율"}.get(fact.get("item"))
    if cost_label is not None:
        # 비용 비중은 _COST_PAIR 형식(%p 없이 "X%에서 Y%로 하락/상승")으로만 쓰고, 원가 구성이 맞춰진 근거에만 제공한다.
        if fact.get("status") != "ok" or not fact.get("cost_bridge_reconciled"):
            return None
        prev, curr = _display_value(fact, "previous"), _display_value(fact, "current")
        try:
            old_v, new_v = (Decimal(str(fact[k])).quantize(Decimal("0.01")) for k in ("previous", "current"))
        except (InvalidOperation, ValueError, TypeError, KeyError):
            return None
        if prev is None or curr is None or old_v == new_v:
            return None
        return f"{cost_label}은 {prev}에서 {curr}로 {"하락" if new_v < old_v else "상승"}했습니다."
    label = _SENTENCE_LABELS.get(fact.get("item"))
    if label is None or fact.get("status") != "ok":
        return None
    if fact.get("item") in {"operating_income", "net_income"} and fact.get("change_pct") is None:
        try:
            old, new = Decimal(str(fact["previous"])), Decimal(str(fact["current"]))
            if not old.is_finite() or not new.is_finite():
                return None
            if old >= 0 and new < 0:
                state = "적자 전환"
            elif old < 0 and new >= 0:
                state = "흑자 전환"
            elif old < 0 and new < 0:
                state = "적자 축소" if new > old else "적자 확대" if new < old else "적자 지속"
            else:
                state = "흑자 지속"
        except (InvalidOperation, KeyError, ValueError):
            return None
        prev, curr = _display_value(fact, "previous"), _display_value(fact, "current")
        if state and prev is not None and curr is not None:
            verb = "했습니다." if "전환" in state else "되었습니다."
            return f"{label}은 {prev}에서 {curr}으로 {state}{verb}"
        return None
    margin = fact["item"] in _PERCENT_ITEMS
    try:
        value = Decimal(str(fact.get("delta_pp" if margin else "change_pct")))
    except (InvalidOperation, ValueError, TypeError):
        return None
    prev, curr = _display_value(fact, "previous"), _display_value(fact, "current")
    if not value.is_finite() or value == 0 or prev is None or curr is None:
        return None
    number = abs(value).quantize(Decimal("0.01"))
    if margin:
        word = "상승" if value > 0 else "하락"
        return f"{label}은 {prev}에서 {curr}로 {number}%p {word}했습니다."
    word = "증가" if value > 0 else "감소"
    return f"{label}은 {prev}에서 {curr}으로 {number}% {word}했습니다."


_SUMMARY_FINANCE = re.compile(r"실적|매출|영업이익|순이익|수익성|이익률")
_SUMMARY_CHANGE = re.compile(r"개선|악화|증가|감소|상승|하락|성장|강화|약화|호조|부진")
_UNVERIFIED_EVENT = re.compile(r"계약|설립|공시|체결|발표|인수|배당|수주|소송")


def _mask_summary_years(text: str, years: tuple[int, ...]) -> str:
    """검증된 증감률 문장과 함께 쓰인 두괄식 실적 요약 문장의 비교 연도를 마스킹한다."""
    if not years or _UNVERIFIED_EVENT.search(text):
        return text
    if not (_SUMMARY_FINANCE.search(text) and _SUMMARY_CHANGE.search(text)):
        return text
    spans = []
    pairs = list(_PERIOD.finditer(text))
    for pair in pairs:
        if (int(pair[1]), int(pair[2])) != years:
            raise AppError("chat_numbers", "재무 수치의 항목·단위·기간·증감 방향을 확인하지 못했습니다.")
        spans.extend((pair.span(1), pair.span(2)))
    for year in _YEAR.finditer(text):
        if any(pair.start() <= year.start() < pair.end() for pair in pairs):
            continue
        if int(year[1]) == years[-1]:
            spans.append(year.span(1))
    if not spans:
        return text
    return "".join(
        char
        for index, char in enumerate(text)
        if not (char.isdigit() and any(start <= index < end for start, end in spans))
    )


def mask_verified_comparisons(text, evidence):
    """일치한 표현의 숫자만 검사 사본에서 지운다. 표시 원문은 바꾸지 않는다.

    동일 항목·기간·연결/별도 근거가 하나일 때만 직접 수치를 허용한다.
    복수 비교 기준이나 항목에 연결되지 않은 금액·이익률은 기존 값 자리표시자를 사용한다.
    수치가 다른 항목에 존재한다는 이유로 허용하지 않는다.
    """
    # 비교 연도는 같은 문장의 수치 주장 또는 검증된 수치 문장과 함께 쓰인 두괄식 실적 요약에만 귀속한다.
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    results = [_mask_sentence(part, evidence) for part in parts]
    all_bases = {base for _, bases in results for base in bases}
    if len(all_bases) == 1:
        years = next(iter(all_bases))[0]
        return "\n".join(
            _mask_summary_years(masked, years) if not bases else masked
            for masked, bases in results
        )
    return "\n".join(masked for masked, _ in results)


def _mask_sentence(text, evidence):
    facts = [v for v in evidence.values() if v.get("kind") == "annual_comparison"
             and v.get("status") == "ok"]
    used, spans = [], []

    def reject():
        raise AppError("chat_numbers", "재무 수치의 항목·단위·기간·증감 방향을 확인하지 못했습니다.")

    for match in _TRANSITION.finditer(text):
        candidates = [f for f in facts if f.get("item") == _ITEMS[match["item"]]]
        if len(candidates) != 1:
            reject()
        fact = candidates[0]
        try:
            old, new = Decimal(str(fact["previous"])), Decimal(str(fact["current"]))
            if not old.is_finite() or not new.is_finite():
                reject()
        except (InvalidOperation, KeyError, ValueError):
            reject()
        kind = match.groupdict().get("kind", "전환")
        if kind == "전환":
            expected_state = "적자" if old >= 0 and new < 0 else "흑자" if old < 0 and new >= 0 else None
            state_match = match["state"] == expected_state
        elif match["state"] == "적자" and old < 0 and new < 0:
            if kind == "축소":
                state_match = new > old
            elif kind == "확대":
                state_match = new < old
            elif kind == "지속":
                state_match = new == old
            else:
                state_match = False
        else:
            state_match = False
        if (not state_match
                or not _amount_matches(match["previous"], _display_value(fact, "previous"))
                or not _amount_matches(match["current"], _display_value(fact, "current"))):
            reject()
        used.append((match, fact))
        spans.extend((match.span("previous"), match.span("current")))

    def rate(match, *, has_pairs=True):
        candidates = [f for f in facts if f.get("item") == _ITEMS[match["item"]]]
        if len(candidates) != 1:
            return reject()
        fact = candidates[0]
        margin = fact["item"] in _PERCENT_ITEMS
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
        if has_pairs:
            prev_display = _display_value(fact, "previous")
            curr_display = _display_value(fact, "current")
            if match["prev"] or match["curr_pair"]:
                if fact['item'] in {'cost_of_sales_ratio','selling_expenses_ratio'}:
                    equal=(Decimal(match['prev'].removesuffix('%'))==Decimal(prev_display.removesuffix('%'))
                           and Decimal(match['curr_pair'].removesuffix('%'))==Decimal(curr_display.removesuffix('%')))
                else:
                    equal=_amount_matches(match['prev'], prev_display) and _amount_matches(match['curr_pair'], curr_display)
                if not equal:
                    return reject()
                spans.extend((match.span("prev"), match.span("curr_pair")))
                years = tuple(fact.get("years", []))
                for label, index in (("prev_year", 0), ("curr_year", -1)):
                    if match[label]:
                        if not years or int(match[label]) != years[index]:
                            return reject()
                        spans.append(match.span(label))
            if match["curr_pre"]:
                if match["curr_pre"] != curr_display:
                    return reject()
                spans.append(match.span("curr_pre"))
            if match["curr_post"]:
                if match["curr_post"] != curr_display:
                    return reject()
                spans.append(match.span("curr_post"))
            if match["year_post"]:
                years = tuple(fact.get("years", []))
                if not years or int(match["year_post"]) != years[-1]:
                    return reject()
                spans.append(match.span("year_post"))
        used.append((match, fact))
        spans.append(match.span("number"))

    for match in _COST_PAIR.finditer(text):
        candidates=[f for f in facts if f.get('item')==_ITEMS[match['item']] and f.get('cost_bridge_reconciled')]
        if len(candidates)!=1:
            reject()
        fact=candidates[0]
        old,new=Decimal(fact['previous']).quantize(Decimal('.01')),Decimal(fact['current']).quantize(Decimal('.01'))
        direction=match['direction']
        if (Decimal(match['previous'])!=old or Decimal(match['current'])!=new
                or direction in {'낮아','하락'} and not new<old
                or direction in {'높아','상승'} and not new>old
                or direction in {'유지','같'} and new!=old):
            reject()
        used.append((match,fact))
        spans.extend((match.span('previous'),match.span('current')))
    for match in _COST_STABLE.finditer(text):
        candidates=[f for f in facts if f.get('item')==_ITEMS[match['item']] and f.get('cost_bridge_reconciled')]
        if len(candidates)!=1:
            reject()
        fact=candidates[0]
        if Decimal(fact['previous'])!=Decimal(fact['current']) or Decimal(match['current'])!=Decimal(fact['current']).quantize(Decimal('.01')):
            reject()
        used.append((match,fact))
        spans.append(match.span('current'))
    for match in _MARGIN_PAIR.finditer(text):
        candidates = [f for f in facts if f.get('item') == 'operating_margin']
        if len(candidates) != 1:
            reject()
        fact = candidates[0]
        try:
            old = Decimal(str(fact['previous'])).quantize(Decimal('.01'))
            new = Decimal(str(fact['current'])).quantize(Decimal('.01'))
        except (InvalidOperation, KeyError, ValueError):
            reject()
        direction = match['direction']
        if (Decimal(match['previous']) != old or Decimal(match['current']) != new
                or direction in {'하락', '악화'} and not new < old
                or direction in {'상승', '개선'} and not new > old
                or direction in {'유지'} and new != old):
            reject()
        used.append((match, fact))
        spans.extend((match.span('previous'), match.span('current')))
    for match in _RATE.finditer(text):
        rate(match, has_pairs=True)
    for match in _PAREN_RATE.finditer(text):
        rate(match, has_pairs=False)
    # 단독 금액 문장은 같은 항목의 단일 검증 근거와 금액·연도(당기/전기)가 정확히 같을 때만 허용한다.
    for match in _DELTA.finditer(text):
        candidates = [f for f in facts if f.get("item") == "operating_income"]
        if candidates and candidates[0].get("delta") is not None:
            fact = candidates[0]
            try:
                expected_delta = format_eok(abs(int(fact["delta"])))
            except (ValueError, TypeError):
                continue
            if match["amount"] == expected_delta:
                used.append((match, fact))
                spans.append(match.span("amount"))
                if match["prev"] and match["prev"] == _display_value(fact, "previous"):
                    spans.append(match.span("prev"))
                years = tuple(fact.get("years", []))
                if match["prev_year"] and years and int(match["prev_year"]) == years[0]:
                    spans.append(match.span("prev_year"))
    for match in _AMOUNT.finditer(text):
        candidates = [f for f in facts if f.get("item") == _ITEMS[match["item"]]]
        if len(candidates) != 1:
            reject()
        fact = candidates[0]
        past = match["verb"] in {"이었습니다", "였습니다"}
        if not _amount_matches(match["amount"], _display_value(fact, "previous" if past else "current")):
            reject()
        years = tuple(fact.get("years", []))
        if match["year"]:
            if len(years) != 2 or int(match["year"]) != years[0 if past else 1]:
                reject()
            spans.append(match.span("year"))
        used.append((match, fact))
        spans.append(match.span("amount"))
    # 연도 + 검증된 비교 자리표시자를 함께 쓴 정상 응답도 같은 주장에 묶는다.
    # ID가 가리키는 항목까지 일치해야 하며 다른 문장의 연도를 빌리지 않는다.
    for marker in _COMPARISON_MARKER.finditer(text):
        fact = evidence.get(marker["id"], {})
        if fact.get("kind") != "annual_comparison":
            continue
        if fact.get("status") != "ok" or fact.get("item") != _ITEMS[marker["item"]]:
            reject()
        used.append((marker, fact))
    # 검증된 비교의 기준 연도를 '2025년 (확정) 실적'처럼 실적의 이름표로만 쓴 경우는 허용한다. 계약·설립 같은 다른 사건의 연도는 해당하지 않는다.
    known_years = {int(y) for f in facts if isinstance(f, dict) and f.get("status") == "ok" for y in f.get("years", ())}
    for label in _YEAR_LABEL.finditer(text):
        if int(label[1]) in known_years:
            spans.append(label.span(1))
    # 연도는 실제 대조한 숫자의 공통 기간과 순서가 맞을 때만 인정한다.
    bases = {(tuple(f.get("years", [])), f.get("fs_div"), f.get("stock_code")) for _, f in used}
    if len(bases) == 1:
        years = next(iter(bases))[0]
        pairs = list(_PERIOD.finditer(text))
        for pair in pairs:
            if (int(pair[1]), int(pair[2])) != years:
                reject()
            if any(claim.start() <= pair.start() and pair.end() <= claim.end()
                   or pair.end() <= claim.start()
                   and re.fullmatch(r"\s*(?:에는|에도|에|의|은|는)?\s*", text[pair.end():claim.start()])
                   for claim, _ in used):
                spans.extend((pair.span(1), pair.span(2)))
        for year in _YEAR.finditer(text):
            if any(pair.start() <= year.start() < pair.end() for pair in pairs):
                continue
            # '당기년 매출은 …' 또는 '매출이 … 증가한 당기년에도'만 허용한다.
            # 연도만 일치하는 무관한 공시/설립/계약 문장의 숫자는 남겨 거절한다.
            # 연도와 주장 사이에는 '기준', '대비', '연간' 같은 기간 표현만 올 수 있다.
            linked = any(
                (year.end() <= claim.start() and re.fullmatch(_YEAR_GAP, text[year.end():claim.start()]))
                or (claim.end() <= year.start() and re.fullmatch(r"한\s*", text[claim.end():year.start()]))
                for claim, _ in used)
            gap_text = max((text[year.end():claim.start()] for claim, _ in used
                            if year.end() <= claim.start()), key=len, default="") if linked else ""
            # 당기 연도는 그대로, 전기 연도는 '전기년 대비' 형태의 비교 기준일 때만 인정한다.
            if linked and years and (int(year[1]) == years[-1]
                                     or (int(year[1]) == years[0] and "대비" in gap_text)):
                spans.append(year.span(1))
    masked = "".join(char for index, char in enumerate(text)
                     if not (char.isdigit() and any(start <= index < end for start, end in spans)))
    return masked, bases


def comparison_source_ids(text,evidence):
    """직접 쓴 연간 증감률을 기존 검증기로 대조해 누락된 출처 연결을 복원한다.

    항목당 유일한 현재 근거만 후보로 삼는다. 전체 문장의 기간·기업·모든 수치와
    의미는 호출자의 기존 검사가 다시 확인한다. 원문/근거 값은 수정하지 않는다.
    """
    result=[]
    matches=(*_RATE.finditer(text),*_PAREN_RATE.finditer(text))
    for match in matches:
        item=_ITEMS[match['item']]
        candidates={key:fact for key,fact in evidence.items() if fact.get("kind")=="annual_comparison"
                    and fact.get("status")=="ok" and fact.get("item")==item}
        if len(candidates)!=1:
            continue
        try:
            masked,bases=_mask_sentence(match[0],candidates)
        except AppError:
            continue
        if bases and not re.search(r"\d",masked):
            key=next(iter(candidates))
            if key not in result:
                result.append(key)
    return tuple(result)
