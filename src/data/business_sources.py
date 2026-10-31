"""정기보고서 사업 절의 제한된 수집. 뉴스 수집·문장 생성·UI와 독립적이다."""
from datetime import timedelta
from dataclasses import replace
from threading import Lock
import re
import time
import xml.etree.ElementTree as ET

import requests

from src.data.business_sections import extract_business_sections, MAX_ARCHIVE_BYTES, PARSER_REVISION
from src.data.dart import DART_BASE_URL, fetch_corp_codes, resolve_corp_code, interpret_dart_status
from src.models import AppError, BusinessSourceBatch, now_kst
from src.data.business_budget import business_timeout

_cache = {}
_lock = Lock()
_TTL = 3600
_MAX_COMPANIES = 6


def current_business_source(source):
    """추출 정책 변경 후 과거 캐시의 다른 절/필터 결과를 현재 근거로 재사용하지 않는다."""
    from src.data.business_web import WEB_REVISION
    expected = WEB_REVISION if source.document_id.startswith('WEB_') else PARSER_REVISION
    return source.parser_revision == expected


def _timeout(settings):
    return business_timeout(settings)


def _fetch(path, params, settings, *, limit):
    """정해진 DART 주소만 사용한다. 인증키를 URL·예외·반환값에 기록하지 않는다."""
    try:
        with requests.get(DART_BASE_URL + path, params=params, timeout=_timeout(settings),
                          stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise AppError("business_source_http", "공식 사업 자료를 조회하지 못했습니다.")
            chunks, size = [], 0
            for chunk in response.iter_content(64 * 1024):
                _timeout(settings)
                size += len(chunk)
                if size > limit:
                    raise AppError("business_source_size", "사업 자료의 응답 크기가 너무 큽니다.")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException:
        raise AppError("business_source_http", "공식 사업 자료를 조회하지 못했습니다.") from None


def select_reports(payload, corp_code):
    """조회 기업의 정기보고서만 선택한다. 최신 값을 정정 완료로 단정하지 않는다."""
    if not isinstance(payload, dict):
        raise AppError("business_list_format", "사업 보고서 목록의 형식을 확인하지 못했습니다.")
    status, _ = interpret_dart_status(payload.get("status"))
    if status != "ok":
        return (), status
    rows = payload.get("list")
    if not isinstance(rows, list):
        raise AppError("business_list_format", "사업 보고서 목록의 형식을 확인하지 못했습니다.")
    reports = [r for r in rows if isinstance(r, dict) and r.get("corp_code") == corp_code
               and re.fullmatch(r"\d{14}", str(r.get("rcept_no", "")))
               and re.fullmatch(r"\d{8}", str(r.get("rcept_dt", "")))
               and re.match(r"^(?:\[[^\]]+\])?(?:사업|반기|분기)보고서\s*\(20\d{2}\.\d{2}\)", str(r.get("report_nm", "")))]
    # 동일 기간 내 정정문은 날짜 순서를 유지하되 정정 관계를 추론하지 않는다.
    reports.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]), reverse=True)
    return tuple(reports[:2]), "ok" if reports else "empty"


def _collect_one(stock, corp_code, settings):
    import json
    today = now_kst().date()
    # 첫 조회부터 정기보고서 주기를 포함한다. 일반 공시의90일 조건은 변경하지 않는다.
    raw = _fetch("/list.json", {
        "crtfc_key": settings.dart_api_key, "corp_code": corp_code,
        "bgn_de": (today - timedelta(days=550)).strftime("%Y%m%d"),
        "end_de": today.strftime("%Y%m%d"), "pblntf_ty": "A", "last_reprt_at": "N",
        "page_count": 20, "page_no": 1, "sort": "date", "sort_mth": "desc",
    }, settings, limit=300_000)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AppError("business_list_format", "사업 보고서 목록을 읽지 못했습니다.") from None
    reports, status = select_reports(payload, corp_code)
    if status != "ok":
        return (), status
    last_error = "no_business_sections"
    for report_index, report in enumerate(reports):
        try:
            archive = _fetch("/document.xml", {"crtfc_key": settings.dart_api_key,
                "rcept_no": report["rcept_no"]}, settings, limit=MAX_ARCHIVE_BYTES)
            if not archive.startswith(b"PK"):
                # 인증/한도 오류는 ZIP 대신 작은 XML로 온다. 자료 형식 오류로 숨기지 않는다.
                if len(archive) < 64_000 and not re.search(br"<!DOCTYPE|<!ENTITY", archive.replace(b"\x00", b""), re.I):
                    try:
                        error_status, _ = interpret_dart_status(ET.fromstring(archive).findtext("status"))
                        if error_status in {"auth_error", "rate_limit"}:
                            return (), error_status
                    except ET.ParseError:
                        pass
            sections = extract_business_sections(archive, stock,
                document_id=report["rcept_no"], document_title=report["report_nm"],
                published_at=report["rcept_dt"], retrieved_at=now_kst(), corp_code=corp_code)
            if sections:
                return sections, "ok" if report_index == 0 else "ok_earlier_report"
        except AppError as error:
            last_error = error.code
    return (), last_error


