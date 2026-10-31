"""요청 보고기간의 미확보를 연간 답변으로 조용히 바꾸지 않는 경계."""
import re


def missing_quarter_answer(question,evidence, *, request=None):
    if request is not None and request.reason:
        return request.reason
    if request is not None:
        question = f"{request.year}년 {request.quarter}분기 실적"
    quarter=re.search(r'([1-4])\s*분기',question)
    if not quarter or not re.search(r'실적|매출|영업이익|순이익|이익률|재무',question):
        return None
    if re.search(r'뉴스|기사|보도|정의|뜻|계산식',question):
        return None
    years=set(re.findall(r'20\d{2}',question))
    def matches(period):
        compact=re.sub(r'\s+','',str(period or ''))
        return quarter[1]+'분기' in compact and (not years or any(year in compact for year in years))
    for item in evidence.values():
        if item.get('kind') in {'quarterly_financial','quarterly_comparison'} and item.get('status')=='ok' and matches(item.get('period')):
            return None
        if any(f.get('status')=='verified' and f.get('item') in {'revenue','operating_income','net_income','operating_margin'}
               and matches(f.get('financial_period')) for f in item.get('structured_facts',())):
            return None
    collection = evidence.get("Q_COLLECTION_STATUS", {})
    if (request is not None and collection.get("request_token") == request.token
            and collection.get("status") == "failed"):
        return "분기 재무자료 조회에 실패했습니다. 잠시 후 같은 기간을 다시 조회해 주세요."
    period=('·'.join(sorted(years))+'년 ' if years else '')+quarter[1]+'분기'
    return f'요청하신 {period} 재무 수치는 현재 확보한 자료에서 확인하지 못했습니다.'
