"""검증된 비교 계산을 질문에 맞춰 설명한다. 단일 종목 LLM 검증기를 우회해 합치지 않는다.

비교 결론은 Decimal 관계로만 결정한다. LLM의 새 사업 원인/전망 생성은 이 경로에 없다.
"""
from decimal import Decimal
import re

from src.formatting import format_eok
from src.models import ChatResponse
from src.agents.presentation import parse_presentation

LABELS={'revenue':'매출','operating_income':'영업이익','operating_margin':'영업이익률'}


def requested_items(question):
    items=[]
    if '매출' in question: items.append('revenue')
    if re.search(r'영업이익(?!률)',question): items.append('operating_income')
    if '이익률' in question or '마진' in question: items.append('operating_margin')
    return tuple(items or LABELS)


def _number(value):
    return f'{Decimal(value):,.2f}'


def _money(value):
    number=Decimal(value)
    return f'{number/Decimal("1e12"):,.2f}조 원' if abs(number)>=Decimal('1e12') else format_eok(number)


def _metric_evidence(snapshot, metric, label):
    return {'id':metric.evidence_id,'text':f'{metric.name} · {label}: {metric.value_text}',
            'stock_code':metric.code,'stock_name':metric.name,'source':'OpenDART',
            'source_result_id':metric.source_id,'comparison_id':snapshot.comparison_id,
            'period':f'{snapshot.year-1}년 → {snapshot.year}년 연간','fs_div':snapshot.fs_div,
            'currency':'KRW','kind':'company_comparison','item':metric.item,'url':metric.source_url,
            'previous':metric.previous,'current':metric.current,'change_pct':metric.change_pct,
            'delta_pp':metric.delta_pp,'answer_origin':'verified_comparison',
            'retrieved_at':next(c.retrieved_at.isoformat() for c in snapshot.companies if c.stock.code==metric.code)}


def comparison_answer(snapshot,question):
    if snapshot.reason: return ChatResponse(snapshot.reason,[])
    if len(snapshot.companies) > 2:
        return _group_answer(snapshot, question)
    evidence=[]; sections=[]; leads=[]; short_values=[]
    lookup={(m.code,m.item):m for m in snapshot.metrics}
    left,right=snapshot.companies
    for item in requested_items(question):
        a,b=(lookup.get((c.stock.code,item)) for c in (left,right))
        label=LABELS[item]
        if a is None or b is None:
            sections.append(f'{label}은 두 기업의 같은 기준 수치가 모두 확인되지 않아 비교에서 제외했습니다.')
            continue
        pair=(a,b)
        for m in pair:
            evidence.append(_metric_evidence(snapshot,m,label))
        if item=='operating_margin':
            av,bv=Decimal(a.current),Decimal(b.current)
            if av==bv:
                lead=f'당기 영업이익률은 두 기업이 {_number(av)}%로 같습니다.'
            else:
                high,low=(a,b) if av>bv else (b,a)
                lead=f'{high.name}의 당기 영업이익률이 {low.name}보다 {_number(abs(av-bv))}%p 높습니다.'
            detail=' '.join(f'{m.name}는 영업이익률이 {_number(m.previous)}%에서 {_number(m.current)}%로 바뀌었습니다.' for m in pair)
            detail+=' 매출에서 영업이익으로 남기는 비중을 비교한 결과입니다.'
        else:
            if a.change_pct is not None and b.change_pct is not None:
                av,bv=Decimal(a.change_pct),Decimal(b.change_pct)
                if av==bv: lead=f'{label} 증감률은 두 기업이 {_number(av)}%로 같습니다.'
                else:
                    high,low=(a,b) if av>bv else (b,a)
                    lead=f'{high.name}의 {label} 증감률이 {low.name}보다 {_number(abs(av-bv))}%p 높습니다.'
                detail=' '.join(f'{m.name}는 {label}이 {_money(m.previous)}에서 {_money(m.current)}으로 '+
                    (f'{_number(abs(Decimal(m.change_pct)))}% '+('증가했습니다.' if Decimal(m.change_pct)>0 else '감소했습니다.' if Decimal(m.change_pct)<0 else '변동 없이 유지됐습니다.')) for m in pair)
                detail+=' 전년 실적 대비 변화 속도를 비교한 결과입니다.'
            else:
                lead=f'{label}은 일반적인 증가율 수치만으로 두 기업의 우열을 비교할 수 없습니다.'
                detail=' '.join(f'{m.name}: {_money(m.previous)} → {_money(m.current)}'+
                    (f' ({m.change_state}).' if m.change_pct is None else f' ({_number(abs(Decimal(m.change_pct)))}% {m.change_state}).') for m in pair)
        if item=='operating_margin':
            short_values.append(f'{label}: {a.name} {_number(a.current)}%, {b.name} {_number(b.current)}%')
        elif a.change_pct is not None and b.change_pct is not None:
            short_values.append(f'{label} 증감률: {a.name} {_number(a.change_pct)}%, {b.name} {_number(b.change_pct)}%')
        else:
            short_values.append(detail.rstrip('.'))
        leads.append(lead);sections.append(detail)
    basis='연결' if snapshot.fs_div=='CFS' else '별도'
    header=f'{snapshot.year-1}~{snapshot.year}년 연간 {basis} 기준 비교입니다.'
    # 숫자 판정은 위에서 동일 기간의 입력 두 개에만 적용한다. 서로 다른 기업의 Fact를 합쳐 모델에 맡기지 않는다.
    contract=parse_presentation(question)
    if not leads:
        return ChatResponse('\n\n'.join([header,*sections]),evidence)
    if contract.max_sentences or contract.max_lines:
        values=f'{snapshot.year-1}~{snapshot.year}년 연간 {basis} 기준으로 '+ '; '.join(short_values)+'입니다'
        meaning='; '.join(lead.rstrip('.') for lead in leads)
        limit=contract.max_sentences or contract.max_lines
        compact=(values+'; '+meaning+'.') if limit==1 else (values+'.\n'+meaning+'.')
        return ChatResponse(compact,evidence)
    return ChatResponse('\n\n'.join([*leads,header,*sections]),evidence)


