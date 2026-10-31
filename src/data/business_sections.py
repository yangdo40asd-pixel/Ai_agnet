"""DART 정기보고서의 사업 절만 추출한다. 서로 다른 제품 절을 합치지 않는다."""
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
import unicodedata

from src.models import AppError, CompanyBusinessSource

PARSER_REVISION = "business-sections-v2"
MAX_ARCHIVE_BYTES = 12_000_000
MAX_XML_BYTES = 32_000_000
MAX_SECTIONS = 4
MAX_SECTION_CHARS = 6000
_HEADINGS = re.compile(r"^(?:사업의개요|주요제품(?:및서비스)?|주요제품등|제품및서비스|주요제품및원재료)$")


def _tag(element):
    return element.tag.rsplit("}", 1)[-1].upper()


def _text(element):
    return " ".join(" ".join(element.itertext()).split())


def _business_fragment(raw):
    """다른 장의 '<테마>' 같은 비XML 표기로 전체 파싱이 실패하면 검수 대상 장만 파싱한다."""
    cover = re.search(br'<COMPANY-NAME\b[^>]*>[^<]{1,500}</COMPANY-NAME>', raw, re.I)
    if cover is None:
        raise ET.ParseError('missing company cover')
    selected = []
    for match in re.finditer(br'<SECTION-1\b[^>]*>.*?</SECTION-1>', raw, re.I | re.S):
        title = re.search(br'<TITLE\b[^>]*>.*?</TITLE>', match[0], re.I | re.S)
        if title is None:
            continue
        heading = unicodedata.normalize('NFKC', _text(ET.fromstring(title[0])))
        heading = re.sub(r'^[\dIVXivx.()\s]+', '', heading)
        if re.sub(r'\s+', '', heading) == '사업의내용':
            selected.append(match[0])
    if not selected:
        raise ET.ParseError('missing business chapter')
    # 외부 스키마를 로드하지 않는다. 표지와 선택한 사업 장의 태그 구조는 여전히 엄격히 검사한다.
    prefix = b'<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xlink="http://www.w3.org/1999/xlink">'
    return ET.fromstring(prefix + cover[0] + b''.join(selected) + b'</DOCUMENT>')


def _roots(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_ARCHIVE_BYTES:
        raise AppError("business_document_size", "사업 원문의 크기를 확인하지 못했습니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            files = [e for e in entries if e.filename.lower().endswith(".xml")]
            if (len(entries) > 64 or not files or
                    sum(e.file_size for e in files) > MAX_XML_BYTES):
                raise ValueError()
            roots = []
            for entry in files:
                raw = archive.read(entry)
                if re.search(br"<!DOCTYPE|<!ENTITY", raw.replace(b"\x00", b""), re.I):
                    raise ValueError()
                # DART 원문 표에 '< 5% hydrogen' 같은 이스케이프되지 않은 비교문이 있다.
                # 숫자 비교의 '<'와 R&D 같은 문자 '&'만 이스케이프한다. 태그 구조는 복구하지 않는다.
                normalized = re.sub(br"<(?=\s*[0-9=])", b"&lt;", raw)
                normalized = re.sub(br"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9a-fA-F]+;)",
                                    b"&amp;", normalized)
                # 보고서에 '<이사ㆍ감사 전체의 보수현황>' 같은 한글 안내문도 있다.
                # 속성/태그가 될 수 없는 공백 포함 한글 표제만 문자로 보존한다.
                if re.search(br"encoding=[\"']utf-8[\"']", normalized[:150], re.I):
                    text = normalized.decode("utf-8")
                    def literal_label(match):
                        first = match[1].strip().split()[0].upper()
                        if first in {'P','TITLE','TABLE','TR','TD','TE','TU','SPAN','DOCUMENT'} or first.startswith('SECTION-'):
                            return match[0]
                        return '&lt;' + match[1] + '&gt;'
                    text = re.sub(r"<([ \t]*[A-Za-z가-힣][A-Za-z가-힣ㆍ·]*[ \t]+[A-Za-z가-힣0-9ㆍ·.,()% \t]{1,160})>",
                                  literal_label, text)
                    normalized = text.encode("utf-8")
                try:
                    roots.append(ET.fromstring(normalized))
                except ET.ParseError:
                    roots.append(_business_fragment(normalized))
            return roots
    except (ValueError, UnicodeError, zipfile.BadZipFile, ET.ParseError, RuntimeError, OSError):
        raise AppError("business_document_format", "사업 원문 형식을 읽지 못했습니다.") from None


def extract_business_sections(data, stock, *, document_id, document_title,
                              published_at, retrieved_at, corp_code=""):
    """절 제목을 확인한 원문만 반환한다. 관련 절이 없으면 전체 문서로 대체하지 않는다."""
    if not re.fullmatch(r"\d{14}", document_id):
        raise AppError("business_document_id", "사업 보고서 접수번호를 확인하지 못했습니다.")
    roots = _roots(data)
    # 공시의 표지에 기업명이 있으면 매핑된 회사와 대조한다. 본문 타사 언급은 소유자로 쓰지 않는다.
    from src.data.stock import normalize_name
    for root in roots:
        covers = [e for e in root.iter() if _tag(e) == "COMPANY-NAME"]
        if covers:
            cover = covers[0]
            identifier = cover.get("AREGCIK", "")
            if corp_code and identifier:
                valid = bool(re.fullmatch(r"\d{8}", corp_code) and identifier == corp_code)
            else:
                valid = normalize_name(_text(cover)).casefold() == normalize_name(stock.name).casefold()
            if not valid:
                raise AppError("business_document_company", "사업 보고서의 회사를 확인하지 못했습니다.")
    period = re.search(r"\((20\d{2}\.\d{2})\)", document_title)
    result, seen = [], set()
    for root in roots:
        for element in root.iter():
            if not re.fullmatch(r"SECTION-\d+", _tag(element)):
                continue
            title_element = next((e for e in element if _tag(e) == "TITLE"), None)
            if title_element is None:
                continue
            title = _text(title_element)
            normalized = re.sub(r"^[\dIVXivx.()\s]+", "", title)
            normalized = re.sub(r"\s+", "", normalized)
            if not _HEADINGS.fullmatch(normalized):
                continue
            # 자식 절은 자기 제목/근거로 추출한다. 상위 절 본문에 묻어 넣지 않는다.
            parts = [_text(e) for e in element if e is not title_element
                     and not _tag(e).startswith("SECTION-")]
            text = "\n".join(p for p in parts if p)[:MAX_SECTION_CHARS].strip()
            if not text:
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if (title, digest) in seen:
                continue
            seen.add((title, digest))
            result.append(CompanyBusinessSource(
                stock.name, stock.code, document_id, document_title, title, text,
                "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + document_id,
                retrieved_at, digest, PARSER_REVISION, published_at,
                period[1] if period else None, corp_code=corp_code))
            if len(result) == MAX_SECTIONS:
                return tuple(result)
    return tuple(result)
