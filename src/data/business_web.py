"""검증된 기업 홈페이지에서 제한된 사업/제품 HTML 절을 읽는다. 웹 전체 검색은 하지 않는다."""
from html.parser import HTMLParser
import hashlib
import ipaddress
import re
import socket
from threading import Lock
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from src.data.business_budget import business_timeout
from src.models import AppError, CompanyBusinessSource, now_kst

WEB_REVISION = "official-business-html-v2"
_BUSINESS = re.compile(r"사업|제품|기술|솔루션|business|product|solution|technolog", re.I)
_NOT_BUSINESS = re.compile(r"뉴스|공고|보도|채용|오시는|개인정보|이용약관|공지|연혁|윤리|사업연속성|news|notice|recruit|privacy|contact|history|business\s+continuity|business\s+conduct", re.I)
_SKIP = {"script", "style", "nav", "header", "footer", "form", "noscript", "svg"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_CACHE_TTL = 3600
_cache = {}
_cache_lock = Lock()


def _host(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _same_company_host(url, home):
    host, root = _host(url), _host(home)
    return bool(root and (host == root or host.endswith('.' + root)))


def official_url(url, *, home=""):
    """공식 등록 주소/동일 호스트만 허용한다. 요청 전 모든 해석 주소를 확인한다."""
    if not isinstance(url, str) or len(url) > 2000 or any(c.isspace() for c in url):
        raise AppError("business_url", "공식 홈페이지 주소를 확인하지 못했습니다.")
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password
                or parts.port not in {None, 80, 443} or (home and not _same_company_host(url, home))):
            raise ValueError()
        addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise AppError("business_url", "공식 홈페이지 주소를 확인하지 못했습니다.") from None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


class _Page(HTMLParser):
    """제목별로 원문을 나눈다. 다른 제품/절을 한 사실로 합치지 않는다."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []
        self.links = []
        self.title = ""
        self.heading = ""
        self.parts = []
        self.skipped = []
        self.in_title = False
        self.in_heading = False
        self.anchor = None

    def _flush(self):
        text = " ".join(" ".join(self.parts).split())
        if self.heading and len(text) >= 70:
            self.sections.append((self.heading, text[:2400]))
        self.parts = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "a":
            self.anchor = [attrs.get("href", ""), []]
        if self.skipped:
            if tag not in _VOID:
                self.skipped.append(tag)
            return
        if tag in _SKIP:
            self.skipped.append(tag)
            return
        if attrs.get("aria-hidden") == "true" or "hidden" in attrs:
            # 숨긴 안내문을 사업 본문으로 채택하지 않는다.
            if tag not in _VOID:
                self.skipped.append(tag)
            return
        if tag == "title":
            self.in_title = True
        if tag in {"h1", "h2", "h3", "h4"}:
            self._flush()
            self.heading = ""
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor[0], " ".join(self.anchor[1])))
            self.anchor = None
        if self.skipped:
            if tag == self.skipped[-1]:
                self.skipped.pop()
            return
        if tag == "title":
            self.in_title = False
        if tag in {"h1", "h2", "h3", "h4"}:
            self.in_heading = False

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor[1].append(data)
        if self.skipped:
            return
        if self.in_title:
            self.title += data
        elif self.in_heading:
            self.heading += data
        else:
            self.parts.append(data)

    def close(self):
        super().close()
        self._flush()


def _download(url, home, settings):
    for _ in range(3):
        business_timeout(settings)
        url = official_url(url, home=home)
        try:
            with requests.get(url, timeout=business_timeout(settings), stream=True, allow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status_code != 200 or "html" not in response.headers.get("Content-Type", "").lower():
                    raise AppError("business_web_format", "공식 사업 페이지의 HTML을 확인하지 못했습니다.")
                chunks, size = [], 0
                for chunk in response.iter_content(64 * 1024):
                    business_timeout(settings)
                    size += len(chunk)
                    if size > 1_500_000:
                        raise AppError("business_web_size", "사업 페이지 응답이 너무 큽니다.")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                encoding = re.search(r"charset\s*=\s*[\"']?([\w-]+)", response.headers.get("Content-Type", ""), re.I)
                meta_encoding = re.search(br"<meta\b[^>]*charset\s*=\s*[\"']?([\w-]+)", raw[:8000], re.I)
                codec = encoding[1] if encoding else meta_encoding[1].decode('ascii') if meta_encoding else "utf-8"
                try:
                    text = raw.decode(codec)
                except (UnicodeError, LookupError):
                    raise AppError("business_web_encoding", "사업 페이지의 문자 인코딩을 확인하지 못했습니다.") from None
                page = _Page()
                page.feed(text)
                page.close()
                return url, page
        except requests.RequestException:
            raise AppError("business_web_http", "공식 사업 페이지를 조회하지 못했습니다.") from None
    raise AppError("business_web_redirect", "공식 사업 페이지 이동을 확인하지 못했습니다.")


def collect_official_pages(stock, home, settings):
    """최대3페이지. 등록된 홈페이지가 신뢰 출발점이며 회사별 하드코딩은 없다."""
    import time
    cache_key = (stock.code, stock.name, home, WEB_REVISION)
    with _cache_lock:
        cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]
    canonical = official_url(home)
    landing_url, landing = _download(canonical, canonical, settings)
    pages = [(landing_url, landing)]
    seen = {landing_url}
    attempted = 0
    links = sorted(landing.links, key=lambda pair: -bool(re.search(r'제품|product|solution', pair[1], re.I)))
    for href, label in links:
        if attempted >= 2:
            break
        if not href or not _BUSINESS.search(label) or _NOT_BUSINESS.search(label):
            continue
        url = urljoin(landing_url, href)
        parts = urlsplit(url)
        if parts.scheme not in {'http', 'https'} or not _same_company_host(url, canonical):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))
        if urlsplit(url).path.lower().endswith(".pdf") or url in seen:
            continue
        seen.add(url)
        attempted += 1
        try:
            pages.append(_download(url, canonical, settings))
        except AppError:
            continue
    result = []
    retrieved = now_kst()
    for url, page in pages:
        for title, text in page.sections:
            if _NOT_BUSINESS.search(title) or not _BUSINESS.search(title + " " + page.title):
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            if any(s.content_hash == digest for s in result):
                continue
            result.append(CompanyBusinessSource(stock.name, stock.code, "WEB_" + hashlib.sha256(url.encode()).hexdigest()[:16],
                page.title.strip()[:180], title.strip()[:140], text, url, retrieved, digest, WEB_REVISION,
                source="기업 공식 홈페이지 사업·제품 설명"))
            if len(result) == 4:
                break
        if len(result) == 4:
            break
    if result:
        with _cache_lock:
            if len(_cache) >= 128:
                _cache.pop(next(iter(_cache)))
            _cache[cache_key] = (time.monotonic(), tuple(result))
    return tuple(result)
