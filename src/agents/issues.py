"""확보된 자료의 명시적 사건 식별. 유사 제목이나 발행일만으로 병합하지 않는다."""
from dataclasses import dataclass, asdict
from decimal import Decimal
import hashlib
import re

from src.models import AppError


@dataclass(frozen=True)
class VerifiedEventLink:
    """상위의 공식 관계 검증기가 제공할 연결. 현재 수집기는 이를 자동 생성하지 않는다(Y)."""
    evidence_id: str
    company: str
    event_id: str
    document_id: str
    supersedes_document_id: str = ''
    changed_items: tuple[str,...] = ()


@dataclass(frozen=True)
class IssueGroup:
    issue_id: str
    evidence_ids: tuple[str,...]
    company: str
    kind: str
    anchors: tuple[str,...]
    reason: str
    conflicts: tuple[str,...] = ()
    versions: tuple[tuple[str,str,tuple[str,...]],...] = ()
    confirmed: bool = False

    def payload(self):
        return asdict(self)


_BUSINESS_EVENTS = (
    (re.compile(r'브랜드\s*가치|브랜드가치'), 'brand', 'brand_value'),
    (re.compile(r'사내\s*대출|임직원\s*대출|직원\s*대출'), 'employee_finance', 'employee_loan'),
)


def _business_event(title):
    # 제목에 명시된 회사 사건을 우선한다. 부동산·시장 영향 등은 새 사실로 추론하지 않는다.
    return next(((kind, anchor) for pattern, kind, anchor in _BUSINESS_EVENTS if pattern.search(title)), None)


