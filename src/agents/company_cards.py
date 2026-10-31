"""기업별 사업 카드 계약 검증, 근거 소유권 대조, 대체 카드 구성.

뉴스 이슈 카드의 독립 사건/개수 규칙을 침범하지 않으며,
각 카드의 설명 항목에는 해당 기업이 소유한 근거 ID만 연결한다.
"""
import re
from src.models import AppError, ChatResponse, CompanyCard, CompanyCardSection
from src.agents.chat import validate_answer


ALLOWED_ROLES = {"summary", "business", "theme", "difference"}


def _source_doc_label(item: dict) -> str:
    """근거 메타데이터를 기반으로 공식 출처 종류를 정확히 표기한다."""
    doc_id = str(item.get("document_id") or "")
    source = str(item.get("source") or "")
    if "홈페이지" in source or doc_id.startswith("WEB_"):
        return "공식 홈페이지 자료"
    if "보고서" in source or doc_id.startswith("DART_"):
        return "공식 사업 보고서"
    return "공식 사업 자료"


def validate_company_cards(payload: dict, evidence: dict[str, dict], candidates: tuple = (), question: str = "", theme: str = "") -> ChatResponse:
    """기업 카드 응답의 스키마·기업별 근거 소유권·공통 문체/수치를 검증한다."""
    if not isinstance(payload, dict) or set(payload) not in (
        {"text", "evidence_ids", "follow_up"},
        {"text", "evidence_ids", "follow_up", "company_cards"},
    ):
        raise AppError("chat_answer", "기업 카드 응답 형식을 확인하지 못했습니다.")

    # candidates는 카드 검증에 필수적이며 비어있으면 안 됨
    if not candidates:
        raise AppError("company_card_candidates", "기업 카드 대상 후보 목록이 누락되었습니다.")

    candidate_lookup = {s.code: s for s in candidates if getattr(s, "code", None)}
    if not candidate_lookup:
        raise AppError("company_card_candidates", "기업 카드 대상 후보가 올바르지 않습니다.")

    raw_cards = payload.get("company_cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        raise AppError("chat_answer", "기업 카드 목록 형식이 올바르지 않습니다.")

    # 종목 코드 중복 및 누락 여부 검사
    card_codes = []
    for c in raw_cards:
        if not isinstance(c, dict):
            raise AppError("company_card_format", "기업 카드 형식이 올바르지 않습니다.")
        c_code = c.get("stock_code")
        if not isinstance(c_code, str) or not c_code.strip():
            raise AppError("company_card_code", "기업 카드의 종목 코드가 누락되었습니다.")
        card_codes.append(c_code.strip())

    if len(card_codes) != len(set(card_codes)):
        raise AppError("company_card_duplicate", "중복된 종목 카드가 있습니다.")
    if set(card_codes) != set(candidate_lookup):
        raise AppError("company_card_mismatch", "기업 카드 대상이 요청된 후보와 일치하지 않습니다.")

    # 도입부 유효성 검사
    intro_payload = {
        "text": payload.get("text"),
        "evidence_ids": payload.get("evidence_ids"),
        "follow_up": payload.get("follow_up", ""),
    }
    intro, used = validate_answer(intro_payload, evidence, theme=theme, question=question)

    # 도입부의 근거 없는 '전문/핵심/주력/특화/집중' 과장 수식어 검사
    intro_corpus = " ".join(
        str(evidence[eid].get("text", "")) + " " + str(evidence[eid].get("products", ""))
        for eid in intro_payload.get("evidence_ids", ()) if eid in evidence
    )
    for m in re.finditer(r"(?:^|[^\w가-힣])(핵심|주력|특화|전문|집중)(?:기업|업체|역할|으로|사업|제품)?", intro):
        term = m.group(1)
        if term not in intro_corpus:
            raise AppError("chat_claim", f"도입부에 원문에 없는 '{term}' 표현을 사용했습니다.")

    seen_sentences = set()
    for s in re.split(r"[.!?。！？\n]+", intro):
        s = s.strip()
        if len(s) > 8:
            seen_sentences.add(re.sub(r"\W", "", s))

    cards = []
    seen_texts = {re.sub(r"\W", "", intro)}

    for card_data in raw_cards:
        if set(card_data) - {"stock_code", "stock_name", "sections"}:
            raise AppError("company_card_format", "기업 카드에 허용되지 않은 필드가 있습니다.")

        code = card_data["stock_code"].strip()
        stock_name = candidate_lookup[code].name
        if "stock_name" in card_data and card_data["stock_name"] != stock_name:
            raise AppError("company_card_name_mismatch", f"기업명이 후보 기업명({stock_name})과 일치하지 않습니다.")

        raw_sections = card_data.get("sections")
        if not isinstance(raw_sections, list) or not (1 <= len(raw_sections) <= 4):
            raise AppError("company_card_sections", "기업 카드 항목 수는 1~4개여야 합니다.")

        sections = []
        seen_roles = set()
        card_sentences = set()

        for sec in raw_sections:
            if not isinstance(sec, dict):
                raise AppError("company_card_sections", "항목 데이터 형식이 올바르지 않습니다.")
            if set(sec) - {"role", "text", "evidence_ids"}:
                raise AppError("company_card_sections", "카드 항목에 허용되지 않은 필드가 있습니다.")

            role = sec.get("role")
            if not isinstance(role, str) or role not in ALLOWED_ROLES:
                raise AppError("company_card_role", f"허용되지 않은 카드 역할입니다: {role}")
            if role in seen_roles:
                raise AppError("company_card_role_duplicate", f"동일 역할이 중복되었습니다: {role}")
            seen_roles.add(role)

            text = sec.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                raise AppError("company_card_text", "카드 항목 내용이 비어 있거나 너무 깁니다.")
            text = text.strip()

            sec_ids = sec.get("evidence_ids")
            if not isinstance(sec_ids, (list, tuple)) or len(sec_ids) > 16:
                raise AppError("company_card_evidence", "카드 항목 근거 수가 올바르지 않습니다.")

            # 모든 근거 ID가 비어있지 않은 문자열인지 확인 (TypeError 사전 방지)
            if any(not isinstance(eid, str) or not eid.strip() for eid in sec_ids):
                raise AppError("company_card_evidence", "근거 ID 형식이 올바르지 않습니다.")

            if len(sec_ids) != len(set(sec_ids)):
                raise AppError("company_card_evidence", "카드 항목에 중복된 근거 ID가 있습니다.")

            # 기업별 근거 소유권 엄격 대조 (크로스 인용 금지, 소유자 없는 근거 금지)
            for eid in sec_ids:
                if eid not in evidence:
                    raise AppError("company_card_evidence", f"존재하지 않는 근거 ID입니다: {eid}")
                ev_code = evidence[eid].get("stock_code")
                if not ev_code or ev_code != code:
                    raise AppError("company_card_evidence_ownership",
                                   f"다른 기업 또는 소유자 없는 근거({eid})를 {code} 카드에 인용할 수 없습니다.")

            # 공통 문체 및 수치 검증
            checked_text, _ = validate_answer(
                {"text": text, "evidence_ids": list(sec_ids), "follow_up": ""},
                evidence,
                theme=theme,
                question=question,
            )

            # 원문에 없는 '전문/주력/핵심/특화/집중' 과장 수식어 검사
            cited_corpus = " ".join(
                str(evidence[eid].get("text", "")) + " " + str(evidence[eid].get("products", ""))
                for eid in sec_ids if eid in evidence
            )
            for m in re.finditer(r"(?:^|[^\w가-힣])(핵심|주력|특화|전문|집중)(?:기업|업체|역할|으로|사업|제품)?", checked_text):
                term = m.group(1)
                if term not in cited_corpus:
                    raise AppError("chat_claim", f"원문에 없는 '{term}' 표현으로 사업 역할을 과장했습니다.")

            text_key = re.sub(r"\W", "", checked_text)
            if text_key in seen_texts:
                raise AppError("chat_directness", "카드 항목 설명이 본문이나 다른 카드와 중복되었습니다.")
            seen_texts.add(text_key)

            # 문장 단위 반복 대조 (도입부 및 동일 카드 내 중복 방지)
            for s in re.split(r"[.!?。！？\n]+", checked_text):
                s = s.strip()
                if len(s) > 8:
                    s_key = re.sub(r"\W", "", s)
                    if s_key in seen_sentences:
                        raise AppError("chat_directness", "카드 항목 설명이 도입부나 다른 항목과 중복되었습니다.")
                    if s_key in card_sentences:
                        raise AppError("chat_directness", "동일 카드 내에서 같은 문장을 반복했습니다.")
                    seen_sentences.add(s_key)
                    card_sentences.add(s_key)

            sections.append(CompanyCardSection(role=role, text=checked_text, evidence_ids=tuple(sec_ids)))

        cards.append(CompanyCard(stock_code=code, stock_name=stock_name, sections=tuple(sections), card_id=f"CARD_{code}"))

    # 전체 사용된 근거 수집
    all_used_ids = list(dict.fromkeys(
        list(payload.get("evidence_ids", [])) +
        [eid for card in cards for s in card.sections for eid in s.evidence_ids]
    ))
    used_evidence = [dict(evidence[eid], id=eid) for eid in all_used_ids if eid in evidence]

    response = ChatResponse(
        intro=intro,
        evidence=used_evidence,
        follow_up=payload.get("follow_up", ""),
        company_cards=tuple(cards),
        lead_evidence_ids=tuple(payload.get("evidence_ids", ())),
    )
    if len(response.text) > 4000:
        raise AppError("chat_answer", "기업 카드 전체 답변이 너무 깁니다.")
    return response


def build_fallback_cards(discovery, evidence: dict[str, dict], stocks: tuple, compact: bool = False) -> tuple[CompanyCard, ...]:
    """확보된 사업 근거와 KIND 목록으로 검증된 대체 기업 카드를 구성한다."""
    cards = []
    for stock in stocks:
        stock_evidence = [e for e in evidence.values() if e.get("stock_code") == stock.code]
        if not stock_evidence:
            sec = CompanyCardSection(
                role="summary",
                text=f"{stock.name}의 상세 공식 사업 정보는 이번 조회에서 확보되지 않았습니다.",
                evidence_ids=(),
            )
            cards.append(CompanyCard(stock_code=stock.code, stock_name=stock.name, sections=(sec,), card_id=f"CARD_{stock.code}"))
            continue

        profile_item = next((e for e in stock_evidence if e.get("kind") == "company_profile"), None)
        business_item = next((e for e in stock_evidence if e.get("kind") == "company_business_section"), None)

        sections = []
        if profile_item:
            ind = (profile_item.get("industry") or "").strip()
            prod = (profile_item.get("products") or "").strip()
            parts = []
            if ind:
                parts.append(f"등록 업종은 {ind}")
            if prod:
                # 완결된 제품 항목 단위로 선택하여 단어/문장 중간 절단 방지
                prod_items = [p.strip() for p in re.split(r"[,/]", prod) if p.strip()]
                kept = []
                cur_len = 0
                for item in prod_items:
                    if cur_len + len(item) + 2 <= 200:
                        kept.append(item)
                        cur_len += len(item) + 2
                    else:
                        break
                prod_str = ", ".join(kept)
                if len(kept) < len(prod_items):
                    prod_str += " 등"
                parts.append(f"주요 제품은 {prod_str}")
            summary_body = f"{stock.name}의 " + "이며, ".join(parts) + "입니다." if parts else f"{stock.name}의 공식 등록 사업 정보입니다."
            sec_id = profile_item["id"]
        elif business_item:
            b_text = business_item.get("products") or business_item.get("text") or ""
            raw_pieces = [v.strip() for v in re.split(r"(?<=[.!?])\s+|\n+", b_text) if v.strip()]
            unique_pieces = []
            seen_raw = set()
            for p in raw_pieces:
                p_key = re.sub(r"\W", "", p)
                if p_key and p_key not in seen_raw:
                    seen_raw.add(p_key)
                    unique_pieces.append(p)
            clean_b_text = " ".join(unique_pieces)

            from src.agents.business_context import business_excerpt
            # 400자 한도로 충분히 긴 정상 단일 문장(예: 196자)을 온전히 수용
            excerpt = business_excerpt(clean_b_text, (), 400)
            if not excerpt and unique_pieces:
                first_sent = unique_pieces[0]
                excerpt = first_sent if len(first_sent) <= 400 else first_sent[:380].rsplit(" ", 1)[0] + "..."
            if not excerpt:
                excerpt = "사업 원문이 확인되었습니다."

            if compact:
                excerpt = re.split(r'(?<=[.!?])\s+', excerpt)[0].strip()
            summary_body = f"{stock.name}의 {_source_doc_label(business_item)} 발췌: {excerpt}"
            sec_id = business_item["id"]
        else:
            summary_body = f"{stock.name}의 확인된 사업 내용입니다."
            sec_id = stock_evidence[0]["id"]

        sections.append(CompanyCardSection(role="summary", text=summary_body, evidence_ids=(sec_id,)))

        if not compact:
            if business_item and profile_item:
                b_text = business_item.get("products") or business_item.get("text") or ""
                raw_pieces = [v.strip() for v in re.split(r"(?<=[.!?])\s+|\n+", b_text) if v.strip()]
                unique_pieces = []
                seen_raw = set()
                for p in raw_pieces:
                    p_key = re.sub(r"\W", "", p)
                    if p_key and p_key not in seen_raw:
                        seen_raw.add(p_key)
                        unique_pieces.append(p)
                clean_b_text = " ".join(unique_pieces)

                from src.agents.business_context import business_excerpt
                excerpt = business_excerpt(clean_b_text, (), 400)
                if not excerpt and unique_pieces:
                    excerpt = unique_pieces[0][:400]
                if excerpt and excerpt != profile_item.get("products"):
                    sections.append(CompanyCardSection(
                        role="business",
                        text=f"{_source_doc_label(business_item)} 발췌: {excerpt}",
                        evidence_ids=(business_item["id"],),
                    ))

            theme_item = next((e for e in stock_evidence if e.get("theme_supported") is True), None)
            if theme_item:
                sections.append(CompanyCardSection(
                    role="theme",
                    text=f"확인된 사업 원문에서 {discovery.theme} 관련 어휘가 확인되었습니다.",
                    evidence_ids=(theme_item["id"],),
                ))

        # 섹션 간 중복 문장 필터링
        seen_sents = set()
        clean_sections = []
        for s in sections:
            s_key = re.sub(r"\W", "", s.text)
            if s_key in seen_sents:
                continue
            seen_sents.add(s_key)
            clean_sections.append(s)

        cards.append(CompanyCard(stock_code=stock.code, stock_name=stock.name, sections=tuple(clean_sections), card_id=f"CARD_{stock.code}"))
    return tuple(cards)
