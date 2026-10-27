"""OpenDART 기업 고유번호(corpCode.xml)·전체 재무제표(fnlttSinglAcntAll)·주요 재무지표(fnlttSinglIndx) 수집 모듈.

API 키 값은 오류 메시지·로그·반환 객체에 절대 노출하지 않는다.
"""

import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

from src.config import Settings
from src.models import AppError

DART_BASE_URL = "https://opendart.fss.or.kr/api"

REPRT_CODES: dict[str, str] = {
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
    "11011": "사업보고서",
}

FS_DIVS: dict[str, str] = {
    "CFS": "연결재무제표",
    "OFS": "별도재무제표",
}

IDX_CL_CODES: dict[str, str] = {
    "M210000": "수익성지표",
    "M220000": "안정성지표",
    "M230000": "성장성지표",
    "M240000": "활동성지표",
}

_CORP_CODE_CACHE: dict[str, object] = {
    "loaded_at": 0.0,
    "mapping": None,
}
CORP_CACHE_TTL_SECONDS = 86400.0


def clear_corp_code_cache() -> None:
    _CORP_CODE_CACHE["loaded_at"] = 0.0
    _CORP_CODE_CACHE["mapping"] = None


def interpret_dart_status(status: object, message: object = "") -> tuple[str, str]:
    """OpenDART 응답 status 코드를 내부 상태(ok/empty/auth_error/rate_limit/failed)와 안전한 안내 문구로 변환한다."""
    code = str(status or "").strip()
    if code == "000":
        return "ok", ""
    if code == "013":
        return "empty", "조회된 공시 재무 자료가 없습니다."
    if code in {"010", "011"}:
        return "auth_error", "OpenDART API 인증키가 유효하지 않거나 사용 권한이 없습니다."
    if code == "020":
        return "rate_limit", "OpenDART API 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."
    if code == "800":
        return "failed", "OpenDART 시스템 점검 중이거나 원활하지 않습니다."
    return "failed", "OpenDART 재무 자료를 확인하지 못했습니다."


def parse_corp_codes_zip(zip_bytes: bytes) -> dict[str, dict[str, object]]:
    """corpCode.xml 압축 바이트에서 상장 6자리 종목코드 → 8자리 고유번호 매핑 사전을 생성한다."""
    if not isinstance(zip_bytes, (bytes, bytearray)) or not zip_bytes:
        raise AppError("dart_corp_format", "OpenDART 고유번호 파일이 비어 있습니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_names = [name for name in zf.namelist() if name.lower().endswith(".xml")]
            if not xml_names:
                raise AppError("dart_corp_format", "OpenDART 고유번호 압축 파일에 XML이 없습니다.")
            xml_bytes = zf.read(xml_names[0])
    except zipfile.BadZipFile:
        # 인증 오류 등으로 XML 평문이 반환된 경우 status 확인
        try:
            root = ET.fromstring(zip_bytes)
            status_el = root.findtext("status")
            if status_el:
                kind, msg = interpret_dart_status(status_el, root.findtext("message"))
                raise AppError(f"dart_{kind}", msg)
        except ET.ParseError:
            pass
        raise AppError("dart_corp_format", "OpenDART 고유번호 압축 파일 형식이 올바르지 않습니다.") from None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise AppError("dart_corp_format", "OpenDART 고유번호 XML 파싱에 실패했습니다.") from None

    mapping: dict[str, dict[str, object]] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip().upper()
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        modify_date = (item.findtext("modify_date") or "").strip()

        if not stock_code:
            continue
        if not re.fullmatch(r"[A-Z0-9]{6}", stock_code) or not re.fullmatch(r"\d{8}", corp_code):
            continue

        existing = mapping.get(stock_code)
        if existing is None:
            mapping[stock_code] = {
                "corp_code": corp_code,
                "corp_name": corp_name,
                "stock_code": stock_code,
                "modify_date": modify_date,
                "ambiguous": False,
            }
        else:
            if existing["corp_code"] == corp_code:
                continue
            prev_mod = str(existing.get("modify_date") or "")
            if modify_date and prev_mod and modify_date > prev_mod:
                mapping[stock_code] = {
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "stock_code": stock_code,
                    "modify_date": modify_date,
                    "ambiguous": False,
                }
            elif modify_date and prev_mod and modify_date < prev_mod:
                continue
            else:
                existing["ambiguous"] = True

    if not mapping:
        raise AppError("dart_corp_empty", "OpenDART 상장 종목 고유번호 목록을 확인하지 못했습니다.")
    return mapping


def fetch_corp_codes(
    settings: Settings,
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, object]]:
    """OpenDART 고유번호 목록을 조회하고 정상 응답만 메모리 캐시한다."""
    if not settings.dart_api_key:
        raise AppError("dart_unconfigured", "DART_API_KEY가 설정되지 않아 기업 재무제표를 조회하지 않습니다.")

    now_ts = time.time()
    cached_map = _CORP_CODE_CACHE.get("mapping")
    loaded_at = float(_CORP_CODE_CACHE.get("loaded_at") or 0.0)
    if (
        not force_refresh
        and isinstance(cached_map, dict)
        and cached_map
        and (now_ts - loaded_at) < CORP_CACHE_TTL_SECONDS
    ):
        return cached_map

    try:
        response = requests.get(
            f"{DART_BASE_URL}/corpCode.xml",
            params={"crtfc_key": settings.dart_api_key},
            timeout=settings.request_timeout,
        )
    except requests.Timeout:
        raise AppError("dart_timeout", "OpenDART 고유번호 조회 시간이 초과되었습니다.") from None
    except requests.RequestException:
        raise AppError("dart_network", "OpenDART 고유번호 서버 연결에 실패했습니다.") from None

    if response.status_code in {401, 403}:
        raise AppError("dart_auth_error", "OpenDART API 인증에 실패했습니다.")
    if response.status_code == 429:
        raise AppError("dart_rate_limit", "OpenDART 요청 한도를 초과했습니다.")
    if response.status_code != 200:
        raise AppError("dart_http_error", "OpenDART 고유번호 응답 상태가 올바르지 않습니다.")

    mapping = parse_corp_codes_zip(response.content)
    _CORP_CODE_CACHE["mapping"] = mapping
    _CORP_CODE_CACHE["loaded_at"] = now_ts
    return mapping


