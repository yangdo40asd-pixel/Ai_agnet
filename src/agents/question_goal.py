"""질문 목적의 공통 분류. 자료 수집과 금융 검증은 기존 계층에서 담당한다."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionGoal:
    purpose: str = "general"

    @property
    def company_overview(self):
        return self.purpose == "company_overview"


def question_goal(question: str) -> QuestionGoal:
    """명시한 지표·뉴스·기간 질문을 넓은 기업 평가로 확대하지 않는다."""
    if re.search(r"PER|PBR|ROE|EPS|BPS|주가|현재가|가격|배당|시가총액|시총", question, re.I):
        return QuestionGoal("metric")
    if re.search(r"뉴스|기사|이슈|공시|소식", question):
        return QuestionGoal("news")
    if re.search(r"왜|원인|이유|비결|요인", question):
        return QuestionGoal("cause")
    if re.search(r"내년|올해|앞으로|향후|전망", question):
        return QuestionGoal("outlook")
    if re.search(r"실적|매출|영업이익|재무|원가|이익률|차트|거래량", question):
        return QuestionGoal("financials")
    if re.search(r"뜻|정의|뭐야|무엇|요약|정리|줄여|바꿔|전환|비교|관련주|테마", question):
        return QuestionGoal()
    if re.search(r"어때|어떤데|어떤\s*회사|괜찮|어떻게\s*생각|분석해|분석해\s*줘|상황", question):
        return QuestionGoal("company_overview")
    return QuestionGoal()
