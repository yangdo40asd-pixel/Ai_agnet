"""질문의 분량/이슈 수/형식 계약. 모델·화면·수집에 의존하지 않는다."""
from dataclasses import asdict, dataclass, replace
import re

from src.models import AppError

_COUNTS = {'한':1,'하나':1,'두':2,'둘':2,'세':3,'셋':3,'네':4,'넷':4,'다섯':5}
_NUMBER = r'(?:\d{1,2}|다섯|하나|둘|셋|넷|한|두|세|네)'


def _count(value):
    return int(value) if value.isdigit() else _COUNTS[value]


@dataclass(frozen=True)
class PresentationContract:
    style: str = 'plain'
    max_sentences: int | None = None
    max_lines: int | None = None
    max_issues: int = 3
    per_issue_sentences: int | None = None
    explicit_issues: bool = False
    depth: str = 'normal'

    def payload(self):
        return asdict(self)

    def instructions(self):
        result = ['분량→확인된 독립 사건 수→요청 형식 순서를 지킵니다. 기사 개수로 카드 수를 채우지 않습니다.']
        if self.max_sentences:
            result.append(f'본문은 {self.max_sentences}문장 이내입니다. 제목·영향 해석을 따로 붙이지 않고 blocks는 비웁니다.')
        if self.max_lines:
            result.append(f'줄바꿈으로 나눈 {self.max_lines}줄 이내로 쓰고 각 줄은 한 문장으로 작성합니다. 출처는 별도 영역입니다.')
        if self.per_issue_sentences:
            result.append(f'각 이슈의 본문과 선택적 영향 해석을 합쳐 {self.per_issue_sentences}문장 이내로 씁니다.')
        if self.depth == 'simple':
            result.append('초보자도 이해하기 쉬운 일상적인 비유와 쉬운 한국어로 금융 용어를 풀어 설명합니다. 불필요한 전문 기술 용어나 축약어는 줄입니다.')
        elif self.depth == 'detailed':
            result.append('확보된 재무 수치와 사업 배경, 세부 사업 내용을 종합하여 깊이 있고 상세하게 설명합니다.')
        if self.style=='issues':
            result.append(f'확인된 사건만 최대 {self.max_issues}개 카드로 씁니다. 자료가 적으면 적게 제시하고 이유를 짧게 설명합니다. implication은 필요한 근거가 있을 때만 쓰며 기본값은 null입니다.')
        return result


def parse_presentation(question, *, has_news=False):
    lengths=[]
    per_issue=None
    for match in re.finditer(r'(?<![가-힣0-9])('+_NUMBER+r')\s*(줄|문장)', question):
        value=_count(match[1])
        if not 1<=value<=30:
            continue
        prefix=question[max(0,match.start()-18):match.start()]
        is_per_unit = (
            bool(re.search(r'(?:각각|각|이슈마다|기업마다|회사마다|종목마다|후보마다|항목마다|각\s*(?:이슈|기업|회사|종목|후보|항목)(?:를|는|별로?)?|(?:이슈|기업|회사|종목|후보|항목)별로?)\s*$', prefix))
            or bool(re.match(r'\s*씩', question[match.end():]))
        )
        if is_per_unit:
            per_issue=min(per_issue or value,value)
        else:
            lengths.append((value,match[2]))
    counts=[]
    for pattern in (r'(?:이슈|뉴스|소식|사건)(?:를|는|은)?\s*('+_NUMBER+r')\s*(?:개|가지)',
                    r'('+_NUMBER+r')\s*(?:개|가지)(?:의)?\s*(?:이슈|뉴스|소식|사건)'):
        counts.extend(_count(m[1]) for m in re.finditer(pattern,question))
    max_issues=min(3,min(counts)) if counts else 3
    global_limit=min((n for n,_ in lengths),default=None)
    line_limit=min((n for n,unit in lengths if unit=='줄'),default=None)
    force_plain=bool(re.search(r'카드\s*없이|텍스트|글로',question))
    wants_cards=bool(counts or re.search(r'카드',question)) and not force_plain
    news_request=bool(re.search(r'뉴스|기사|이슈|공시|종합|전체.*분석',question))
    short=bool(re.search(r'간단|짧게|간결',question))
    single_followup=bool(re.search(r'(?:첫\s*번째|두\s*번째|세\s*번째|[123]\s*번째|그|이)\s*(?:이슈|기사|뉴스|소식)',question))
    force_plain=force_plain or (single_followup and not wants_cards)
    style='issues' if has_news and not force_plain and not global_limit and (wants_cards or news_request and not short) else 'plain'
    depth = 'normal'
    if re.search(r"쉽게|쉬운|초보|간단히\s*설명|알기\s*쉽게", question):
        depth = 'simple'
    elif re.search(r"자세히|자세하게|상세히|상세하게|깊이\s*있게|구체적으로", question):
        depth = 'detailed'
    return PresentationContract(style,global_limit,line_limit,max(1,max_issues),per_issue,bool(counts),depth)


