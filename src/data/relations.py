"""확보된 공식 원문의 명시적 기업 역할만 연결한다. 관계/정정/지분율을 추측하지 않는다."""
from dataclasses import asdict
import hashlib
import re
from urllib.parse import urlparse

from src.models import CompanyRelation


def _mention(text,name):
    return bool(name and re.search(r'(?<![가-힣A-Za-z0-9])'+re.escape(name)+
        r'(?=$|[^가-힣A-Za-z0-9]|(?:은|는|이|가|의|와|과|을|를)(?=$|[^가-힣A-Za-z0-9]))',text))


def extract_relationships(documents, stock):
    result=[]
    for document in documents:
        parsed=urlparse(document.url)
        if (document.stock_code!=stock.code or document.stock_name!=stock.name
                or document.scope!='official_disclosure' or document.source!='OpenDART 공시 원문'
                or parsed.hostname!='dart.fss.or.kr' or parsed.scheme!='https' or parsed.username or parsed.password):
            continue
        target=re.escape(stock.name)
        subject=r'(?P<subject>[가-힣A-Za-z0-9㈜()]+)'
        patterns=(
            ('shareholder',subject+r'(?:은|는|이|가)\s+'+target+r'(?:의)?\s+(?:주식|지분)[^.!?\n]{0,70}?보유(?:하|합|했|중|한|하고|$)'),
            ('shareholder',subject+r'(?:이|가)\s+보유한\s+'+target+r'(?:의)?\s+(?:주식|지분)'),
            ('supply',subject+r'(?:은|는|이|가)\s+'+target+r'(?:에|에게)\s+[^.!?\n]{0,50}?(?:공급|납품)\s*(?:계약을?\s*)?(?:체결|하고|한다|합니다)'),
            ('cooperation',subject+r'(?:은|는|이|가)\s+'+target+r'(?:와|과)\s+[^.!?\n]{0,60}?(?:공동\s*투자|공동\s*개발|협력)\s*(?:계약을?\s*)?(?:체결|합의|발표)'))
        for kind,pattern in patterns:
            for match in re.finditer(pattern,document.text[:6000]):
                line_start=document.text.rfind('\n',0,match.start())+1
                line_end=document.text.find('\n',match.end())
                context=document.text[line_start:line_end if line_end>=0 else len(document.text)]
                if re.search(r'아니|않|부인|미확인|예정|추정|검토|가능성|보유하지|계획',context):
                    continue
                name=match['subject']
                if name==stock.name:
                    continue
                digest=hashlib.sha256(document.text.encode()).hexdigest()
                identifier=hashlib.sha256((document.evidence_id+str(match.span())+digest).encode()).hexdigest()[:14]
                result.append(CompanyRelation('REL_'+identifier,stock.code,stock.name,name,kind,match[0],
                    document.evidence_id,digest,match.span(),document.url,published_at=document.published_at,
                    retrieved_at=document.retrieved_at.isoformat()))
    return tuple(result)


def article_relationships(article, stock_name, relationships, *, target_code=None):
    accepted=[]
    for fact in relationships:
        if (not isinstance(fact,CompanyRelation) or fact.target_name!=stock_name
                or target_code is not None and fact.target_code!=target_code
                or not _mention(article.title,fact.subject_name) or not _mention(article.title,stock_name)):
            continue
        pattern={'shareholder':r'(?:지분|대량보유|보유주식|담보|소유).{0,24}(?:보고|공시|변동|변경|계약|유지|보유)', 'supply':r'공급|납품|계약|수주',
                 'cooperation':r'공동|협력|투자'}.get(fact.relation)
        if pattern and re.search(pattern,article.title):
            accepted.append(fact)
    return tuple(accepted)


def relationship_payload(fact):
    return {**asdict(fact),'scope':'official_disclosure'}
