"""원문 수치의 후보 추출과 등록 심사. LLM·화면·출처 수집에 의존하지 않는다.

지원하는 명시적 항목만 등록한다. 해석이 불명확한 수치는 원문과 함께 보류한다.
"""
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import re

from src.models import StructuredFact

NUMBER = r'[+-]?\d[\d,]*(?:\.\d+)?'
QUANTITY = re.compile(r'(?<![\d.,])(?P<num>'+NUMBER+r'(?:\s*[조억만]\s*(?:'+NUMBER+r')?)*)\s*'
                      r'(?P<unit>퍼센트포인트|%p|억원|조원|만원|원|%|배|주|년|분기)(?![A-Za-z])')
DATES = re.compile(r'(?<!\d)(?:(?P<year>20\d{2})년\s*)?(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일')
PERIOD = re.compile(r'(20\d{2})년\s*(?:(1|2|3|4)분기|사업연도|연간)?')
LABELS = (
    ('operating_margin', r'영업이익률'), ('foreign_ratio', r'(?:외국인|외인)(?:\s*지분율|\s*보유\s*비율|\s*비중)?'),
    ('foreign_net_buy', r'(?:외국인|외인)\s*순매수'), ('foreign_net_sell', r'(?:외국인|외인)\s*순매도'),
    ('holding_ratio', r'지분율|보유\s*비율|보유\s*지분|지분'), ('operating_income', r'영업이익(?!률)'),
    ('net_income', r'당기순이익|순이익'), ('revenue', r'매출액|매출(?!원가)'),
    ('cost_of_sales', r'매출원가'), ('selling_expenses', r'판매관리비|판관비'),
    ('fine_amount', r'과징금'), ('investment_amount', r'투자(?:금액|금|액)?'),
    ('contract_amount', r'계약(?:\s*해지)?\s*(?:금액|규모)|해지\s*금액'),
    ('price', r'주가|종가|현재가'), ('per', r'PER'), ('pbr', r'PBR'),
    ('roe', r'ROE'), ('eps', r'EPS'), ('bps', r'BPS'), ('volume', r'거래량'),
)
UP = r'상승|증가|급등|올라|올랐|늘었|높아'
DOWN = r'하락|감소|급락|내려|내렸|줄었|낮아'


def normalize_quantity(raw, unit):
    compact = re.sub(r'\s+', '', raw)
    if len(compact) > 80:
        raise ValueError('quantity_length')
    sign = -1 if compact.startswith('-') else 1
    compact = compact.lstrip('+-')
    total = Decimal(0)
    previous = Decimal('1e30')
    suffix_scale = {'억원': Decimal('1e8'), '조원': Decimal('1e12'), '만원': Decimal('1e4')}
    chunks = list(re.finditer(r'(\d[\d,]*(?:\.\d+)?)([조억만]?)', compact))
    if not chunks or ''.join(m[0] for m in chunks) != compact:
        raise ValueError('quantity_format')
    for chunk in chunks:
        number = chunk[1]
        if ',' in number and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', number):
            raise ValueError('comma_format')
        scale = {'조': Decimal('1e12'), '억': Decimal('1e8'), '만': Decimal('1e4'), '': Decimal(1)}[chunk[2]]
        if scale >= previous:
            raise ValueError('scale_order')
        previous = scale
        total += Decimal(number.replace(',', ''))*scale
    total *= suffix_scale.get(unit, Decimal(1))*sign
    if not total.is_finite() or abs(total) > Decimal('1e24'):
        raise ValueError('quantity_range')
    return total, '원' if unit in {'원','억원','조원','만원'} else '%p' if unit == '퍼센트포인트' else unit


def quantity_tokens(text):
    """인용 가능한 수량 위치와 정규값. 날짜의 월/일을 독립 수량으로 분해하지 않는다."""
    tokens = []
    date_spans = []
    for match in DATES.finditer(text):
        try:
            date(int(match['year'] or 2000), int(match['month']), int(match['day']))
            value = Decimal((match['year'] or '')+match['month'].zfill(2)+match['day'].zfill(2))
            tokens.append((match.start(), match.end(), value, 'date', match[0]))
            date_spans.append(match.span())
        except ValueError:
            continue
    for match in QUANTITY.finditer(text):
        if any(a <= match.start() < b for a,b in date_spans):
            continue
        try:
            value, unit = normalize_quantity(match['num'], match['unit'])
            tokens.append((match.start(), match.end(), value, unit, match[0]))
        except (ValueError, InvalidOperation):
            continue
    return sorted(tokens)


