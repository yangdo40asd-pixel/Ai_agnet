"""명시적인 공식 공시 요청의 제한된 수집. 정정 관계/현재 유효 값 결정은 하지 않는다."""
from datetime import timedelta
import io
import re
import xml.etree.ElementTree as ET
import zipfile

import requests

from src.data.dart import DART_BASE_URL, fetch_corp_codes, resolve_corp_code, interpret_dart_status
from src.models import AppError, SourceDocument, now_kst

MAX_ARCHIVE_BYTES = 2_000_000
MAX_XML_BYTES = 4_000_000


def _timeout(settings):
    from src.agents.local_verification import current_turn_remaining
    remaining = current_turn_remaining()
    if remaining is not None and remaining <= 0:
        raise AppError("source_budget", "공시 조회 시간 예산이 끝났습니다.")
    return min(settings.request_timeout, remaining) if remaining is not None else settings.request_timeout


def document_text(data):
    if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE_BYTES:
        raise AppError("disclosure_format", "공시 원문의 크기 또는 형식을 확인하지 못했습니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = [v for v in archive.infolist() if v.filename.lower().endswith('.xml')]
            if not files or sum(v.file_size for v in files) > MAX_XML_BYTES:
                raise ValueError()
            parts = []
            for entry in files:
                raw = archive.read(entry)
                if re.search(br'<!DOCTYPE|<!ENTITY', raw.replace(b'\x00', b''), re.I):
                    raise ValueError()
                root = ET.fromstring(raw)
                parts.extend(t.strip() for t in root.itertext() if t.strip())
            return '\n'.join(parts)
    except (ValueError, zipfile.BadZipFile, ET.ParseError, RuntimeError):
        raise AppError("disclosure_format", "공시 원문을 읽지 못했습니다.") from None


def collect_disclosures(stock, settings, question):
    """기존 기업 매핑을 재사용해 목록1회+원문최대2회만 조회한다. 실패도 상태로 반환한다."""
    if not re.search(r'공시|공식|계약', question):
        return (), "not_requested"
    if not settings.dart_api_key:
        return (), "not_configured"
    documents = []
    try:
        _timeout(settings)
        mapping = fetch_corp_codes(settings)
        corp_code = resolve_corp_code(stock.code, mapping)
        today = now_kst().date()
        response = requests.get(DART_BASE_URL+'/list.json', params={
            'crtfc_key': settings.dart_api_key, 'corp_code': corp_code,
            'bgn_de': (today-timedelta(days=90)).strftime('%Y%m%d'), 'end_de': today.strftime('%Y%m%d'),
            'page_count': 20, 'page_no': 1, 'sort': 'date', 'sort_mth': 'desc', 'last_reprt_at': 'N'},
            timeout=_timeout(settings))
        if response.status_code != 200:
            return (), 'failed'
        payload = response.json()
        if not isinstance(payload, dict):
            return (), 'format_error'
        status, _ = interpret_dart_status(payload.get('status'))
        if status != 'ok':
            return (), status
        rows = payload.get('list')
        if not isinstance(rows, list):
            return (), 'format_error'
        terms = [v for v in ('계약', '대량보유', '주식등의대량보유', '투자', '정정', '실적') if v in question]
        matches = [r for r in rows if isinstance(r, dict) and r.get('corp_code') == corp_code
                   and re.fullmatch(r'\d{14}', str(r.get('rcept_no', '')))
                   and (not terms or any(t in str(r.get('report_nm', '')) for t in terms))]
        for row in matches[:2]:
            receipt = row['rcept_no']
            raw = requests.get(DART_BASE_URL+'/document.xml', params={
                'crtfc_key': settings.dart_api_key, 'rcept_no': receipt}, timeout=_timeout(settings))
            if raw.status_code != 200:
                continue
            text = document_text(raw.content)
            documents.append(SourceDocument('NEWS_DART_'+receipt, stock.code, stock.name,
                str(row.get('report_nm', '')), text, 'OpenDART 공시 원문',
                'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt, now_kst(),
                published_at=str(row.get('rcept_dt') or '') or None, document_id=receipt))
        return tuple(documents), 'ok' if documents else 'empty'
    except AppError as error:
        return tuple(documents), error.code
    except (requests.RequestException, ValueError, TypeError):
        return tuple(documents), 'failed'
