"""화면과 독립적인 자료 갱신 판단 및 결과 메시지 조립."""
import re
from datetime import datetime
from src.models import AnalysisResult, AnswerBlock, ChatResponse
from src.agents.evidence import build_evidence
from src.agents.answer_quality import select_evidence
from src.agents.report_presentation import HEADLINE_SCOPE, news_sections


def needs_data(result: AnalysisResult, scope: str, text: str, period: str = "", *,
               now: datetime, dart_enabled: bool = False, messages=()) -> bool:
    from src.agents.request import is_concept_question
    if is_concept_question(text) and not any(w in text for w in ("이 종목", "현재", result.financial.stock.name)):
        return False
    from src.agents.quarterly import contextual_quarter
    quarter = contextual_quarter(text, messages)
    if quarter is not None and scope in {"all", "financials"}:
        if not dart_enabled or quarter.reason:
            return False
        if result.section_status.get("quarterly_request") != quarter.token:
            return True
        if re.search(r"PER|PBR|ROE|EPS|BPS|주가|가격|현재가", text, re.I):
            if (result.financial.collection_status == "not_collected"
                    or (now-result.financial.retrieved_at).total_seconds() > 300):
                return True
        if re.search(r"차트|추이|거래량|주가.{0,15}왜|왜.{0,15}주가", text):
            if result.price_history is None or result.price_history.status == "not_collected":
                return True
        checked_at = result.section_status.get("quarterly_checked_at")
        if checked_at:
            try:
                return (now - datetime.fromisoformat(checked_at)).total_seconds() > 900
            except (ValueError, TypeError):
                return True
        return False
    if scope == "news":
        return result.news.status == "not_collected" or (now-result.news.retrieved_at).total_seconds() > 900
    if scope == "history":
        return (bool(period and period != result.query_options.price_period)
                or result.price_history is None
                or (now-result.price_history.retrieved_at).total_seconds() > 900)
    if scope == "finance":
        return (now-result.financial.retrieved_at).total_seconds() > 300 or result.financial.collection_status == "not_collected"
    if scope == "all" and re.search(r"사도|살까|사야|담아|매수|매도|팔까|손절|물타|들어가도|투자해도", text):
        # 매수·매도 판단은 재무·뉴스·가격 맥락을 함께 근거로 삼아야 하므로 아직 수집하지 않은 구간만 보충 조회한다.
        return (result.news.status == "not_collected"
                or (dart_enabled and result.section_status.get("dart") == "not_collected"))
    if scope == "all" and re.search(r"실적|매출|영업이익|순이익|재무|이익률|마진", text):
        # 가격만 조회한 뒤 실적을 함께 묻는 후속 질문은 아직 수집하지 않은 재무 구간만 보충 조회한다.
        return dart_enabled and result.section_status.get("dart") == "not_collected"
    from src.agents.question_goal import question_goal
    if scope == "all" and question_goal(text).company_overview:
        return (result.financial.collection_status == "not_collected"
                or result.news.status == "not_collected"
                or (dart_enabled and result.section_status.get("dart") == "not_collected"))
    if scope == "financials":
        # 인증 설정이 없는 자료를 질문할 때마다 반복 호출하지 않는다.
        return dart_enabled and result.section_status.get("dart") == "not_collected"
    return False


def analysis_message(result: AnalysisResult, scope: str = "all") -> tuple[str, list[dict]]:
    response = analysis_response(result, scope)
    return response.text, response.evidence


def analysis_response(result: AnalysisResult, scope: str = "all") -> ChatResponse:
    """수집 결과와 근거를 채팅용 내용으로 조립한다. 상태를 변경하지 않는다."""
    evidence_map = build_evidence(result)
    evidence = []
    commentary = result.commentary
    summary_parts = [f"**{result.financial.stock.name} 조회 결과**"]
    blocks = []
    comparison = select_evidence("실적", [], evidence_map, []).evidence
    compared = {k: v for k, v in comparison.items() if v.get("kind") == "annual_comparison"}
    if commentary and commentary.stock_comment:
        summary_parts.append(commentary.stock_comment)
    elif compared and commentary and scope == "all":
        summary_parts.append(f"{result.financial.stock.name}의 확인된 연간 실적 변화와 주요 관련 소식을 요약해 드립니다.")
    elif compared and scope in {"all", "financials"}:
        summary_parts.append(f"{result.financial.stock.name}의 확인된 연간 실적 비교 자료를 요약해 드립니다.")
    elif commentary and scope in {"all", "news"}:
        summary_parts.append(f"{result.financial.stock.name}의 관련 뉴스와 테마 동향을 요약해 드립니다.")
    if compared and scope in {"all", "financials"}:
        labels = {"CFS": "연결재무제표", "OFS": "별도재무제표"}
        lines = [f"{labels.get(item['fs_div'], item['fs_div'])} · {item['text']}" for item in compared.values()]
        blocks.append(AnswerBlock("연간 실적", "\n\n".join(lines), tuple(compared)))
        evidence.extend(dict(item, id=key) for key, item in compared.items())
    elif result.financial.price is not None and scope in {"all", "finance"}:
        summary_parts.append("조회된 주가는 " + evidence_map["PRICE"]["value_text"] + "입니다.")
        evidence.append(dict(evidence_map["PRICE"], id="PRICE"))
    seen = {}
    if commentary:
        for label, statements in (*news_sections(commentary),
                                  ("재무 분석", () if compared else commentary.financial_commentary)):
            for statement in statements:
                if statement:
                    ids = tuple(key for key in [*(f"NEWS_{n}" for n in statement.news_ids), *(f"FACT_{n}" for n in statement.fact_ids)] if key in evidence_map)
                    if statement.text in seen:
                        index = seen[statement.text]
                        old = blocks[index]
                        blocks[index] = AnswerBlock(old.title, old.text, tuple(dict.fromkeys((*old.evidence_ids, *ids))))
                    else:
                        seen[statement.text] = len(blocks)
                        blocks.append(AnswerBlock(label, statement.text, ids))
                    for key in ids:
                        if key in evidence_map and key not in {e["id"] for e in evidence}:
                            evidence.append({"id": key, **evidence_map[key]})
    elif scope == "all":
        summary_parts.append("자료 수집 결과를 표시합니다. AI 종합 설명은 생성되지 않았습니다.")
    if any(key.startswith("NEWS_") for block in blocks for key in block.evidence_ids):
        summary_parts.append(HEADLINE_SCOPE)
    if result.ai_error and commentary is None and compared:
        summary_parts.append("AI 설명을 생성하지 못해 확인된 연간 수치를 먼저 표시합니다.")
    from src.agents.issues import fold_report_blocks
    blocks=fold_report_blocks(blocks,evidence_map)
    # 병합 시 추가된 동일 사건 근거도 원래 결과의 링크로 연결한다.
    for block in blocks:
        for key in block.evidence_ids:
            if key in evidence_map and key not in {item['id'] for item in evidence}:
                evidence.append(dict(evidence_map[key],id=key))
    return ChatResponse("\n\n".join(summary_parts), evidence, blocks=tuple(blocks),
                        lead_evidence_ids=tuple(e["id"] for e in evidence if e["id"] == "PRICE"))