def _identity(key,item,link=None):
    text=' '.join(str(item.get(k) or '') for k in ('text','excerpt','source_excerpt'))
    company=str(item.get('subject_quote') if item.get('relation')=='industry' else item.get('stock_name') or item.get('stock_code') or '')
    if link is not None and link.company==company and link.event_id and link.document_id:
        return company,'linked',(link.event_id,),'verified_event_link',True
    # 결과 객체의 대상 명칭만으로 타사 기사를 같은 회사 사건으로 묶지 않는다.
    boundary=r'(?=$|[^가-힣A-Za-z0-9]|(?:은|는|이|가|의|와|과|에서|에|를|을)(?=$|[^가-힣A-Za-z0-9]))'
    if company and not re.search(r'(?<![가-힣A-Za-z0-9])'+re.escape(company)+boundary,text):
        title=str(item.get('text') or '')
        kind=('earnings' if re.search(r'실적|매출|영업이익|사업보고서',title) and not re.search(r'전망|예상|발표\s*예정',title)
              else 'contract' if re.search(r'계약|수주',title)
              else 'investment' if re.search(r'투자|생산라인|생산\s*확대|가동\s*계획',title)
              else 'regulatory' if re.search(r'공정위|공정거래위원회|과징금|제재|행정처분|시정명령|금융위|금감원|과태료',title)
              else 'legal' if re.search(r'소송|재판|판결|선고|구속|기밀유출|영업비밀|특허\s*분쟁|특허\s*소송|법원|가처분|기소|항소|손해배상',title)
              else 'product' if re.search(r'품질만족|KS-QEI|품질|수상|인증|신제품|출시|HBM|양산|차세대|개발|공정',title)
              else 'shareholder' if re.search(r'주주환원|배당|자사주|소각|취득|주주총회',title)
              else 'management' if re.search(r'인사|선임|대표이사|사장단|조직개편|경영쇄신|이사회',title)
              else 'unknown')
        special=_business_event(title)
        if special:
            kind=special[0]
        # 회사 귀속을 미확인으로 남기되, 이미 다른 사건 종류인 자료를 같은 사건으로 만들지 않는다.
        return '', kind, (key,), 'company_role_unconfirmed', False
    facts=[f for f in item.get('structured_facts',()) if f.get('status')=='verified']
    title=str(item.get('text') or '')
    special=_business_event(title)
    if special:
        return company,special[0],(special[1],),'explicit_business_topic',False
    periods=sorted(set(re.sub(r'\s+','',m[0]) for m in re.finditer(r'20\d{2}년\s*(?:[1-4]분기|연간|사업연도)',title)))
    if not periods:
        periods=sorted(set(re.sub(r'\s+','',m[0]) for m in re.finditer(r'20\d{2}년\s*(?:[1-4]분기|연간|사업연도)',text)))
    basis='CFS' if '연결' in text else 'OFS' if '별도' in text else 'unknown'
    if re.search(r'실적|매출|영업이익|사업보고서',title) and not re.search(r'전망|예상|발표\s*예정',title):
        return company,'earnings',tuple(periods)+(basis,) if periods else (key,),'same_financial_period' if periods else 'period_unknown',bool(periods and company)
    if re.search(r'계약|수주',title):
        contract=re.search(r'계약\s*(?:번호|ID)\s*[:：]?\s*([A-Za-z0-9_-]+)',text,re.I)
        partner=re.search(r'([가-힣A-Za-z0-9]+)(?:와|과)\s+([^.,;\n]{2,35}?)(?:공급\s*)?계약',text)
        if contract:
            return company,'contract',(contract[1],),'explicit_contract_id',bool(company)
        if partner:
            return company,'contract',('counterparty:'+partner[1],re.sub(r'\s+','',partner[2]),key),'counterparty_known_contract_identity_unknown',False
        return company,'contract',(key,),'contract_identity_unknown',False
    if re.search(r'투자|생산라인|생산\s*확대|가동\s*계획',title):
        project=re.search(r'(신규\s*생산라인|[가-힣A-Za-z0-9]+\s*(?:생산라인|공장)|생산\s*확대)',text)
        amounts=sorted(set(f['value'] for f in facts if f['item']=='investment_amount'))
        targets=sorted(set(f['raw_text'] for f in facts if f['item']=='target_date'))
        target_periods=sorted(set(re.sub(r'\s+','',m[0]) for m in re.finditer(r'20\d{2}년\s*(?:상반기|하반기|[1-4]분기)',text)))
        if targets and target_periods:
            targets=target_periods
        anchors=((re.sub(r'\s+','',project[0]),) if project else ())+tuple(amounts)+tuple(targets)
        strong=bool(company and project and amounts and targets)
        return company,'investment',anchors if strong else (key,),'project_and_verified_facts' if strong else 'project_identity_unknown',strong
    if re.search(r'공정위|공정거래위원회|과징금|제재|행정처분|시정명령|금융위|금감원|과태료',title):
        agency=('공정위' if re.search(r'공정위|공정거래위원회',text)
                else '금융위' if '금융위' in text
                else '금감원' if '금감원' in text
                else '규제당국')
        action=('과징금' if '과징금' in text
                else '시정명령' if '시정명령' in text
                else '제재' if '제재' in text
                else '과태료' if '과태료' in text
                else '행정처분' if '행정처분' in text
                else '조사')
        amounts=sorted(set(f['value'] for f in facts if f.get('item') in {'fine_amount','penalty_amount'}))
        anchors=(agency,action)+tuple(amounts)
        return company,'regulatory',anchors,'regulatory_agency_action',False
    if re.search(r'소송|재판|판결|선고|구속|기밀유출|영업비밀|특허\s*분쟁|특허\s*소송|법원|가처분|기소|항소|손해배상',title):
        topic=('기밀유출' if re.search(r'기밀유출|영업비밀',text)
               else '특허' if '특허' in text
               else '손해배상' if '배상' in text
               else '소송')
        stage=('판결' if re.search(r'판결|선고|구속|징역',text)
               else '기소' if re.search(r'기소|수사',text)
               else '항소' if '항소' in text
               else '분쟁')
        anchors=(topic,stage)
        return company,'legal',anchors,'legal_matter',False
    if re.search(r'주주환원|배당|자사주|소각|취득|주주총회',title):
        topic=('소각' if '소각' in text else '자사주' if '자사주' in text else '배당' if '배당' in text else '주주환원')
        anchors=(topic,)
        return company,'shareholder',anchors,'shareholder_return_policy',False
    if re.search(r'인사|선임|대표이사|사장단|조직개편|경영쇄신|이사회',title):
        topic=('대표이사' if '대표이사' in text else '인사' if '인사' in text else '조직개편')
        anchors=(topic,)
        return company,'management',anchors,'management_governance',False
    if re.search(r'품질만족|KS-QEI|품질|수상|인증|신제품|출시|HBM|양산|차세대|개발|공정',title):
        award='품질만족지수' if re.search(r'품질만족|KS-QEI',text) else None
        prod=re.search(r'(HBM[0-9A-Za-z]*|갤럭시[A-Za-z0-9\s]*|D램|낸드|파운드리)',text)
        if award:
            anchors=(award,)
        elif prod:
            anchors=(re.sub(r'\s+','',prod[0]),)
        else:
            action=('출시' if '출시' in text else '양산' if '양산' in text else '개발' if '개발' in text else '품질' if '품질' in text else '제품')
            anchors=(action,)
        return company,'product',anchors,'product_or_technology',False
    # 사건 종류가 다른 자료는 분리할 수 있지만, 미확인 사건 여러 개로 카드 수를 채우지 않는다.
    return company,'unknown',(key,),'event_identity_unknown',False