def resolve_corp_code(
    stock_code: object,
    corp_map: dict[str, dict[str, object]],
) -> str:
    """6자리 상장 종목코드(선행 0 유지)로 정확히 일치하는 8자리 DART corp_code를 반환한다."""
    if not isinstance(stock_code, str) or not re.fullmatch(r"[A-Z0-9]{6}", stock_code.strip().upper()):
        raise AppError("dart_stock_code", "유효한 6자리 종목코드가 아니어서 DART 기업 고유번호를 찾을 수 없습니다.")
    code = stock_code.strip().upper()
    if not isinstance(corp_map, dict) or code not in corp_map:
        raise AppError("dart_corp_unmapped", f"종목코드({code})에 대응하는 DART 기업 고유번호를 찾지 못했습니다.")
    entry = corp_map[code]
    if entry.get("ambiguous"):
        raise AppError("dart_corp_ambiguous", f"종목코드({code})에 복수의 DART 고유번호가 존재해 임의 연결하지 않습니다.")
    corp_code = str(entry.get("corp_code") or "").strip()
    if not re.fullmatch(r"\d{8}", corp_code):
        raise AppError("dart_corp_format", "DART 기업 고유번호(8자리) 형식이 올바르지 않습니다.")
    return corp_code


def _request_dart_json(
    endpoint: str,
    params: dict[str, str],
    settings: Settings,
) -> dict[str, object]:
    """OpenDART JSON 엔드포인트를 호출하고 HTTP·본문 status를 검증한다. 인증 실패는 재시도하지 않는다."""
    if not settings.dart_api_key:
        return {
            "status": "unconfigured",
            "message": "DART_API_KEY가 설정되지 않아 재무 자료를 조회하지 않습니다.",
            "list": [],
        }

    request_params = {"crtfc_key": settings.dart_api_key, **params}
    try:
        response = requests.get(
            f"{DART_BASE_URL}/{endpoint}",
            params=request_params,
            timeout=settings.request_timeout,
        )
    except requests.Timeout:
        return {
            "status": "timeout",
            "message": "OpenDART 요청 시간이 초과되었습니다.",
            "list": [],
        }
    except requests.RequestException:
        return {
            "status": "failed",
            "message": "OpenDART 서버와 통신하지 못했습니다.",
            "list": [],
        }

    if response.status_code in {401, 403}:
        return {
            "status": "auth_error",
            "message": "OpenDART API 인증키가 유효하지 않거나 권한이 없습니다.",
            "list": [],
        }
    if response.status_code == 429:
        return {
            "status": "rate_limit",
            "message": "OpenDART API 요청 한도를 초과했습니다.",
            "list": [],
        }
    if response.status_code != 200:
        return {
            "status": "failed",
            "message": "OpenDART 응답 오류(HTTP 상태 비정상)가 발생했습니다.",
            "list": [],
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "status": "failed",
            "message": "OpenDART 응답 JSON 형식을 해석하지 못했습니다.",
            "list": [],
        }

    if not isinstance(payload, dict):
        return {
            "status": "failed",
            "message": "OpenDART 응답 구조가 올바르지 않습니다.",
            "list": [],
        }

    status_kind, status_msg = interpret_dart_status(payload.get("status"), payload.get("message"))
    items = payload.get("list")
    return {
        "status": status_kind,
        "raw_status": str(payload.get("status") or ""),
        "message": status_msg,
        "list": items if isinstance(items, list) else [],
    }


