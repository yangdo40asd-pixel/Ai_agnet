"""분기 재무 요청의 범위. 화면·API·LLM에 의존하지 않는 명시 기간 계약."""
from dataclasses import dataclass
from datetime import date
import re


@dataclass(frozen=True)
class QuarterRequest:
    year: int
    quarter: int
    fs_div: str | None = None
    reason: str = ""

    @property
    def token(self) -> str:
        return f"{self.year}Q{self.quarter}:{self.fs_div or 'auto'}:3m:yoy"

    @property
    def reports(self) -> tuple[tuple[str, str], ...]:
        codes = {1: ("11013",), 2: ("11012",), 3: ("11014",), 4: ("11011", "11014")}
        return tuple((str(year), code) for year in (self.year - 1, self.year)
                     for code in codes[self.quarter] if year >= 2015)


def quarter_request(question: str, *, reference_year: int | None = None) -> QuarterRequest | None:
    """정기보고서의 특정 분기만 요청한다. 잠정·기사·어닝콜을 확정 재무로 바꾸지 않는다."""
    if not re.search(r"실적|매출|영업이익|순이익|이익률|재무|마진|분기.*비교|비교.*분기", question):
        return None
    if re.search(r"뉴스|기사|보도|어닝콜|잠정|컨센서스|가이던스|정의|뜻|계산식", question):
        return None
    quarters = {int(q) for q in re.findall(r"([1-4])\s*분기", question)}
    if not quarters:
        return None
    this_year = reference_year or date.today().year
    years = {int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)}
    if not years and re.search(r"올해|금년", question):
        years = {this_year}
    elif not years and re.search(r"작년|지난해", question):
        years = {this_year - 1}
    year = max(years, default=this_year)
    basis = "OFS" if "별도" in question else "CFS" if "연결" in question else None
    reason = ""
    if not years:
        reason = "조회할 분기의 사업연도도 함께 입력해 주세요."
    elif len(quarters) != 1 or re.search(r"전분기|직전\s*분기|누적|반기", question):
        reason = "현재 분기 조회는 한 분기의 3개월 실적과 전년 동기 비교를 지원합니다. 누적 또는 전분기 비교는 별도 자료 연결이 필요합니다."
    elif len(years) > 2 or len(years) == 2 and max(years) - min(years) != 1:
        reason = "분기 증가율은 동일 분기의 전년 동기와 비교합니다. 조회할 당기 연도를 지정해 주세요."
    elif "연결" in question and "별도" in question:
        reason = "조회할 연결 또는 별도 기준 하나를 지정해 주세요."
    elif year < 2015 or year > this_year:
        reason = "현재 조회할 수 있는 사업연도의 분기를 지정해 주세요."
    return QuarterRequest(year, max(quarters), basis, reason)
