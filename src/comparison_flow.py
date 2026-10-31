"""기업 비교의 수집·질문 범위. 기존 단일 종목 pipeline/AnalysisResult는 변경하지 않는다."""
import re
from uuid import uuid4

from src.data.company_comparison import CompanyAnnuals, build_comparison
from src.data.financials import collect_company_financials
from src.models import now_kst


def comparison_options(question):
    if re.search(r'분기|반기|잠정|누적|PER|PBR|ROE|EPS|BPS|주가|시세|뉴스|어닝콜|컨센서스|순이익|부채|자산|현금|배당|시가총액|건전성',question,re.I):
        return None,'현재 두 종목 비교는 원화 연간 매출·영업이익·영업이익률을 지원합니다. 요청하신 분기·시세·다른 지표 비교는 아직 연결되지 않았습니다.'
    years=sorted({int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?:년)?',question)})
    if len(years)>2 or len(years)==2 and years[1]!=years[0]+1:
        return None,'증가율은 서로 이어지는 두 사업연도의 자료로 비교합니다. 비교할 당기 사업연도를 지정해 주세요.'
    if '연결' in question and '별도' in question:
        return None,'두 기업에 공통으로 적용할 연결 또는 별도 기준 하나를 지정해 주세요.'
    return {'year':max(years) if years else None,'fs_div':'OFS' if '별도' in question else 'CFS' if '연결' in question else None},''


def collect_comparison(stocks,question,settings,progress=lambda _:None):
    if (not 2 <= len(stocks) <= 6 or len({s.code for s in stocks}) != len(stocks)
            or any(not s.selectable for s in stocks)):
        return None,'공식 상장 정보가 확인된 서로 다른 종목을 2~6곳 지정해 주세요.'
    options,reason=comparison_options(question)
    if reason: return None,reason
    companies=[]
    for stock in stocks:
        progress(f'{stock.name}의 연간 재무자료를 확인하고 있습니다.')
        bundle=collect_company_financials(stock,settings,preferred_fs_div=options['fs_div'] or 'CFS',
            years=(str(options['year']-1),str(options['year'])) if options['year'] else None,
            include_indices=False)
        companies.append(CompanyAnnuals(stock,tuple(bundle.get('annual_summaries') or ()),uuid4().hex,
                                      now_kst(),str(bundle.get('status') or 'failed')))
    return build_comparison(companies,**options),''


def comparison_followup(question):
    """명시적 회사/새 주제를 건드리지 않는 제한된 비교 후속 질문만 처리한다."""
    value=re.sub(r'[.!?。！？]','',question).strip()
    return bool(re.fullmatch(r'(?:그럼|그러면|둘의|두\s*회사의)?\s*(?:매출(?:액)?|영업이익|영업이익률|이익률|마진)(?:\s*(?:증가율|성장률|증감률))?(?:은|는|도|을|를)?\s*(?:어때|어떤데|비교해줘|비교해\s*줘|알려줘|알려\s*줘)?',value))
