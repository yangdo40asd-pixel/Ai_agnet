"""검증된 답변 블록·출처·서로 다른 시각을 화면에 표시한다."""
from dataclasses import asdict
from datetime import datetime
import re
from urllib.parse import urlparse

import streamlit as st

from src.data.news import safe_news_url
from src.models import ChatResponse
from src.agents.report_presentation import HEADLINE_SCOPE

DISCLAIMER_TEXT = "⚠️ 투자 유의사항: 본 정보는 수집된 공시·시세 및 뉴스 제목 기준의 참고 자료이며 특정 종목의 매수·매도 추천이나 투자 권유가 아닙니다."


def clean_display_lead(text: str) -> str:
    """본문 상단에 노출되던 기계적 범위 경고문을 제거해 하단 접이식 안내로 일원화한다."""
    cleaned = str(text or "")
    for prefix in (HEADLINE_SCOPE, "수집된 뉴스 제목 기준입니다."):
        cleaned = re.sub(r"(?:^|\n\n)" + re.escape(prefix) + r"[ \t]*", "\n\n", cleaned)
    cleaned = re.sub(r"\{\{[A-Z0-9_a-z-]+\}\}", "", cleaned)
    cleaned = re.sub(r"(?m)^[-–—*•]\s*", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def follow_up_suggestions(message: dict) -> list[str]:
    """나무증권 N2 스타일의 후속 추천 질문 칩 목록을 반환한다."""
    suggestions = []
    follow = str(message.get("follow_up") or "").strip()
    if follow:
        suggestions.append(follow)
    target = str(message.get("target") or "").strip()
    prefix = f"{target} " if target and target not in {"일반 설명", "후보 탐색"} else ""
    for item in (f"{prefix}최근 실적이 좋아졌어?", f"{prefix}PER은 어떤 편이야?", f"{prefix}최근 주요 이슈 요약해 줘"):
        if item not in suggestions:
            suggestions.append(item)
    return suggestions[:3]


def escaped(value) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", str(value))


def time_label(value) -> str:
    if isinstance(value, str):
        try:
            if re.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", value):
                return datetime.strptime(value.replace('-', ''), '%Y%m%d').date().isoformat()
            value = datetime.fromisoformat(value)
        except ValueError:
            pass
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds").replace("T", " ")
    return str(value or "미확인")


def response_fields(response) -> dict:
    """세션에는 데이터만 저장한다. 이전 세 값 반환도 표시할 수 있다."""
    if not isinstance(response, ChatResponse):
        return {}
    res = {"intro": response.intro, "blocks": [asdict(b) for b in response.blocks],
           "lead_evidence_ids": response.lead_evidence_ids,
           **({'notices':response.notices} if response.notices else {})}
    if getattr(response, "company_cards", None):
        res["company_cards"] = [asdict(c) for c in response.company_cards]
    return res


def evidence_metadata(item: dict) -> str:
    fields = [("제공자", item.get("source"))]
    if item.get("scope") == "company_profile":
        fields.append(("확인 범위", "상장법인목록의 업종·주요제품"))
    if item.get("scope") == "official_business":
        fields.extend((("확인 범위", "공식 사업 자료의 관련 절 발췌"),
                       ("문서", item.get("document_title")), ("절", item.get("section_title")),
                       ("발행/접수", time_label(item.get("published_at")))))
    if item.get("scope") in {"headline_only","article_excerpt","official_disclosure"}:
        label={'headline_only':'뉴스 제목 기반','article_excerpt':'뉴스 제목·검색 발췌','official_disclosure':'공식 공시 원문'}[item['scope']]
        publication_label = "공시 접수" if item['scope'] == 'official_disclosure' else "기사 발행"
        fields.extend((("확인 범위", label), (publication_label, time_label(item.get("published_at")))))
    elif item.get("id") in {"PRICE", "PER", "PBR", "EPS", "BPS", "ROE"}:
        fields.append(("자료 기준", item.get("as_of") or "자료 기준 시각 미확인"))
    if item.get("period"):
        fields.append(("보고·산정 기간", item["period"]))
    if item.get("fs_div"):
        fields.append(("재무 기준", {"CFS": "연결", "OFS": "별도"}.get(item["fs_div"], item["fs_div"])))
    if item.get("formula"):
        fields.append(("산식", item["formula"]))
    fields.append(("조회 시각", time_label(item.get("retrieved_at"))))
    return " · ".join(f"{name}: {value}" for name, value in fields if value)


def source_groups(message: dict):
    """답변 안의 표시 번호를 원본 근거 ID에 연결한다. 원본 자료는 보존한다."""
    refs = {e["id"]: e for e in message.get("evidence", ())}
    blocks = message.get("blocks") or ()
    company_cards = message.get("company_cards") or ()
    card_ids = [i for card in company_cards for sec in card.get("sections", ()) for i in sec.get("evidence_ids", ())]
    has_structured = bool(blocks or company_cards or message.get("lead_evidence_ids"))
    ids = (list(message.get("lead_evidence_ids", ())) +
           [i for block in blocks for i in block.get("evidence_ids", ())] +
           card_ids) if has_structured else list(refs)
    groups, by_identity, numbers = [], {}, {}
    for key in dict.fromkeys(ids):
        if key not in refs:
            continue
        item = refs[key]
        url = safe_news_url(item.get("url"))
        identity = ("url", url) if url else ("news",key) if key.startswith('NEWS_') else ("data", item.get("source"), item.get("period"), item.get("fs_div"), item.get("stock_code"))
        if identity not in by_identity:
            by_identity[identity] = len(groups) + 1
            groups.append({"number": len(groups) + 1, "url": url, "items": []})
        number = by_identity[identity]
        numbers[key] = number
        groups[number - 1]["items"].append(item)
        for proof in item.get('relationship_proofs',()):
            proof_url=safe_news_url(proof.get('source_url'))
            proof_identity=('url',proof_url) if proof_url else ('relation',proof.get('fact_id'))
            if proof_identity not in by_identity:
                by_identity[proof_identity]=len(groups)+1
                groups.append({'number':len(groups)+1,'url':proof_url,'items':[{
                    'id':proof.get('fact_id'),'text':proof.get('quote','관계 확인 자료'),
                    'source':proof.get('source'),'scope':'official_disclosure',
                    'published_at':proof.get('published_at'),'retrieved_at':proof.get('retrieved_at')}]})
    return groups, numbers


def _reference_marks(ids, numbers):
    return " ".join(f"[{n}]" for n in dict.fromkeys(numbers[k] for k in ids if k in numbers))


def render_sources(groups, *, scope_notice: bool = False):
    if not groups and not scope_notice:
        return
    if groups:
        st.caption("출처")
        for group in groups:
            item = group["items"][0]
            label = f"[{group['number']}] " + str(item.get("source") or "자료 출처")
            if group["url"]:
                source_title = "기업별 업종·주요제품" if item.get("kind") == "company_profile" else item["text"]
                st.link_button(label + " · " + source_title, group["url"])
            else:
                from src.source_presentation import data_source_label
                label = f"[{group['number']}] " + data_source_label(item)
                st.caption(escaped(label))
    with st.expander("출처 상세 · 기준과 조회 시각", expanded=False):
        for group in groups:
            for item in group["items"]:
                st.caption(escaped(f"[{group['number']}] {item.get('text', '')}"))
                st.caption(escaped(evidence_metadata(item)))
        if scope_notice:
            st.caption(escaped(HEADLINE_SCOPE))
        st.caption(escaped(DISCLAIMER_TEXT))


def render_follow_up_chips(message: dict, key_prefix: str = "chip") -> str | None:
    """답변 하단에 후속 추천 질문 칩을 가로로 렌더링하고 클릭된 질문을 반환한다."""
    chips = follow_up_suggestions(message)
    if not chips:
        return None
    cols = st.columns(len(chips))
    clicked = None
    for idx, (col, prompt) in enumerate(zip(cols, chips)):
        if col.button(prompt, key=f"{key_prefix}_{idx}"):
            clicked = prompt
    return clicked


def render_answer(message: dict, key_prefix: str = "") -> None:
    groups, numbers = source_groups(message)
    blocks = message.get("blocks") or ()
    company_cards = message.get("company_cards") or ()
    raw_intro = message.get("intro", "")
    raw_text = message.get("text", "")
    has_scope_notice = (
        HEADLINE_SCOPE in raw_intro
        or HEADLINE_SCOPE in raw_text
        or "수집된 뉴스 제목 기준입니다." in raw_intro
        or "수집된 뉴스 제목 기준입니다." in raw_text
        or any(item.get("scope") == "headline_only" for item in message.get("evidence", ()))
    )
    if company_cards:
        if raw_intro:
            marks = _reference_marks(message.get("lead_evidence_ids", ()), numbers)
            lead = clean_display_lead(raw_intro)
            st.markdown(lead + (" " + marks if marks else ""), unsafe_allow_html=False)
        from src.ui.company_cards import render_company_cards_section
        card_prefix = key_prefix or f"card_{re.sub(r'\W', '_', str(message.get('request_id') or message.get('sent_at') or 'default'))}"
        render_company_cards_section(message, numbers, key_prefix=card_prefix)
    elif blocks:
        marks = _reference_marks(message.get("lead_evidence_ids", ()), numbers)
        lead = clean_display_lead(raw_intro)
        st.markdown(lead + (" " + marks if marks else ""), unsafe_allow_html=False)
        for block in blocks:
            with st.container(border=True):
                st.markdown("#### " + escaped(block.get('title',block.get('headline',''))))
                marks = _reference_marks(block["evidence_ids"], numbers)
                st.markdown(block.get('text',block.get('summary','')) + (" " + marks if marks else ""), unsafe_allow_html=False)
                if block.get('implication'):
                    st.caption('해석')
                    st.markdown(block['implication'],unsafe_allow_html=False)
                refs={e['id']:e for e in message.get('evidence',())}
                badges={}
                for key in block['evidence_ids']:
                    url=safe_news_url(refs.get(key,{}).get('url'))
                    if url:
                        badges[url]=urlparse(url).hostname
                if badges:
                    st.caption(' · '.join('['+escaped(domain)+'](<'+url+'>)' for url,domain in badges.items()))
    else:
        lead = clean_display_lead(raw_text)
        st.markdown(lead, unsafe_allow_html=False)
    for notice in message.get('notices',()):
        st.caption(escaped(notice))
    if not company_cards:
        render_sources(groups, scope_notice=has_scope_notice)
    else:
        st.caption(escaped(DISCLAIMER_TEXT))
