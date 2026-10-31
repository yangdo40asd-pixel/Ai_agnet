"""뉴스·공시 근거에 그대로 적힌 숫자를 본문 숫자 검사에서 허용한다.

허용 조건은 두 가지다: (1) 숫자가 아래 분류(기간, 순위·심급, 금액·비율·배수·건수, 연도, 영문+숫자 제품명)에 속하고
(2) 같은 표현이 단위까지 포함해 답변이 인용한 뉴스·공시 근거 원문에 그대로(공백만 무시) 있어야 한다.
단위가 붙은 채로 비교하므로 '2심'과 '3심', '5조원'과 '15조원', '10%'와 '10배'는 서로 대신할 수 없다.
이 검사는 숫자가 원문에 실제로 있는지만 확인한다. 그 숫자가 어느 대상의 것인지는 근거 대조 심사(grounding review)가 맡는다.
구조화 재무 Fact(PRICE, PER 등)는 근거 원문이 아니므로 기존 Fact 검사가 그대로 담당한다.
"""
import re

_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_SCALE = r"[조억만천]"
_LITERAL = re.compile(
    r"(?<![\dA-Za-z])(?<!\d[.,])(?:"
    r"\d{1,3}\s*(?:개월|분기|년)(?:\s*(?:연속|째|만에|간))?"
    r"|\d{1,3}\s*(?:위|심|등|나노|회)"
    rf"|{_NUM}\s*{_SCALE}(?:\s*(?:{_NUM}\s*)?{_SCALE})*\s*(?:원|달러|엔|위안)?"
    rf"|{_NUM}\s*(?:%p|%|퍼센트|배|원|달러|엔|위안|개국|개사|개|건|명|곳|포인트|주(?!식|택))"
    r"|(?:19|20)\d{2}(?:\s*년)?"
    r"|[A-Za-z]{1,6}-?\d{1,3}[A-Za-z]?"
    r")(?![\dA-Za-z])(?![.,]\d)"
)


# 한글 제품명 뒤에 붙은 모델 번호(예: 갤럭시 Z 폴드8, 아이폰16)도 원문에 그대로 있을 때만 허용한다.
_HANGUL_PRODUCT = re.compile(r"(?<![\dA-Za-z])[가-힣]{1,4}\d{1,3}(?![\dA-Za-z])(?![.,]\d)(?!\s*(?:%|퍼센트|배|원|달러|개|건|명|곳|위|등|심|년|개월|분기|조|억|만|천|주(?!식|택)))")

# 산업 이름·동일 업종 기업 수는 금융 금액이 아니다. 아래도 인용 원문에
# 동일한 단어와 숫자가 실제 존재해야 하며, 다른 업종/건수로 대체하지 않는다.
_INDUSTRY_LITERAL = re.compile(r"(?<![\dA-Za-z])(?:[1-9]차전지|[가-힣]{2,8}\s*\d{1,2}사|\d{1,2}족\s*보행\s*로봇)(?![\dA-Za-z])")

# 공정/검사 제품명. 금융 비율·금액과 구별하며 인용한 원문에 같은 토큰이 있어야 한다.
_TECH_LITERAL = re.compile(r"(?<![\dA-Za-z])(?:\d{1,2}(?:\.\d)?D|\d{1,2}-SIDE)(?![\dA-Za-z])")