def collect_business_sources(stocks, settings):
    """호출자가 부족한 후보만 전달한다. 성공만 캐시하고 기업별 실패를 보존한다."""
    eligible = tuple(dict((s.code, s) for s in stocks if s.selectable).values())
    if not eligible:
        return BusinessSourceBatch()
    if len(eligible) > _MAX_COMPANIES:
        raise AppError("business_source_batch", "사업 자료 조회는 여섯 기업 이내로 나눠 주세요.")
    if not settings.dart_api_key:
        return BusinessSourceBatch(statuses=tuple((s.code, "not_configured") for s in eligible))
    sources, statuses = [], []
    mapping = None
    provider_blocked = ""
    for stock in eligible:
        key = (stock.code, stock.name, PARSER_REVISION)
        with _lock:
            cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < _TTL:
            sources.extend(cached[1])
            statuses.append((stock.code, cached[2]))
            continue
        if provider_blocked:
            statuses.append((stock.code, provider_blocked))
            continue
        try:
            _timeout(settings)
            if mapping is None:
                mapping = fetch_corp_codes(replace(settings, request_timeout=_timeout(settings)))
            corp_code = resolve_corp_code(stock.code, mapping)
            sections, status = _collect_one(stock, corp_code, settings)
            if status in {"auth_error", "rate_limit"}:
                provider_blocked = status
            if sections:
                with _lock:
                    if len(_cache) >= 128:
                        _cache.pop(next(iter(_cache)))
                    _cache[key] = (time.monotonic(), sections, status)
                sources.extend(sections)
            statuses.append((stock.code, status))
        except AppError as error:
            statuses.append((stock.code, error.code))
    return BusinessSourceBatch(tuple(sources), tuple(statuses))


def _official_home(stock, settings, profile):
    """KIND의 정확한 회사 행 또는 DART 기업개황으로만 홈페이지를 결정한다."""
    import json
    if profile and profile.stock_code == stock.code and profile.stock_name == stock.name and profile.website_url:
        return profile.website_url
    if not settings.dart_api_key:
        return ""
    mapping = fetch_corp_codes(replace(settings, request_timeout=_timeout(settings)))
    corp_code = resolve_corp_code(stock.code, mapping)
    raw = _fetch('/company.json', {'crtfc_key': settings.dart_api_key, 'corp_code': corp_code}, settings, limit=100_000)
    try:
        item = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AppError('business_home_format', '기업 홈페이지 등록 정보를 읽지 못했습니다.') from None
    if not isinstance(item, dict):
        raise AppError('business_home_format', '기업 홈페이지 등록 정보를 읽지 못했습니다.')
    status, _ = interpret_dart_status(item.get('status'))
    if status != 'ok':
        raise AppError('business_home_' + status, '기업 홈페이지 등록 정보를 확인하지 못했습니다.')
    if item.get('stock_code') != stock.code or item.get('corp_code', corp_code) != corp_code:
        raise AppError('business_home_company', '기업 홈페이지의 등록 회사를 확인하지 못했습니다.')
    return str(item.get('hm_url') or item.get('ir_url') or '').strip()


def collect_business_details(stocks, settings, *, profiles=()):
    """DART 사업 절을 우선하고 결측 회사만 공식 HTML로 보완한다."""
    from src.data.business_budget import business_budget
    from src.data.business_web import collect_official_pages
    stocks = tuple(s for s in stocks if s.selectable)
    by_code = {p.stock_code: p for p in profiles}
    with business_budget(45):
        primary = collect_business_sources(stocks, settings)
        sources = list(primary.sources)
        statuses = dict(primary.statuses)
        home_provider_blocked = ''
        for stock in stocks:
            if any(s.stock_code == stock.code for s in sources):
                continue
            profile = by_code.get(stock.code)
            # 제공자가 한도/인증 오류를 반환했으면 같은 제공자에 홈페이지 확인을 재요청하지 않는다.
            if statuses.get(stock.code) in {'rate_limit', 'auth_error'} and not (profile and profile.website_url):
                continue
            if home_provider_blocked and not (profile and profile.website_url):
                statuses[stock.code] = home_provider_blocked
                continue
            try:
                _timeout(settings)
                home = _official_home(stock, settings, profile)
                if not home:
                    continue
                additional = collect_official_pages(stock, home, settings)
                if additional:
                    sources.extend(additional)
                    statuses[stock.code] = 'ok_official_web'
            except AppError as error:
                statuses[stock.code] = error.code
                if error.code in {'business_home_auth_error', 'business_home_rate_limit'}:
                    home_provider_blocked = error.code
        return BusinessSourceBatch(tuple(sources), tuple(statuses.items()))
