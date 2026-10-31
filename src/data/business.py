"""KIND 공개 회사목록의 사업 원문을 수집한다. 테마 판단·문장 생성은 하지 않는다."""
from io import StringIO
from threading import Lock
import re
import time

import pandas as pd
import requests

from src.models import AppError, CompanyBusinessProfile, now_kst
from src.data.stock import normalize_name

KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
KIND_PAGE = KIND_URL + "?method=loadInitPage&scrnmode=1"
_cached = None
_lock = Lock()
_TTL = 3600


def parse_business_table(html):
    try:
        table = pd.read_html(StringIO(html), converters={"종목코드": str})[0]
    except (ValueError, IndexError, ImportError) as error:
        raise AppError("business_format", "기업 사업 정보의 형식을 확인하지 못했습니다.") from error
    required = {"회사명", "종목코드", "업종", "주요제품"}
    if table.empty or not required <= set(table.columns):
        raise AppError("business_format", "기업 사업 정보의 필수 항목을 확인하지 못했습니다.")
    return table


def load_business_table(settings):
    """한 시간 캐시, 실패는 캐시하지 않는다. 공개 다운로드에 API 키를 보내지 않는다."""
    global _cached
    with _lock:
        if _cached is not None and time.monotonic() - _cached[0] < _TTL:
            return _cached[1], _cached[2]
        from src.agents.local_verification import current_turn_remaining
        remaining = current_turn_remaining()
        if remaining is not None and remaining <= 0:
            raise AppError("business_timeout", "기업 사업 정보 조회 시간 예산이 끝났습니다.")
        timeout = min(settings.request_timeout, 15, remaining if remaining is not None else 15)
        try:
            response = requests.get(KIND_URL, params={"method": "download", "searchType": "13"}, timeout=timeout)
            response.raise_for_status()
            if len(response.content) > 8_000_000:
                raise AppError("business_format", "기업 사업 정보 응답 크기가 너무 큽니다.")
            response.encoding = "euc-kr"
            table = parse_business_table(response.text)
        except requests.RequestException as error:
            raise AppError("business_failed", "공식 기업 사업 정보를 조회하지 못했습니다.") from error
        retrieved = now_kst()
        _cached = (time.monotonic(), table, retrieved)
        return table, retrieved


def _field(value):
    return "" if pd.isna(value) else " ".join(str(value).split())[:1500]


def collect_business_profiles(stocks, settings):
    table, retrieved = load_business_table(settings)
    codes = table["종목코드"].map(lambda v: str(v).strip().zfill(6))
    names = table["회사명"].map(lambda v: normalize_name(str(v)).casefold())
    profiles = []
    for stock in stocks:
        # 이름과 코드가 둘 다 일치할 때만 같은 회사의 사업 원문으로 사용한다.
        rows = table[(codes == stock.code) & (names == normalize_name(stock.name).casefold())]
        if len(rows) != 1 or not stock.selectable:
            continue
        row = rows.iloc[0]
        industry, products = _field(row["업종"]), _field(row["주요제품"])
        if not industry and not products:
            continue
        website = _field(row.get("홈페이지", ""))
        profiles.append(CompanyBusinessProfile(stock.name, stock.code, industry, products, retrieved, KIND_PAGE, website))
    return tuple(profiles)


def theme_terms(theme):
    """테마의 직접 어휘만 대조한다. 별개의 산업을 임의 동의어로 바꾸지 않는다."""
    terms = re.findall(r"[A-Za-z0-9가-힣]+", theme)
    terms = [t for t in terms if t not in {"관련", "종목", "테마", "관련주", "기업", "산업"} and len(t) >= 2]
    if any(t in {"배터리", "2차전지", "이차전지"} for t in terms):
        terms.extend(("배터리", "2차전지", "이차전지"))
    return tuple(dict.fromkeys(terms))


def direct_theme_terms(theme, profile):
    text = (profile.industry + " " + profile.products).casefold()
    return tuple(t for t in theme_terms(theme) if t.casefold() in text)


def has_direct_theme_support(theme, profile):
    terms = [t for t in re.findall(r"[A-Za-z0-9가-힣]+", theme)
             if t not in {"관련", "종목", "테마", "관련주", "기업", "산업"} and len(t) >= 2]
    found = set(direct_theme_terms(theme, profile))
    battery = {"배터리", "2차전지", "이차전지"}
    return bool(terms) and all(bool(found & battery) if t in battery else t in found for t in terms)
