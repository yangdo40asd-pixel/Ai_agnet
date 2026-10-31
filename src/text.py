"""외부 호출에 의존하지 않는 검색어 정리."""
import re


def discovery_theme(text: str) -> str:
    text = re.sub(r"^(?:다른|새로운|새)\s*테마(?:로|는)?\s*", "", text.strip())
    text = re.sub(r"(?:찾아|검색해|탐색해|알려|분석해|알아보).*?$", "", text).strip()
    text = re.sub(r"\s+(?:좀|한번|한 번)\s*$", "", text).strip()
    text = re.sub(r"(?:쪽에는?\s*)?어떤\s*종목.*$", "", text).strip()
    text = re.sub(r"\s*(?:(?:관련|테마)\s*)?(?:테마주|관련주|종목|테마)(?:들|을|를|이|가|은|는)?\s*$", "", text).strip()
    res = text.strip(" .?!")
    if res in {"요즘 관심 가질 만한", "관심 가질 만한", "관심 가질", "어떤", "무슨", "추천", "인기", "주목받는", "핫한", "뜨는", "관심", "테마"}:
        return ""
    return res
