"""기업별 사업 원문에서 질문에 필요한 발췌와 안정적인 인용ID를 만든다. 판단 문장은 생성하지 않는다."""
import hashlib
import re

from src.data.business import theme_terms
from src.data.business_sources import current_business_source

MEMORY_REFERENCE_URL = 'https://semiconductor.samsung.com/kr/about-us/business-area/memory/'


def business_area_terms(area):
    """제품 분류의 한·영 표현. 기업/고객/수혜 관계를 대신 추정하지 않는다."""
    cf = area.casefold()
    if cf in {'메모리', 'memory'}:
        return ('메모리', 'memory', 'DRAM', 'NAND')
    if cf in {'소재', 'material', 'materials'}:
        return ('소재', 'material', 'materials', '재료', '양극재', '음극재', '원재료', '소재부품')
    if cf in {'장비', 'equipment'}:
        return ('장비', 'equipment', '설비', '기기', '장치')
    if cf in {'부품', 'component', 'components'}:
        return ('부품', 'component', '모듈', '소자')
    return (area,) if area else ()


def matches_business_area(item, area):
    text = ' '.join(str(item.get(k, '')) for k in ('industry', 'products', 'section_title'))
    if area.casefold() in {'메모리', 'memory'}:
        text = re.sub(r'비\s*메모리|非\s*메모리|\bnon[\s-]*memory\b', '', text, flags=re.I)
    for term in business_area_terms(area):
        if term.isascii():
            if re.search(r'(?<![A-Za-z0-9])' + re.escape(term) + r'(?![A-Za-z0-9])', text, re.I):
                return True
        elif term in text:
            return True
    return False


def _is_financial_statement_piece(piece: str) -> bool:
    # 매출액, 영업이익 등의 회계 실적/수치 나열 문장은 사업 모델이나 제품 용도 설명이 아님
    if re.search(r"(?:매출액?|영업이익|당기순이익|자산총계|부채총계)\s*(?:은|는|이)?\s*\d+[\d,]*\s*(?:조|억|만|천)?\s*원", piece):
        return True
    if re.search(r"\d+[\d,]*\s*(?:조|억|만|천)?\s*원\s*(?:규모|가량|상당|의)?\s*(?:매출|영업이익|순이익|실적)", piece):
        return True
    if re.search(r"전년\s*동기\s*대비\s*\d+[\d,.]*\s*%", piece):
        return True
    if re.search(r"단위\s*:\s*(?:백만원|천원|억원|원|%|주)", piece):
        return True
    return False


def business_excerpt(text, terms, limit):
    """완전한 문장/문단을 우선한다. 숫자·단어 중간을 자르지 않는다.
    재무 실적 수치 나열 문장은 제외하고 사업 모델과 제품/용도 문장만 발췌한다."""
    pieces = [v.strip() for v in re.split(r"(?<=[.!?])\s+|\n+", text) if v.strip()]
    pure_business_pieces = [p for p in pieces if not _is_financial_statement_piece(p)]
    candidates = pure_business_pieces if pure_business_pieces else pieces
    ranked = sorted(enumerate(candidates), key=lambda p: (-sum(t.casefold() in p[1].casefold() for t in terms), p[0]))
    chosen, used = [], 0
    for index, piece in ranked:
        if used + len(piece) + 1 <= limit:
            chosen.append((index, piece))
            used += len(piece) + 1
    return "\n".join(piece for _, piece in sorted(chosen))


def detailed_business_evidence(discovery, stocks, *, area=""):
    eligible = {s.code: s for s in stocks if s.selectable}
    result, counts = {}, {}
    per_section = min(1100, max(400, 6000 // max(1, len(eligible)) // 2))
    for source in getattr(discovery, 'business_sources', ()):
        if not current_business_source(source):
            continue
        stock = eligible.get(source.stock_code)
        if stock is None or stock.name != source.stock_name or counts.get(stock.code, 0) >= 2:
            continue
        text = business_excerpt(source.text, business_area_terms(area) if area else theme_terms(discovery.theme), per_section)
        if not text:
            continue
        if source.document_id.startswith('WEB_'):
            topics = list(business_area_terms(area) if area else theme_terms(discovery.theme))
            if '반도체' in topics:
                topics.extend(('semiconductor', 'DRAM', 'NAND'))
            if topics and not any(t.casefold() in (source.section_title + ' ' + text).casefold() for t in topics):
                continue  # 일반 소비재 광고·구호를 질문 테마의 사업 근거로 채택하지 않는다.
        fingerprint = hashlib.sha256((source.document_id + source.section_title + source.content_hash).encode()).hexdigest()[:12]
        key = f'BUSINESS_{stock.code}_{fingerprint}'
        result[key] = {
            'id': key, 'kind': 'company_business_section', 'status': 'ok', 'scope': 'official_business',
            'stock_code': stock.code, 'stock_name': stock.name, 'text': text, 'products': text, 'industry': '',
            'source': source.source, 'url': source.source_url, 'document_id': source.document_id,
            'document_title': source.document_title, 'section_title': source.section_title,
            'period': source.reporting_period, 'published_at': source.published_at,
            'retrieved_at': source.retrieved_at.isoformat(), 'content_hash': source.content_hash,
            'parser_revision': source.parser_revision, 'theme_terms_in_source': (), 'theme_supported': None,
            'basis_note': '공식 사업 자료의 관련 절 발췌. 발행/보고/조회 시점은 구별하며 현재 실적·수요·수혜를 입증하지 않음',
        }
        counts[stock.code] = counts.get(stock.code, 0) + 1
    return result