def group_issues(evidence, *, verified_links=()):
    links={v.evidence_id:v for v in verified_links if isinstance(v,VerifiedEventLink)
           and v.evidence_id in evidence and evidence[v.evidence_id].get('document_id')==v.document_id}
    groups={}
    for key,item in evidence.items():
        if not key.startswith('NEWS_') or key=='NEWS_STATUS':
            continue
        identity=_identity(key,item,links.get(key))
        company,kind,anchors,reason,confirmed=identity
        signature=(company,kind,anchors)
        groups.setdefault(signature,[]).append(key)
    result=[]
    for (company,kind,anchors),ids in groups.items():
        fields={}
        for key in ids:
            for f in evidence[key].get('structured_facts',()):
                if f.get('status')=='verified' and f.get('item') not in {'event_date','financial_period','target_date'}:
                    slot=(f['item'],f['unit'],f.get('financial_period'))
                    fields.setdefault(slot,set()).add(Decimal(str(f['value'])))
        conflicts=tuple(sorted({slot[0] for slot,values in fields.items() if len(values)>1}))
        versions=tuple((links[k].document_id,links[k].supersedes_document_id,links[k].changed_items)
                       for k in ids if k in links and links[k].company==company)
        # 제공된 변경 항목 관계만 이력으로 취급한다. 나머지 충돌은 그대로 남긴다.
        documents={document for document,_,_ in versions}
        changed={item for _,previous,items in versions if previous in documents for item in items}
        previous_by_document={document:previous for document,previous,_ in versions}
        for document in previous_by_document:
            seen=set()
            while document in previous_by_document and document:
                if document in seen:
                    changed=set()  # 주입된 연결도 순환이면 값 대체 근거로 사용할 수 없다.
                    break
                seen.add(document)
                document=previous_by_document[document]
        conflicts=tuple(item for item in conflicts if item not in changed)
        _,_,_,reason,confirmed=_identity(ids[0],evidence[ids[0]],links.get(ids[0]))
        fingerprint=hashlib.sha256(repr((company,kind,anchors)).encode()).hexdigest()[:12]
        result.append(IssueGroup('ISSUE_'+fingerprint,tuple(ids),company,kind,anchors,reason,conflicts,versions,confirmed))
    return tuple(result)


def card_groups(groups):
    """미확인 같은 종류 자료는 여러 독립 이슈라고 확정하지 않는다."""
    selected=[]
    for group in sorted(groups,key=lambda g:(not g.confirmed, g.kind=='unknown')):
        same=[g for g in selected if g.company==group.company and (g.kind==group.kind or group.kind=='unknown')]
        distinct_partner=(group.kind=='contract' and group.anchors[0].startswith('counterparty:')
                          and same and all(g.anchors[0].startswith('counterparty:') and g.anchors[0]!=group.anchors[0] for g in same))
        if not group.confirmed and same and not distinct_partner:
            continue
        selected.append(group)
    return tuple(selected)