def clause_bounds(text, start, end):
    boundaries = list(re.finditer(r'\n|[;；!?。！？]|\.(?=\s|$)', text))
    left = max((m.end() for m in boundaries if m.end() <= start), default=0)
    right = min((m.start() for m in boundaries if m.start() >= end), default=len(text))
    return left, right


def context_fields(text, start, end, unit, stock_name, known_names=()):
    left, right = clause_bounds(text, start, end)
    before, after = text[left:start], text[end:right]
    labels = [(m.end(), len(m[0]), item) for item, pattern in LABELS for m in re.finditer(pattern, before, re.I)]
    item = max(labels, default=(0,0,'unknown'))[2]
    # 한국어 기사는 항목을 금액 뒤에도 쓴다. 바로 붙은 투자 동사만 읽고
    # 투자자/투자수익 같은 다른 항목이나 이미 명시된 매출 항목을 덮지 않는다.
    if unit == '원' and item == 'unknown' and re.match(
            r'^\s*(?:을|를|의)?\s*투자(?:\s|$|할|하|했|합|한|금액|금|액)', after):
        item = 'investment_amount'
    if unit == '년' and re.match(r'\s*연속', after):
        item = 'streak'  # '18년 연속 1위'는 재무 기간이 아니라 연속 횟수다.
    elif unit in {'date','년','분기'}:
        item = 'target_date' if re.search(r'예정|목표', before[-15:]+after[:18]) else 'event_date' if unit == 'date' else 'financial_period'
    elif unit in {'%','%p'} and item == 'price':
        item = 'price_change'
    elif unit == '원' and item == 'unknown' and re.match(r'(?:으로|에)?\s*'+NUMBER+r'\s*%\s*(?:'+UP+'|'+DOWN+')', after):
        item = 'price'
    elif unit == '%' and item == 'operating_income':
        item = 'operating_income_change'
    elif unit == '%' and item == 'revenue':
        item = 'revenue_change'
    elif unit == '%' and item == 'unknown' and re.search(r'원(?:으로|에)?\s*$', before[-35:]) and re.search(UP+'|'+DOWN, after[:10]):
        item = 'price_change'
    names = set(known_names) | {stock_name}
    names.update(m[0] for m in re.finditer(r'[가-힣A-Za-z0-9]+(?:전자|물산|회사|메모리|반도체|장비|홀딩스|증권)', before))
    # 삼성전자우 등 긴 별개 명칭의 일부를 현재 회사 명칭으로 인정하지 않는다.
    suffix = r'(?=$|[^가-힣A-Za-z0-9]|(?:은|는|이|가|의|와|과|에서|에|를|을)(?=$|[^가-힣A-Za-z0-9]))'
    mentions = [(m.start(), name) for name in names if name for m in re.finditer(re.escape(name)+suffix, before)]
    # 겹치는 공식 이름의 긴 쪽을 우선한다. 타사 수치를 현재 종목으로 승격하지 않는다.
    target = max(mentions, key=lambda v:(v[0]+len(v[1]),len(v[1])), default=(0,''))[1]
    direction_text = after[:10]
    if re.search(UP, direction_text):
        direction = 'up'
    elif re.search(DOWN, direction_text):
        direction = 'down'
    elif re.search(r'상승률|증가율', before[-10:]):
        direction = 'up'
    elif re.search(r'하락률|감소율', before[-10:]):
        direction = 'down'
    else:
        direction = 'value'
    if item == 'price' and re.match(r'(?:으로|에)?\s*'+NUMBER+r'\s*%', after):
        direction = 'value'
    nearby = before[-60:]+after[:25]
    qualifier = 'provisional' if '잠정' in before else 'planned' if item == 'target_date' else 'reported'
    periods = list(PERIOD.finditer(before))
    period = periods[-1][0].strip() if periods and item != 'streak' else None
    validity = 'historical' if re.search(r'최초\s*공시|정정\s*전|과거\s*값|이전\s*공시', before[-50:]) and not re.search(r'정정\s*(?:후|공시)', before[-16:]) else 'current'
    ownership = 'aggregate' if re.search(r'특수관계인|합산|합계', nearby) else 'unknown'
    reason = ''
    if not target or target != stock_name:
        reason = 'target_not_explicit'
    elif item == 'unknown':
        reason = 'item_not_explicit'
    elif item in {'holding_ratio','foreign_ratio'} and len({n for _,n in mentions if n in set(known_names) | {stock_name}}) > 1:
        reason = 'ownership_roles_ambiguous'
    elif item in {'foreign_ratio','holding_ratio'} and unit != '%':
        reason = 'unit_item_mismatch'
    elif item in {'price','investment_amount','contract_amount','fine_amount','revenue','operating_income','net_income','cost_of_sales','selling_expenses','foreign_net_buy','foreign_net_sell'} and unit != '원':
        reason = 'unit_item_mismatch'
    return dict(item=item,target=target,direction=direction,qualifier=qualifier,financial_period=period,
                validity=validity,ownership_basis=ownership), reason


