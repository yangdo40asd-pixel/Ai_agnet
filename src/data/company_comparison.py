"""2~6개 기업의 동일 연간 기준 비교. 조회·LLM·UI에 의존하지 않는다."""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
import re

from src.data.financial_comparison import annual_comparison_evidence
from src.models import AnnualFinancialSummary, StockCandidate


@dataclass(frozen=True)
class CompanyAnnuals:
    stock: StockCandidate
    summaries: tuple[AnnualFinancialSummary, ...]
    source_id: str
    retrieved_at: datetime
    status: str = 'ok'


@dataclass(frozen=True)
class CompanyMetric:
    code: str
    name: str
    item: str
    evidence_id: str
    source_id: str
    previous: str
    current: str
    change_pct: str | None
    delta_pp: str | None
    change_state: str
    value_text: str
    source_url: str = ''


@dataclass(frozen=True)
class ComparisonSnapshot:
    comparison_id: str
    companies: tuple[CompanyAnnuals, ...]
    year: int | None = None
    fs_div: str = ''
    metrics: tuple[CompanyMetric, ...] = ()
    reason: str = ''


def _items_for_period(evidence: dict, period: tuple[int, str]) -> set[str]:
    return {v['item'] for v in evidence.values()
            if (v['years'][-1],v['fs_div'])==period}


def build_comparison(
    companies: Iterable[CompanyAnnuals], *, year: int | None = None, fs_div: str | None = None
) -> ComparisonSnapshot:
    """명시 연도는 대체하지 않는다. 미지정이면 모든 기업의 최신 공통 전년비 기간을 고른다."""
    companies=tuple(companies)
    snapshot=ComparisonSnapshot(uuid4().hex,companies)
    def unavailable(reason):
        return ComparisonSnapshot(snapshot.comparison_id,companies,reason=reason)
    if (not 2 <= len(companies) <= 6 or len({c.stock.code for c in companies})!=len(companies)
            or any(not c.stock.selectable for c in companies)):
        return unavailable('공식 상장 정보가 확인된 서로 다른 종목을 2~6곳 지정해 주세요.')
    if any(c.status!='ok' or not c.summaries for c in companies):
        return unavailable('요청한 기업의 연간 재무자료를 모두 확보하지 못해 실적 비교를 완료하지 못했습니다.')
    entries=[]
    periods=[]
    for company in companies:
        evidence=annual_comparison_evidence(company.summaries,stock_code=company.stock.code,result_id=company.source_id)
        # 근거 함수가 중복 연도/통화/누락/전기 불연속을 거절한 결과만 사용한다.
        evidence={k:v for k,v in evidence.items()
                  if v.get('kind')=='annual_comparison'
                  and v.get('item') in {'revenue','operating_income','operating_margin'}}
        entries.append(evidence)
        periods.append({(v['years'][-1],v['fs_div']) for v in evidence.values()})
    common=set.intersection(*periods)
    # 같은 연도라도 A는 매출만, B는 영업이익만 있으면 비교 가능한 쌍이 아니다.
    common={period for period in common if set.intersection(*(_items_for_period(entry,period) for entry in entries))}
    if year is not None: common={p for p in common if p[0]==year}
    if fs_div is not None: common={p for p in common if p[1]==fs_div}
    if not common:
        return unavailable('두 기업에서 같은 전기·당기 사업연도와 연결·별도 기준의 원화 연간 비교자료를 확인하지 못했습니다. 요청 기간을 다른 연도로 바꾸거나 서로 다른 기준을 섞어 비교하지 않았습니다.')
    chosen_year=max(p[0] for p in common)
    bases={basis for y,basis in common if y==chosen_year}
    if len(bases)!=1:
        return unavailable('공통 연결·별도 자료가 모두 있어 비교할 회계 기준을 지정해 주세요.')
    basis=next(iter(bases))
    metrics=[]
    for company,evidence in zip(companies,entries):
        for key,item in evidence.items():
            if item['years']!=[chosen_year-1,chosen_year] or item['fs_div']!=basis: continue
            current=next(s for s in company.summaries if int(s.bsns_year)==chosen_year and s.fs_div==basis and s.currency=='KRW' and s.reprt_code=='11011')
            receipt=str(current.rcept_no or '')
            source_url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt if re.fullmatch(r'\d{14}',receipt) else ''
            metrics.append(CompanyMetric(company.stock.code,company.stock.name,item['item'],
                company.stock.code+'_'+key,company.source_id,item['previous'],item['current'],
                item.get('change_pct'),item.get('delta_pp'),item.get('change_state',''),item['value_text'],source_url))
    return ComparisonSnapshot(snapshot.comparison_id,companies,chosen_year,basis,tuple(metrics))
