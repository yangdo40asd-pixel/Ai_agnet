"""뉴스 제목과 근거 링크를 수집한다. 기사 본문은 수집하지 않는다."""

import html
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

from src.config import Settings
from src.models import KST, NewsArticle, NewsData, now_kst

NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"


def news_query(theme: str, stock_name: str) -> str:
    from src.text import discovery_theme
    keyword = discovery_theme(theme)
    if keyword == stock_name or not keyword:
        return stock_name
    return f"{keyword} {stock_name}"


def safe_news_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        # 화면 링크에 제어 문자나 마크다운 문법이 섞이지 않도록 한다.
        if re.search(r"[\s<>]", value):
            return None
        return value.strip()
    except ValueError:
        return None


def clean_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())[:500]


def publication_time(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return date.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    except (TypeError, ValueError, OverflowError):
        return None


def parse_news(payload: object, sort: str = "date") -> NewsData:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return NewsData((), now_kst(), "failed", "뉴스 응답의 형식을 확인하지 못했습니다.", sort=sort)
    articles = []
    seen = set()
    unreadable = False
    for item in payload["items"]:
        if not isinstance(item, dict):
            unreadable = True
            continue
        title = clean_title(item.get("title"))
        if not title:
            unreadable = True
            continue
        original = safe_news_url(item.get("originallink"))
        url = original or safe_news_url(item.get("link"))
        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        articles.append(NewsArticle(
            id=len(articles) + 1, title=title, url=url,
            published_at=publication_time(item.get("pubDate")),
            publisher_domain=urlparse(original).hostname if original else None,
        ))
        if len(articles) == 3:
            break
    if not articles:
        status = "empty" if not payload["items"] else "failed"
        message = "검색된 뉴스가 없습니다." if status == "empty" else "뉴스 제목을 확인하지 못했습니다."
        return NewsData((), now_kst(), status, message, sort=sort)
    incomplete = any(not article.url or not article.published_at for article in articles)
    messages = []
    if unreadable:
        messages.append("일부 뉴스 항목을 읽지 못했습니다.")
    if incomplete:
        messages.append("일부 뉴스의 링크 또는 발행 시각이 없습니다.")
    return NewsData(tuple(articles), now_kst(), "partial" if messages else "ok", " ".join(messages), sort=sort)


def fetch_news(theme: str, stock_name: str, settings: Settings) -> NewsData:
    if not settings.naver_id or not settings.naver_secret:
        return NewsData((), now_kst(), "failed", "뉴스 API 설정이 없어 뉴스를 조회하지 못했습니다.", sort=settings.news_sort, error_code="news_unconfigured")
    headers = {"X-NCP-APIGW-API-KEY-ID": settings.naver_id,
               "X-NCP-APIGW-API-KEY": settings.naver_secret}
    try:
        response = requests.get(
            NEWS_URL, headers=headers,
            params={"query": news_query(theme, stock_name), "display": 3, "sort": settings.news_sort},
            timeout=settings.request_timeout,
        )
        if response.status_code != 200:
            messages = {
                401: "뉴스 API 인증 설정을 확인해 주세요.",
                403: "뉴스 API 이용 권한을 확인해 주세요.",
                429: "뉴스 API 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
            }
            error_code = {401: "news_auth_error", 403: "news_auth_error", 429: "news_rate_limit"}.get(response.status_code, "news_http_error")
            return NewsData((), now_kst(), "failed", messages.get(response.status_code, "뉴스 서비스 요청에 실패했습니다."), sort=settings.news_sort, error_code=error_code)
        return parse_news(response.json(), settings.news_sort)
    except requests.Timeout:
        return NewsData((), now_kst(), "failed", "뉴스 조회 시간이 초과되었습니다.", sort=settings.news_sort, error_code="news_timeout")
    except (requests.RequestException, ValueError):
        return NewsData((), now_kst(), "failed", "뉴스 데이터를 가져오지 못했습니다.", sort=settings.news_sort, error_code="news_request_failed")
