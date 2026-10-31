"""추가 탐색과 복수 기업 지시어를 현재 대화의 실제 후보에 연결한다."""
import re


def expansion_request(text):
    if re.search(r"말고|아니라|하지\s*마|보여\s*주지|보여주지|찾지\s*마", text):
        return False
    if re.search(r"뉴스|기사|실적|재무|PER|차트", text, re.I) and not re.search(r"관련주|관련\s*종목|후보", text):
        return False
    if re.search(r"다른\s*(?:관련주|관련\s*종목|기업|회사|종목)|추가\s*(?:관련주|관련\s*종목|후보|기업|회사|종목)", text):
        return True
    if re.search(r"^(?:더|추가로?)\s*(?:보여|찾|있|알려|소개)", text) or re.search(r"(?:더|추가로?)\s*(?:보여|찾아|알려)\s*줘", text):
        return True
    return bool(re.search(r"관련주|관련\s*종목|다른\s*(?:기업|종목|회사)|후보", text)
                and re.search(r"더|추가|다른", text)
                and re.search(r"보여|찾|있|알려|소개", text))


def explicit_expansion_theme(text):
    match = re.match(r"^(?:이번엔?\s*)?(.+?)\s*관련\s*(?:주|종목)", text)
    if not match:
        return ""
    theme = match.group(1).strip()
    return "" if re.fullmatch(r"그|이|해당|같은|다른|추가|기존|그\s*테마(?:의)?", theme) else theme


def collective_comparison(text, discovery, messages):
    if not re.search(r"비교|어디.{0,5}(?:좋|나[아았]|우세)|어느.{0,5}(?:좋|나[아았]|우세)", text):
        return None
    if not re.search(r"(?:그|이|위|해당)\s*(?:(?:두|세|네|여러)\s*(?:기업|회사|종목)|(?:기업|회사|종목)들)|둘\s*중|전체\s*후보|지금까지.*(?:기업|종목|회사)|표로\s*비교|비교표", text):
        return None
    latest = next((m for m in reversed(messages) if m.get("role") == "assistant"), {})
    snapshot = latest.get("comparison_snapshot")
    if re.search(r"전체\s*후보|지금까지", text) and discovery:
        stocks = discovery.selectable_candidates
    elif snapshot is not None:
        stocks = tuple(c.stock for c in snapshot.companies)
    else:
        stocks = tuple(s for s in discovery.latest_candidates if s.selectable) if discovery else ()
    if re.search(r"두\s*(?:기업|회사|종목)|둘\s*중", text) and len(stocks) != 2:
        return ()  # 세 후보 가운데 임의로 두 개를 고르지 않는다.
    return stocks