def extract_candidates(text, evidence_id, stock_name, *, scope='headline_only', published_at=None, known_names=()):
    result=[]
    digest=hashlib.sha256(text.encode()).hexdigest()
    # 원문은 결과에 보존하고 해석은 앞 6,000자로 제한한다. 위치는 원문과 같고 해시는 전체 원문이다.
    text=text[:6000]
    for index,(start,end,value,unit,raw) in enumerate(quantity_tokens(text),1):
        fields, reason=context_fields(text,start,end,unit,stock_name,known_names)
        if value < 0 and unit in {'%','%p'} and fields['direction'] in {'up','down'}:
            if fields['direction']=='up':
                reason='sign_direction_conflict'
            else:
                value=abs(value)  # -4.46% 하락과 4.46% 하락은 같은 변화 방향이다.
        prefix=evidence_id+('_EX' if scope=='article_excerpt' else '')
        result.append(StructuredFact(prefix+'_F'+str(index),evidence_id,fields.pop('item'),fields.pop('target'),
            value,unit,fields.pop('direction'),scope,raw,(start,end),digest,
            article_published_at=published_at, event_occurred_at=raw if unit=='date' and not reason and fields['qualifier']!='planned' else None,
            reason=reason,**fields))
    return tuple(result)


def register_fact(candidate, text, stock_name, *, scope, published_at=None, known_names=()):
    """후보의 자기신고를 신뢰하지 않고 고정 원문과 위치·수치·의미 연결을 다시 대조한다."""
    expected = {f.fact_id:f for f in extract_candidates(text,candidate.evidence_id,stock_name,
                scope=scope,published_at=published_at,known_names=known_names)}.get(candidate.fact_id)
    if (not isinstance(candidate.value,Decimal) or expected is None or candidate != expected
            or scope not in {'headline_only','article_excerpt','official_disclosure','financial_statement'}):
        return replace(candidate,status='rejected',reason='raw_fact_mismatch')
    return replace(candidate,status='deferred' if expected.reason else 'verified')


def source_facts(text,evidence_id,stock_name,*,scope='headline_only',published_at=None,known_names=()):
    candidates=extract_candidates(text,evidence_id,stock_name,scope=scope,published_at=published_at,known_names=known_names)
    # 이 경로는 LLM 후보를 받지 않는 결정적 추출이다. 외부 후보는 register_fact로 원문 재대조한다.
    return tuple(replace(c,status='deferred' if c.reason else 'verified') for c in candidates)


def fact_payload(fact):
    value=asdict(fact)
    value['value']=str(fact.value)
    return value


def contract_scale_fact(contract, annual_revenue):
    """검증된 입력의 규모 비교만 계산한다. 매출 손실 추정이나 정정 관계 판정은 하지 않는다."""
    if (contract.status!='verified' or annual_revenue.status!='verified'
            or contract.validity!='current' or annual_revenue.validity!='current'
            or contract.target!=annual_revenue.target or contract.unit!='원' or annual_revenue.unit!='원'
            or contract.item!='contract_amount' or annual_revenue.item!='revenue'
            or contract.scope not in {'official_disclosure','financial_statement'}
            or annual_revenue.scope not in {'official_disclosure','financial_statement'}
            or contract.value<0 or annual_revenue.value<=0
            or not re.fullmatch(r'20\d{2}년(?:\s*(?:사업연도|연간))?', annual_revenue.financial_period or '')):
        raise ValueError('incompatible_contract_scale_inputs')
    raw=f'{contract.fact_id} / {annual_revenue.fact_id} * 100'
    digest=hashlib.sha256((contract.source_hash+annual_revenue.source_hash+raw).encode()).hexdigest()
    return StructuredFact('CALC_'+digest[:16],contract.evidence_id,'contract_scale_ratio',contract.target,
        contract.value/annual_revenue.value*Decimal(100),'%','value','calculated',raw,(0,0),digest,
        financial_period=annual_revenue.financial_period,status='verified',qualifier='scale_comparison',
        input_fact_ids=(contract.fact_id,annual_revenue.fact_id),formula=raw)