def sentences(text):
    """화면 폭에 따른 시각적 줄 수나 소수점은 문장 수로 세지 않는다."""
    return [part.strip() for part in re.split(r'(?<=[.!?。！？])\s+|\n+',text) if part.strip()]


def enforce_presentation(response, contract):
    bodies = [response.intro] if response.intro else []
    bodies.extend(b.text + ('\n' + b.implication if b.implication else '') for b in response.blocks)
    if getattr(response, "company_cards", None):
        bodies.extend(s.text for c in response.company_cards for s in c.sections if s.text)
    text = '\n'.join(bodies)
    if contract.max_sentences and len(sentences(text))>contract.max_sentences:
        raise AppError('chat_length','요청한 문장 수를 초과했습니다.')
    if contract.max_lines and len([line for line in text.splitlines() if line.strip()])>contract.max_lines:
        raise AppError('chat_length','요청한 줄 수를 초과했습니다.')
    if len(response.blocks)>contract.max_issues:
        raise AppError('chat_issues','요청한 이슈 수를 초과했습니다.')
    if contract.per_issue_sentences and any(len(sentences(body))>contract.per_issue_sentences for body in bodies[1:]):
        raise AppError('chat_length','이슈별 문장 수를 초과했습니다.')


def attribute_reported_news(response):
    """보도만 인용하는 답변의 귀속을 보존한다. 사실·수치·심사 결과는 고치지 않는다.

    공식 원문/금융 계산이 섞이면 전역 보도 귀속을 적용하지 않는다.
    표시 문구도 이후 기존 의미 심사를 통과해야 한다.
    """
    if not response.evidence or not all(
        str(item.get("id", "")).startswith("NEWS_") and item.get("id") != "NEWS_STATUS"
        and item.get("scope") in {"headline_only", "article_excerpt"}
        for item in response.evidence
    ):
        return response
    first = sentences(response.intro)[0] if sentences(response.intro) else ""
    if re.search(r'보도|기사|헤드라인|제목|회사(?:는|가).{0,60}(?:설명|발표)',first):
        return response
    intro=re.sub(r'^(?:확인된|제공된|수집된)\s*자료에\s*따르면[,]?\s*',"",response.intro)
    return replace(response,intro="관련 보도에 따르면, " + intro)


def mask_displayed_issue_count(text, count):
    """검증할 카드 수와 같은 도입의 이슈 개수만 숫자 검사에서 제외한다.

    카드 자체의 근거·독립성은 기존 검사에서 별도로 확인한다. 계약/기사 건수,
    카드와 다른 수, 금액·비율에는 적용하지 않는다.
    """
    if count not in {1,2,3}:
        return text
    def matched(match):
        prefix=text[max(text.rfind(".",0,match.start())+1,text.rfind("\n",0,match.start())+1):match.start()]
        if int(match[1])==count and re.search(r'이슈|독립\s*사건',prefix):
            return match[0].replace(match[1],"",1)
        return match[0]
    return re.sub(r'(?<![\d.])([1-3])\s*(?:건|개)(?=입니다|이며|이고|을|를|만|의|뿐|[ .,!?])',matched,text)