def _group_answer(snapshot, question):
    """세 곳 이상도 모두의 동일 기준 수치만 비교한다. 투자 우선순위는 생성하지 않는다."""
    lookup = {(m.code, m.item): m for m in snapshot.metrics}
    leads, details, evidence = [], [], []
    for item in requested_items(question):
        rows = [lookup.get((c.stock.code, item)) for c in snapshot.companies]
        label = LABELS[item]
        if any(row is None for row in rows):
            details.append(f'{label}은 모든 기업의 공통 수치를 확보하지 못해 비교에서 제외했습니다.')
            continue
        for m in rows:
            evidence.append(_metric_evidence(snapshot,m,label))
        if item == 'operating_margin' or all(m.change_pct is not None for m in rows):
            field = 'current' if item == 'operating_margin' else 'change_pct'
            values = [Decimal(getattr(m, field)) for m in rows]
            suffix = '' if item == 'operating_margin' else ' 증감률'
            best = ', '.join(m.name for m, v in zip(rows, values) if v == max(values))
            lead = (f'{label}{suffix}은 모든 기업이 {_number(values[0])}%로 같습니다.' if len(set(values)) == 1
                    else f'{label}{suffix}이 가장 높은 기업은 {best}({_number(max(values))}%)입니다.')
            detail = '; '.join(f'{m.name} {_number(v)}%' for m,v in zip(rows,values))
            detail += (' — 매출에서 영업이익으로 남기는 비중입니다.' if item == 'operating_margin'
                       else ' — 같은 전년 대비 변화율입니다.')
        else:
            lead = '영업손익은 적자·흑자 전환과 손실 여부가 달라 일반적인 증가율로 순위를 매기지 않았습니다.'
            detail = '; '.join(f'{m.name} {_money(m.previous)} → {_money(m.current)} ({m.change_state})' for m in rows)
        leads.append(lead)
        details.append(f'{label}: {detail}')
    basis = '연결' if snapshot.fs_div == 'CFS' else '별도'
    header = f'{snapshot.year-1}~{snapshot.year}년 연간 {basis} 기준 비교입니다.'
    contract = parse_presentation(question)
    if contract.max_sentences or contract.max_lines:
        # 같은 숫자 근거를 간결하게 표현한다. 소수점은 문장 경계가 아니다.
        names = ', '.join(c.stock.name for c in snapshot.companies)
        summary = leads or details
        text = names + '의 ' + header.rstrip('.') + ' ' + '; '.join(lead.rstrip('.') for lead in summary) + '.'
    else:
        text = '\n\n'.join([*leads, header, *details])
    return ChatResponse(text, evidence)