_ISO_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def mask_data_basis_terms(text: str, evidence: dict) -> str:
    """재무 근거 자체의 산출 기준(기간 '12개월', 기준일)을 말하는 숫자만 검사 사본에서 지운다.

    PER 산출식·EPS 기간 필드(formula/period/reason)에 실제로 적힌 '12개월'과 기준일(YYYY-MM-DD)만 허용하며,
    값(금액·배수)은 건드리지 않는다.
    """
    basis = " ".join(str(item.get(field) or "") for item in evidence.values() if not item.get("url")
                     for field in ("formula", "period", "reason", "as_of"))
    if not basis:
        return text
    forms = [re.escape(m) for m in set(re.findall(r"\d{1,3}개월", basis))]
    for y, mo, d in _ISO_DATE.findall(basis):
        m = int(mo)
        forms.append(rf"{y}년\s*{m}월(?:\s*(?:{int(d)}일|말))?")
        forms.append(rf"{y}-{mo}-{d}")
    if not forms:
        return text
    pattern = re.compile(r"(?<![\d.,])(?:" + "|".join(forms) + r")(?![\d])")
    return pattern.sub(lambda m: re.sub(r"\d", "", m.group(0)), text)


_RELATIVE_YEAR = re.compile(r"(올해|금년|내년|작년|지난해)(\s*\(\s*|\s*인\s*|\s+|)(20\d{2})(\s*년)")
_RELATIVE_YEAR_REVERSE = re.compile(r"(?<![\d,.])(20\d{2})(\s*년)(\s*)(올해|금년|내년|작년|지난해)")
_RELATIVE_OFFSET = {"올해": 0, "금년": 0, "내년": 1, "작년": -1, "지난해": -1}


def mask_relative_years(text: str, today=None) -> str:
    """'올해(2026년)'처럼 상대 연도 표현에 오늘 날짜로 정해지는 연도를 병기한 경우만 검사 사본에서 지운다."""
    import datetime
    year = (today or datetime.date.today()).year
    introduced = set()
    def repl(match):
        if int(match.group(3)) == year + _RELATIVE_OFFSET[match.group(1)]:
            introduced.add(match.group(3))
            return match.group(1) + match.group(2) + match.group(4)
        return match.group(0)
    masked = _RELATIVE_YEAR.sub(repl, text)
    def repl_reverse(match):
        if int(match.group(1)) == year + _RELATIVE_OFFSET[match.group(4)]:
            introduced.add(match.group(1))
            return match.group(2) + match.group(3) + match.group(4)
        return match.group(0)
    masked = _RELATIVE_YEAR_REVERSE.sub(repl_reverse, masked)
    # 상대 표현으로 이미 밝힌 같은 연도의 이후 단순 언급('2027년의 목표')은 달력 연도 표기이므로 함께 지운다.
    for label in introduced:
        masked = re.sub(r"(?<![\d,.])" + label + r"(?=\s*년)", "", masked)
    return masked


_RESULT_WORD = re.compile(r"실적|매출|영업이익|순이익|이익률|수익성|재무")
_EVENT_WORD = re.compile(r"계약|체결|수주|인수|합병|투자|발표|공시|착공|출시|양산|계획|목표|전망|예정|가이던스|컨센서스|예상")