def validate_issue_cards(response, evidence, groups, *, max_issues=3):
    eligible=card_groups(groups)
    by_source={key:g for g in eligible for key in g.evidence_ids}
    # 사건 식별이 안 된 같은 회사의 기사는 카드 수 계산에서 하나로 묶여 있다. 그 카드 한 장이 같은 묶음의
    # 기사를 함께 인용하는 것은 허용한다. 카드 수와 확인된 사건의 분리는 그대로이며 독립 사건으로 세지 않는다.
    pooled={g.company:g for g in eligible if not g.confirmed and g.kind=='unknown'}
    for g in groups:
        if not g.confirmed and g.kind=='unknown' and g.company in pooled:
            for key in g.evidence_ids:
                by_source.setdefault(key,pooled[g.company])
    if len(response.blocks)>min(max_issues,len(eligible)):
        raise AppError('chat_issues','확인한 독립 사건 수보다 카드가 많습니다.')
    used=set()
    for block in response.blocks:
        news=[key for key in block.evidence_ids if key.startswith('NEWS_') and key!='NEWS_STATUS']
        owners={by_source[key].issue_id for key in news if key in by_source}
        if not news or any(key not in by_source for key in news) or len(owners)!=1 or owners & used:
            raise AppError('chat_issues','동일 사건을 반복하거나 다른 사건을 한 카드에 섞었습니다.')
        group=by_source[news[0]]
        if group.conflicts and not re.search(r'상충|서로\s*다|차이|충돌|다르게|일치하지',block.text+' '+response.intro):
            raise AppError('chat_issues','자료 간 수치 충돌을 임의로 해소했습니다.')
        used.update(owners)


def fold_report_blocks(blocks, evidence):
    """종목 선택 직후 기본 리포트도 동일 사건을 한 카드에 표시한다. 금융 카드는 보존한다."""
    from src.models import AnswerBlock
    groups=group_issues(evidence)
    by_source={key:g for g in groups for key in g.evidence_ids}
    result=[]
    locations={}
    news_count=0
    for block in blocks:
        news=[key for key in block.evidence_ids if key in by_source]
        owners={by_source[key].issue_id for key in news}
        if not news:
            result.append(block)
            continue
        # 이전 저장 리포트의 여러 근거에 걸친 일반 문장은 새 사건 연결이라고 단정하지 않는다.
        group=by_source[news[0]] if len(owners)==1 else None
        if group is not None and group.issue_id in locations:
            index=locations[group.issue_id]
            old=result[index]
            ids=tuple(dict.fromkeys((*group.evidence_ids,*old.evidence_ids,*block.evidence_ids)))
            if group.conflicts:
                result[index]=AnswerBlock('자료 간 수치 차이','같은 사건의 수치가 자료마다 다르게 기재돼 있습니다. 원문을 함께 확인할 수 있습니다.',ids)
            else:
                bodies=list(dict.fromkeys(part for text in (old.text,block.text) for part in text.split('\n\n')))
                title='종합 분석' if '종합 분석' in {old.title,block.title} else old.title
                result[index]=AnswerBlock(title,'\n\n'.join(bodies),ids)
            continue
        if news_count>=3:
            continue
        if group is not None:
            locations[group.issue_id]=len(result)
            block=AnswerBlock(block.title,block.text,tuple(dict.fromkeys((*group.evidence_ids,*block.evidence_ids))),block.implication)
            if group.conflicts:
                block=AnswerBlock('자료 간 수치 차이','같은 사건의 수치가 자료마다 다르게 기재돼 있습니다. 원문을 함께 확인할 수 있습니다.',block.evidence_ids)
        result.append(block)
        news_count+=1
    return tuple(result)
