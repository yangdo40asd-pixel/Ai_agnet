"""기업별 사업 카드 UI 컴포넌트 (02-D).

검증된 카드 데이터와 허용된 동작(실적 보기, 출처 보기)만 표시한다.
금융 계산·자료 조회·LLM 호출은 일체 발생시키지 않으며,
출처는 가벼운 st.popover를 사용하여 저장된 근거만 즉시 표시한다.
"""
import re
import streamlit as st

from src.data.news import safe_news_url
from src.ui.answer import evidence_metadata, escaped, _reference_marks
from src.ui.state import select_candidate


ROLE_LABELS = {
    "summary": "사업 개요",
    "business": "주요 제품 및 사업 내용",
    "theme": "테마 연관 근거",
    "difference": "사업상 차별점",
}


def render_company_card(
    card: dict,
    message: dict,
    numbers: dict,
    key_prefix: str = "card",
) -> None:
    """단일 기업 카드를 네이티브 container 안에 정돈된 레이아웃으로 렌더링한다."""
    stock_code = str(card.get("stock_code") or "").strip()
    stock_name = str(card.get("stock_name") or "").strip()
    sections = card.get("sections") or ()
    refs = {e["id"]: e for e in message.get("evidence", ())}

    with st.container(border=True):
        # 상단 기업명 및 종목 코드
        col_name, col_code = st.columns([3, 1])
        with col_name:
            st.markdown(f"### {escaped(stock_name)}")
        with col_code:
            st.caption(f"`{escaped(stock_code)}`")

        # 섹션별 사업 설명 렌더링
        for sec in sections:
            role = sec.get("role", "summary")
            sec_text = str(sec.get("text") or "").strip()
            sec_ids = sec.get("evidence_ids") or ()
            marks = _reference_marks(sec_ids, numbers)
            annotated_text = sec_text + (f" {marks}" if marks else "")

            if role in ROLE_LABELS and role != "summary":
                st.caption(ROLE_LABELS[role])
            st.markdown(annotated_text, unsafe_allow_html=False)

        # 하단 액션 버튼 행: [실적 보기] 및 [출처 n개]
        card_key = f"{key_prefix}_{stock_code}"
        col_act, col_pop = st.columns([1, 1])
        with col_act:
            selected_code = st.session_state.get("selected_code")
            is_selected = (selected_code == stock_code)
            btn_label = f"{stock_name} 실적 확인됨" if is_selected else f"{stock_name} 실적 보기"
            btn_key = (
                f"msg_select_{stock_code}"
                if key_prefix.startswith("msg_select")
                else f"{card_key}_analyze"
            )
            st.button(
                btn_label,
                key=btn_key,
                disabled=is_selected,
                on_click=select_candidate,
                args=(st.session_state, stock_code),
            )

        with col_pop:
            sec_eids = list(dict.fromkeys(
                eid for sec in sections for eid in sec.get("evidence_ids", ()) if eid in refs
            ))
            if sec_eids:
                with st.popover(f"출처 {len(sec_eids)}개", key=f"{card_key}_popover"):
                    st.markdown(f"**{escaped(stock_name)} 관련 출처**")
                    for eid in sec_eids:
                        item = refs[eid]
                        src_label = str(item.get("source") or "공식 사업 자료")
                        scope_desc = (
                            "상장법인목록 등록 정보"
                            if item.get("kind") == "company_profile"
                            else "공식 사업 원문 발췌"
                        )
                        st.markdown(f"**{escaped(src_label)}** · {scope_desc}")
                        if item.get("url"):
                            safe_url = safe_news_url(item["url"])
                            if safe_url:
                                st.link_button(
                                    "원문 링크 열기",
                                    safe_url,
                                    key=f"{card_key}_{eid}_url",
                                )
                        if item.get("text"):
                            st.caption(escaped(item["text"]))
                        meta = evidence_metadata(item)
                        if meta:
                            st.caption(escaped(meta))
                        st.divider()
            else:
                st.caption("확인된 별도 출처 없음")


def render_company_cards_section(
    message: dict,
    numbers: dict,
    key_prefix: str = "cards",
) -> None:
    """메시지에 포함된 모든 기업 카드를 순서대로 렌더링한다."""
    cards = message.get("company_cards") or ()
    for card in cards:
        render_company_card(
            card,
            message,
            numbers,
            key_prefix=key_prefix,
        )