def fetch_statement(
    corp_code: str,
    bsns_year: str,
    reprt_code: str = "11011",
    fs_div: str = "CFS",
    *,
    settings: Settings,
) -> dict[str, object]:
    """단일회사 전체 재무제표(fnlttSinglAcntAll.json)를 조회한다."""
    if not re.fullmatch(r"\d{8}", str(corp_code or "").strip()):
        raise AppError("dart_corp_format", "유효한 8자리 DART 기업 고유번호가 필요합니다.")
    if not re.fullmatch(r"\d{4}", str(bsns_year or "").strip()):
        raise AppError("dart_year_format", "유효한 4자리 사업연도가 필요합니다.")
    if reprt_code not in REPRT_CODES:
        raise AppError("dart_reprt_code", "지원하지 않는 보고서 코드입니다.")
    if fs_div not in FS_DIVS:
        raise AppError("dart_fs_div", "재무제표 구분은 CFS 또는 OFS여야 합니다.")

    result = _request_dart_json(
        "fnlttSinglAcntAll.json",
        {
            "corp_code": corp_code.strip(),
            "bsns_year": bsns_year.strip(),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        },
        settings,
    )
    return {
        **result,
        "corp_code": corp_code.strip(),
        "bsns_year": bsns_year.strip(),
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }


def fetch_financial_indices(
    corp_code: str,
    bsns_year: str,
    reprt_code: str = "11011",
    idx_cl_code: str = "M210000",
    *,
    settings: Settings,
) -> dict[str, object]:
    """단일회사 주요 재무지표(fnlttSinglIndx.json)를 조회한다.

    공식 가이드 기준: 2023년 3분기 이후 제공되며 fs_div 요청 인자가 없다.
    응답에 없는 연결/별도 구분이나 접수번호를 임의로 붙이지 않는다.
    """
    if not re.fullmatch(r"\d{8}", str(corp_code or "").strip()):
        raise AppError("dart_corp_format", "유효한 8자리 DART 기업 고유번호가 필요합니다.")
    if not re.fullmatch(r"\d{4}", str(bsns_year or "").strip()):
        raise AppError("dart_year_format", "유효한 4자리 사업연도가 필요합니다.")
    if reprt_code not in REPRT_CODES:
        raise AppError("dart_reprt_code", "지원하지 않는 보고서 코드입니다.")
    if idx_cl_code not in IDX_CL_CODES:
        raise AppError("dart_idx_code", "지원하지 않는 지표 분류 코드입니다.")

    result = _request_dart_json(
        "fnlttSinglIndx.json",
        {
            "corp_code": corp_code.strip(),
            "bsns_year": bsns_year.strip(),
            "reprt_code": reprt_code,
            "idx_cl_code": idx_cl_code,
        },
        settings,
    )
    return {
        **result,
        "corp_code": corp_code.strip(),
        "bsns_year": bsns_year.strip(),
        "reprt_code": reprt_code,
        "idx_cl_code": idx_cl_code,
    }
