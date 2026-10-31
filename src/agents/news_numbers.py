"""검증된 비정형 Fact와 답변의 수치/항목/대상/기간을 대조한다. 표시 문장은 바꾸지 않는다."""
from datetime import date
from decimal import Decimal
import re

from src.data.text_facts import quantity_tokens, context_fields, clause_bounds
from src.models import AppError


def _legacy_metric(item, value, unit, evidence):
    key={'price':'PRICE','per':'PER','pbr':'PBR','roe':'ROE','eps':'EPS','bps':'BPS'}.get(item)
    fact=evidence.get(key,{}) if key else {}
    return (fact.get('status')=='ok' and fact.get('value') is not None
            and Decimal(str(fact['value'])).quantize(Decimal('.01')) == value
            and unit=={'PRICE':'원','PER':'배','PBR':'배','ROE':'%','EPS':'원','BPS':'원'}.get(key))


def mask_verified_news(text,evidence):
    facts=[{**fact, '_document_only': parent.get('validity')=='document_only'}
           for parent in evidence.values() for fact in parent.get('structured_facts',())
           if fact.get('status')=='verified']
    if not facts:
        return text
    target_names={fact['target'] for fact in facts}
    stock_name=next(iter(target_names)) if len(target_names)==1 else ''
    if not stock_name:
        raise AppError('chat_numbers','비정형 수치의 대상 기업이 혼합되어 있습니다.')
    spans=[]
    for start,end,value,unit,raw in quantity_tokens(text):
        fields,_=context_fields(text,start,end,unit,stock_name,tuple(target_names))
        if value < 0 and unit in {'%','%p'} and fields['direction'] in {'up','down'}:
            if fields['direction']=='up':
                raise AppError('chat_numbers','음수 변화율과 상승 방향이 충돌합니다.')
            value=abs(value)
        if _legacy_metric(fields['item'],value,unit,evidence):
            continue
        candidates=[f for f in facts if Decimal(f['value'])==value and f['unit']==unit]
        if not candidates:
            continue  # 기존 재무/CMP 검사는 이후에도 그대로 적용한다.
        left,right=clause_bounds(text,start,end)
        sentence=text[left:right]
        if fields['item']=='unknown' and re.search(r'최초\s*공시|정정\s*(?:전|후|공시)',sentence):
            items={f['item'] for f in candidates}
            if len(items)==1:
                fields['item']=next(iter(items))
        matching=[]
        for fact in candidates:
            if fields['item']!=fact['item']:
                continue
            if fields['target'] and fields['target']!=fact['target']:
                continue
            if fields['direction']!='value' and fields['direction']!=fact['direction']:
                continue
            if fact.get('direction') in {'up','down'} and fields['direction']!=fact['direction']:
                continue
            if fields['financial_period'] and fields['financial_period']!=fact.get('financial_period'):
                # 기사가 '3분기'처럼 연도를 생략한 경우, 답변이 붙인 연도가 오늘 연도(최신 기사 기준)와 같으면 같은 분기로 본다.
                year_only = re.fullmatch(r'\s*(20\d{2})\s*년?\s*', str(fields['financial_period']))
                if not (unit=='분기' and not fact.get('financial_period') and year_only
                        and int(year_only.group(1))==date.today().year):
                    continue
            if fields['validity']!=fact.get('validity','current'):
                continue
            if fact.get('qualifier')=='provisional' and '잠정' not in sentence:
                continue
            if fact.get('qualifier')=='provisional' and re.search(r'확정',sentence) and not re.search(r'확정.{0,8}(?:아니|아닙|전|예정|발표)',sentence):
                continue
            if fact.get('ownership_basis')=='aggregate' and not re.search(r'합산|특수관계인|합계',sentence):
                continue
            if fact.get('qualifier')=='planned' and not re.search(r'목표|예정|계획',sentence):
                continue
            if fact.get('scope') in {'headline_only','article_excerpt'} and re.search(r'공시(?:에서|로|를|상|된)|공식.{0,8}확인',sentence):
                continue
            if fact['_document_only'] and (not re.search(r'공시|문서|기재',sentence)
                    or re.search(r'현재|최신|유효|정정\s*후',sentence)):
                continue  # 공시 원문 수집은 전체 정정 이력의 유효성 확인을 뜻하지 않는다.
            matching.append(fact)
        if not matching:
            raise AppError('chat_numbers','뉴스·공시 수치의 항목·기업·기간·방향 또는 확인 범위가 다릅니다.')
        spans.append((start,end))
    # 검사 사본에서 승인된 수치의 숫자만 지운다. 사용자에게 보이는 원문은 보존한다.
    return ''.join(ch for i,ch in enumerate(text) if not (ch.isdigit() and any(a<=i<b for a,b in spans)))