_MARGIN_CHANGE=re.compile(r'(?<![\d.])([+-]?\d+(?:\.\d+)?)\s*(?:%p|퍼센트포인트)')


def _single_margin_delta(response):
    from decimal import Decimal,InvalidOperation
    comparisons=[item for item in response.evidence if item.get("kind") in {"annual_comparison","quarterly_comparison"}]
    if len(comparisons)!=1 or comparisons[0].get("item")!="operating_margin" or comparisons[0].get("delta_pp") is None:
        return None
    try:
        value=abs(Decimal(str(comparisons[0]["delta_pp"]))).quantize(Decimal("0.01"))
        return value if value.is_finite() else None
    except (InvalidOperation,ValueError):
        return None  # 원자료의 유효성은 기존 금융 검증기가 판정한다.


def _same_change(number,expected):
    from decimal import Decimal
    return abs(Decimal(number))==expected


def deduplicate_margin_note(response):
    """자리표시자가 펼친 괄호와 모델 본문의 동일 변화가 겹칠 때 괄호만 생략한다.

    본문에 같은 검증 수치가 남는 경우만 처리한다. 새로운 숫자/주장은 만들지 않는다.
    """
    expected=_single_margin_delta(response)
    if expected is None or sum(_same_change(m[1],expected) for m in _MARGIN_CHANGE.finditer(response.intro))<2:
        return response
    pattern=re.compile(r'\(\s*([+-]?\d+(?:\.\d+)?)\s*%p\s*(?:상승|하락)\s*\)')
    removed=False
    def replace_note(match):
        nonlocal removed
        if not removed and _same_change(match[1],expected):
            removed=True
            return ""
        return match[0]
    intro=pattern.sub(replace_note,response.intro)
    if removed:
        intro=re.sub(r'(?<=%)\s+(?=로|으로|이며|이고|입니다|였습니다)',"",intro)
    return replace(response,intro=re.sub(r'\s+([,，])',r'\1',intro).replace("  "," ")) if removed else response


def enforce_single_margin_change(response):
    """단일 이익률 설명의 동일 %p 반복을 검사한다. 다른 지표/전기·당기 %는 제외한다."""
    expected=_single_margin_delta(response)
    if expected is not None and sum(_same_change(m[1],expected) for m in _MARGIN_CHANGE.finditer(response.text))>1:
        raise AppError("chat_repetition","같은 이익률 변화 수치를 반복했습니다.")


def normalize_metric_subject(text,evidence):
    """모델이 '현재 {{PER}}은 값'으로 쓴 주어를 실제 근거 키 이름으로 복원한다."""
    def subject(match):
        key=match[1]
        if key not in evidence or not evidence[key].get("value_text"):
            return match[0]
        return "현재 "+key+match[2]+" "
    text=re.sub(r'현재\s*\{\{(PER|PBR|ROE|EPS|BPS)\}\}\s*([은는])\s+',subject,text)
    def echoed(match):
        # 'PER {{PER}}은 15.20배입니다'처럼 값이 자리표시자와 본문에 두 번 나온 경우, 같은 확인값일 때만 자리표시자를 뺀다.
        key=match[1]
        value=str(evidence.get(key,{}).get("value_text") or "")
        if not value or not text[match.end():].startswith(value):
            return match[0]
        return key+(match[2] or "은")+" "
    return re.sub(r'(PER|PBR|ROE|EPS|BPS)\s*\{\{\1\}\}\s*([은는이가])?\s*(?=\d)',echoed,text)
