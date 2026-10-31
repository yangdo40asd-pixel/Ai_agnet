"""최근 산업 동향과 공시·사업 자료에 기반한 대표 관심 테마 안내.
인기 순위·상승 가능성을 근거 없이 만들지 않고, 확인 가능한 산업 배경과 관찰 분야를 설명한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RecommendedTheme:
    theme: str
    display_title: str
    rationale: str
    key_areas: Sequence[str]
    suggested_query: str


RECOMMENDED_THEMES: tuple[RecommendedTheme, ...] = (
    RecommendedTheme(
        theme="AI 반도체",
        display_title="AI 반도체 및 첨단 패키징",
        rationale="데이터센터 인공지능(AI) 연산 가속기 수요 증가와 고대역폭 메모리(HBM), 첨단 2.5D 패키징 및 초미세 공정 장비 공급망 확대",
        key_areas=("고성능 메모리(DRAM·HBM) 직접 제조", "초미세 공정 및 후공정(본딩·패키징) 장비", "반도체 기판 및 검사 부품"),
        suggested_query="AI 반도체 관련주 알려줘",
    ),
    RecommendedTheme(
        theme="로봇",
        display_title="로봇 자동화 및 피지컬 AI",
        rationale="제조·물류 현장의 공정 자동화, 협동로봇(Cobot) 도입 확대 및 차세대 휴머노이드·자율이동로봇(AMR) 개발",
        key_areas=("협동로봇 및 제조용 로봇 제작", "정밀 감속기·서보모터 등 핵심 구동 부품", "산업용 자동화 제어 솔루션"),
        suggested_query="로봇 테마 보여줘",
    ),
    RecommendedTheme(
        theme="2차전지",
        display_title="2차전지 및 배터리 공급망",
        rationale="글로벌 전기차 전동화 수요 대응, ESS(에너지저장장치) 시장 성장 및 차세대 배터리(LFP·전고체) 기술 개발",
        key_areas=("배터리 셀(완제품) 직접 제조", "양극재·음극재 등 핵심 배터리 소재", "배터리 조립 및 전극 공정 장비"),
        suggested_query="2차전지 관련 기업 찾아줘",
    ),
)


def is_theme_ranking_request(text: str) -> bool:
    """순위 집계·등락률 랭킹 요청을 식별한다."""
    if re.search(r"순위|랭킹|등락률\s*순위|상승률\s*순위|1위|몇\s*위", text):
        return bool(re.search(r"테마|섹터|업종", text))
    return False


def is_theme_recommendation_request(text: str) -> bool:
    """특정 테마를 지정하지 않고 관심/추천 테마를 묻는 질문을 식별한다."""
    cleaned = text.strip()
    if is_theme_ranking_request(cleaned):
        return False
    # 명시적인 특정 산업 테마가 이미 포함된 경우(예: '반도체 테마', '2차전지 관련주')는 일반 discover로 보낸다.
    from src.data.business import theme_terms
    terms = theme_terms(cleaned)
    known_specific = {
        "반도체", "배터리", "2차전지", "이차전지", "로봇", "바이오",
        "조선", "자동차", "방산", "원전", "해운", "철강", "화학",
    }
    if any(t in known_specific for t in terms):
        return False

    # 1) '요즘 관심 가질 만한 테마주 알려줘', '요즘 핫한 테마', '주목받는 테마'
    if re.search(r"(?:최근|요즘|오늘|현재|시장).*(?:관심|주목|인기|핫한|뜨는|볼\s*만한).*테마", cleaned):
        return True
    # 2) '어떤 테마가 좋아?', '어떤 테마를 볼까?'
    if re.search(r"어떤\s*테마(?:가|를|는)?\s*(?:좋아|있어|있을까|추천|살펴|볼까)", cleaned):
        return True
    # 3) '관심 가질 테마', '관심 가질 만한 테마', '추천 테마'
    if re.search(r"(?:관심|주목|추천).*(?:가질|할|받는)?\s*(?:만한)?\s*(?:테마|테마주|섹터)", cleaned):
        return True
    # 4) '테마주 추천', '테마 추천해줘'
    if re.search(r"테마(?:주)?\s*(?:추천|뭐가|어떤\s*게|어떤\s*것)", cleaned):
        return True
    return False


def build_theme_recommendation_text() -> str:
    """근거 기반 대표 테마 소개 문장을 구성한다. 인기 순위나 상승을 보장하지 않는다."""
    lines = [
        "시장 전체의 실시간 테마 등락률이나 순위를 집계하는 통계 자료는 제공되지 않지만, 최근 산업 동향과 기업 공시·뉴스에서 관심이 이어지는 대표 테마를 소개해 드립니다.",
        "※ 아래 소개는 인기 순위나 주가 상승 보장이 아니며, 각 산업의 최근 시장 이슈와 기술·공급망 관점을 기준으로 선정한 분야입니다.",
        "",
    ]
    for item in RECOMMENDED_THEMES:
        lines.append(f"### {item.display_title}")
        lines.append(f"- **선정 배경**: {item.rationale}")
        lines.append(f"- **주요 관찰 분야**: {', '.join(item.key_areas)}")
        lines.append(f"- **탐색 예시**: \"{item.suggested_query}\"")
        lines.append("")

    lines.append(
        "위 테마 중 자세히 살펴보고 싶은 분야가 있으시거나 다른 관심 테마를 말씀해 주시면, "
        "한국거래소(KRX) 상장 정보와 금융감독원(DART) 공식 사업보고서 원문을 대조하여 "
        "관련 기업의 사업 내용과 차이를 안내해 드립니다."
    )
    return "\n".join(lines).strip()