def mask_evidence_years(text: str, evidence: dict, original: str = "") -> str:
    """연간 비교 및 재무 근거의 연도를 말하는 같은 문장 안에서, 그 근거가 실제로 가리키는 연도('YYYY년')만 검사 사본에서 지운다.

    다른 문장이나 다른 사건에 붙은 연도, 근거에 없는 연도는 그대로 남아 검사된다. 금액·증감률 값은 지우지 않는다.
    """
    annual_items = [item for item in evidence.values() if item.get("kind") in {"annual_comparison", "annual_financial"}]
    if not annual_items:
        return text
    def mask_sentence(sentence: str, source: str) -> str:
        for item in annual_items:
            for year in item.get("years") or item.get("years_available") or []:
                raw_pct = item.get("change_pct") if item.get("change_pct") is not None else item.get("delta_pp")
                if raw_pct is not None:
                    try:
                        rate = f"{abs(float(raw_pct)):.2f}"
                        if re.search(r"(?<![\d.,])" + re.escape(rate) + r"\s*%", source):
                            sentence = re.sub(r"(?<![\d,.])" + str(year) + r"(?=\s*년)(?![\d])", "", sentence)
                    except (TypeError, ValueError):
                        pass
                elif item.get("kind") == "annual_financial" or (item.get("kind") == "annual_comparison" and item.get("change_state") in {"적자 축소", "적자 지속", "적자 확대", "흑자 전환", "적자 전환"}):
                    if _RESULT_WORD.search(source) and not _EVENT_WORD.search(source):
                        sentence = re.sub(r"(?<![\d,.])" + str(year) + r"(?=\s*년)(?![\d])", "", sentence)
        return sentence
    splitter = r"(?<=[.!?])\s+|\n"
    parts = re.split(splitter, text)
    sources = re.split(splitter, original or text)
    if len(parts) != len(sources):
        return text
    all_years = sorted({str(y) for item in annual_items for y in (item.get("years") or [])})
    def mask_result_label(sentence: str) -> str:
        # 비교 연도를 실적 결과의 기간 이름으로만 쓴 문장('2025년 확정 실적 기준 …')은 사건·계획·전망 표현이 없을 때만 허용한다.
        if _RESULT_WORD.search(sentence) and not _EVENT_WORD.search(sentence) and "%" not in sentence:
            for year in all_years:
                sentence = re.sub(r"(?<![\d,.])" + year + r"(?=\s*년)(?![\d])", "", sentence)
        return sentence
    return "\n".join(mask_result_label(mask_sentence(part, source)) for part, source in zip(parts, sources))


_UP = re.compile(r"상승|올랐|오른|올라|증가|늘었|높아")
_DOWN = re.compile(r"하락|내렸|내린|떨어|감소|줄었|낮아")


def mask_history_facts(text: str, evidence: dict) -> str:
    """인용한 시세 구간(HISTORY) 근거의 시작·종료일, 시작·종료 종가, 구간 변화율을 답변이 그대로 말한 경우만 검사 사본에서 지운다.

    값은 근거의 수치와 표기까지 같아야 하고, 변화율은 근거의 부호와 같은 방향의 표현(상승/하락)이 뒤따를 때만 인정한다.
    """
    item = evidence.get("HISTORY")
    if not isinstance(item, dict) or not all(k in item for k in ("first_close", "last_close", "change_pct", "period")):
        return text
    spans = []
    def add(pattern, ok=lambda m: True):
        for m in re.finditer(pattern, text):
            if ok(m):
                spans.append((m.start(), m.end()))
    for iso in re.findall(r"20\d{2}-\d{2}-\d{2}", str(item["period"])):
        y, mo, d = iso.split("-")
        add(rf"(?<![\d.,]){y}\s*년\s*{int(mo)}\s*월\s*{int(d)}\s*일(?!\d)")
        add(rf"(?<![\d.,]){iso}(?!\d)")
    for key in ("first_close", "last_close"):
        v = float(item[key])
        forms = {f"{v:,.2f}", f"{v:,.0f}"} | ({f"{v / 10000:g}만"} if v % 10000 == 0 else set())
        for form in forms:
            add(r"(?<![\d.,])" + re.escape(form) + r"\s*원(?![\d])")
    change = float(item["change_pct"])
    forms = {f"{abs(change):.2f}", f"{abs(change):.1f}"}
    wanted = _UP if change >= 0 else _DOWN
    for form in forms:
        add(r"(?<![\d.,])" + re.escape(form) + r"\s*%(?![\d])",
            lambda m: bool(wanted.search(text[m.end():m.end() + 14])) )
    return "".join(ch for i, ch in enumerate(text) if not (ch.isdigit() and any(a <= i < b for a, b in spans)))


def mask_question_quarters(text: str, question: str, evidence: dict | None = None) -> str:
    """사용자가 질문에 직접 쓴 기간(N분기, YYYY년) 및 질문 속 숫자 표현, 자료 확인 경계 연도를 검사 사본에서 지운다."""
    if not question:
        return text
    asked_quarters = set(re.findall(r"(?<![\d.])([1-4])\s*분기", question))
    if asked_quarters:
        text = re.sub(r"(?<![\d.,])([1-4])(?=\s*분기)", lambda m: "" if m.group(1) in asked_quarters else m.group(0), text)
    question_terms = re.findall(r"(?<![\dA-Za-z])(?:\d+(?:,\d{3})*(?:\.\d+)?\s*(?:조\s*원|조원|조|억원|억|만\s*원|만원|원|%|배|년|분기)?)(?![\dA-Za-z])", question)
    for term in sorted(set(question_terms), key=len, reverse=True):
        term = term.strip()
        if term and re.search(r"\d", term):
            text = re.sub(r"(?<![\dA-Za-z])" + re.escape(term) + r"(?![\dA-Za-z])", "", text)
    if evidence:
        confirmed = {str(y) for item in evidence.values() if isinstance(item, dict)
                     for y in (item.get("years") or item.get("years_available") or ([item.get("year")] if item.get("year") else []))}
        if confirmed:
            splitter = r"(?<=[.!?。！？])\s+|\n+"
            parts = re.split(splitter, text)
            new_parts = []
            for part in parts:
                if re.search(r"확정|확인|수집|공시|발표|최신|자료|실적", part) and re.search(r"까지|기준|현재", part):
                    for y in confirmed:
                        part = re.sub(r"(?<![\d,.])" + y + r"(?=\s*년)(?![\d])", "", part)
                new_parts.append(part)
            text = "\n".join(new_parts)
    return text


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def mask_literal_source_numbers(text: str, evidence: dict) -> str:
    """검사 사본에서 근거 원문에 그대로 있는 허용 분류의 숫자만 지운다. 사용자에게 보이는 원문은 바꾸지 않는다."""
    # 모델에게 실제 제공한 제목·사업 원문·기사 발췌만 대조한다. 인용 범위 밖 숫자는 허용하지 않는다.
    sources = [" ".join(str(part).split()) for item in evidence.values()
               if item.get("kind") not in {"annual_comparison", "quarterly_comparison", "annual_financial", "cost_structure_comparison"}
               and (item.get("url") or item.get("scope") in {"company_profile", "official_business"} or item.get("kind") in {"company_profile", "company_business_section"})
               for part in (item.get("text"), item.get("excerpt") if item.get("excerpt_scope") == "article_excerpt" else None) if part]
    if not sources:
        return text
    spans = []
    for match in [*_LITERAL.finditer(text), *_HANGUL_PRODUCT.finditer(text), *_INDUSTRY_LITERAL.finditer(text), *_TECH_LITERAL.finditer(text)]:
        token = _compact(match.group(0))
        # 기사에 '200억'으로 적힌 금액을 답변이 '200억 원'으로 통화만 붙여 쓴 경우는 같은 값이다.
        forms = [token] + ([token[:-1]] if re.search(r"[조억만천]원$", token) else [])
        # '17년 연속'처럼 접미사가 붙은 경우, 원문의 '17년'도 동일한 기간 숫자 근거다.
        stem = re.sub(r"(?:연속|째|만에|간)$", "", token)
        if stem != token:
            forms.append(stem)
        # 기사에 '2026 한국품질…'처럼 연도만 적혀 있어도 본문의 '2026년'은 같은 연도 표기다.
        if re.fullmatch(r"(?:19|20)\d{2}년", token):
            forms.append(token[:-1])
        patterns = [re.compile(r"(?<![\dA-Za-z])(?<!\d[.,])" + r"\s*".join(re.escape(ch) for ch in form) + r"(?![\dA-Za-z])(?![.,]\d)" + (r"(?!\s*[\d조억만천])" if form != token else ""))
                    for form in forms]
        if any(pattern.search(source) for pattern in patterns for source in sources):
            spans.append((match.start(), match.end()))
    return "".join(ch for i, ch in enumerate(text) if not (ch.isdigit() and any(a <= i < b for a, b in spans)))
