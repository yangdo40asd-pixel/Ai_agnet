"""대화 의도 분류와 현재 선택 종목 자료에 근거한 후속 답변."""

import re
import datetime
from src.agents.request import (ChatIntent, route_message, discovery_theme, is_explicit_search,
                                prefers_dialogue, company_to_lookup, is_concept_question, is_evaluation_question)

def is_theme_search(text, has_discovery=False):
    return is_explicit_search(text)

from pathlib import Path
from dataclasses import replace

from src.agents.transport import CHAT_TEMPERATURE, _invoke
from src.agents.evidence import build_evidence
from src.agents.answer_quality import QUALITY_CHECKS, answer_context, select_evidence, model_evidence, failed_checks, review_units, failed_unit_reviews
from src.agents.report import asserts_valuation, wrong_per_formula
from src.agents.knowledge import TERMS, concept_answer, TRADING_CONCEPTS, MECHANISM_CONCEPTS, verified_metric_explanation
from src.config import Settings
from src.models import AnalysisResult, AppError, CandidateDiscoveryResult, resolve_roe_metric, AnswerBlock, ChatResponse
from src.agents.presentation import parse_presentation, sentences, enforce_presentation, attribute_reported_news, enforce_single_margin_change, deduplicate_margin_note, normalize_metric_subject
from src.agents.issues import group_issues, card_groups, validate_issue_cards
from src.agents.interpretation import GENERATION_POLICY as INTERPRETATION_POLICY

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 8000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def prepare_submission(raw_text: str, files: list[tuple[str, bytes]] | None = None) -> tuple[str, str, list[dict]]:
    """빈 제출, 첨부만 있는 제출, 일반 메시지를 외부 호출 전에 구분한다."""
    attachments = normalize_attachments(list(files or []))
    text = " ".join(str(raw_text or "").split())
    if not text and not attachments:
        return "empty", "", []
    if not text:
        return "attachment_only", "", attachments
    return "message", normalize_message(text), attachments


def normalize_message(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise AppError("chat_empty", "테마를 입력하거나 궁금한 내용을 질문해 주세요.")
    if len(text) > 1200:
        raise AppError("chat_length", "질문은 1,200자 이내로 입력해 주세요.")
    return text


def _compress_history_text(text: str) -> str:
    """2턴 이전의 긴 대화는 핵심 첫 문장 중심으로 압축해 4K 문맥 예산을 보호한다."""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= 180:
        return cleaned
    first_sentence = re.split(r"(?<=[.!?。！？])\s+", cleaned, maxsplit=1)[0]
    if 10 <= len(first_sentence) <= 180:
        return first_sentence
    return cleaned[:177] + "..."


def _message_target_code(message: dict) -> str | None:
    report = message.get("report")
    if report is not None and getattr(report, "target_code", None):
        return str(report.target_code)
    target = message.get("result_target")
    if isinstance(target, dict) and target.get("code"):
        return str(target["code"])
    return None


def _current_stock_messages(messages: list[dict] | None, result: AnalysisResult | None) -> list[dict]:
    """다른 종목으로 전환한 뒤 이전 종목의 대화 턴이 현재 종목 문맥에 섞이지 않게 분리한다."""
    items = list(messages or [])
    if result is None or not items:
        return items
    target_code = str(result.target_code)
    tagged_codes = [_message_target_code(m) for m in items]
    if not any(code is not None and code != target_code for code in tagged_codes):
        return items
    filtered = []
    for idx, msg in enumerate(items):
        code = tagged_codes[idx]
        if code is None and msg.get("role") == "user" and idx + 1 < len(items):
            code = tagged_codes[idx + 1]
        if code is not None and code != target_code:
            continue
        filtered.append(msg)
    return filtered


def conversation_context(messages: list[dict], result: AnalysisResult | None = None) -> list[dict]:
    # 오래된 답변의 수치/리포트 객체는 전달하지 않는다. 사실 근거는 현재 결과만 쓴다.
    scoped = _current_stock_messages(messages, result)
    recent = [m for m in scoped[-12:] if m.get("role") in {"user", "assistant"}]
    context = []
    for idx, message in enumerate(recent):
        text = str(message.get("text", ""))[:1200]
        is_latest_turn = idx >= len(recent) - 2
        report = message.get("report")
        if is_latest_turn and report and report.commentary and (result is None or getattr(report, "target_code", None) == result.target_code):
            commentary = report.commentary
            statements = [*commentary.theme_trend, commentary.opportunity,
                          commentary.risk, commentary.summary, *commentary.financial_commentary]
            text += "\n" + commentary.stock_comment + "\n" + "\n".join(s.text for s in statements if s)
        elif not is_latest_turn:
            text = _compress_history_text(text)
        context.append({"role": message["role"], "text": text[:1000]})
    return context


def infer_implicit_metrics(text: str, messages: list[dict] | None) -> list[str]:
    """주어·지표명이 생략된 후속 평가 질문에서 직전 대화의 지표를 승계한다."""
    if not messages:
        return []
    if re.search(r"뉴스|기사|이슈|실적|매출|영업이익|순이익|재무|차트|거래량|주가|현재가", text):
        return []
    if not (is_evaluation_question(text) or re.search(r"^(?:그럼|그러면|그렇다면|그건|이건)|그\s*지표|해석", text)):
        return []
    for msg in reversed(messages[-4:]):
        found = list(dict.fromkeys(re.findall(r"(?<![A-Z])(?:PER|PBR|ROE|EPS|BPS)(?![A-Z])", str(msg.get("text", "")).upper())))
        if found:
            return found
    return []


def recover_evidence_ids(payload: dict, evidence: dict[str, dict]) -> dict:
    """중복된 evidence_ids를 정규화하고 본문 자리표시자·검증된 연간 비교의 근거 ID를 복원한다."""
    if not isinstance(payload, dict):
        return payload
    updated = dict(payload)
    text = str(updated.get("text", ""))
    if isinstance(updated.get("evidence_ids"), list) and all(isinstance(i, str) for i in updated["evidence_ids"]):
        ids = list(dict.fromkeys(updated["evidence_ids"]))
        for placeholder in re.findall(r"\{\{([A-Z0-9_a-z-]+)\}\}", text):
            if placeholder in evidence and placeholder not in ids:
                ids.append(placeholder)
        from src.agents.financial_numbers import comparison_source_ids
        ids.extend(key for key in comparison_source_ids(text, evidence) if key not in ids)
        if "NEWS_STATUS" in evidence and "NEWS_STATUS" not in ids and re.search(r"뉴스|기사", text):
            ids.append("NEWS_STATUS")
        for k in evidence:
            if k.startswith("NEWS_") and k != "NEWS_STATUS" and k not in ids:
                news_title = str(evidence[k].get("text", ""))
                title_words = [w for w in re.split(r"[\s,·\-_/]+", news_title) if len(w) >= 2]
                if any(w in text for w in title_words[:5]):
                    ids.append(k)
        has_income_evidence = any("OPERATING_INCOME" in k or "operating_income" in k for k in ids)
        if not has_income_evidence and re.search(r"영업이익|영업손익", text):
            cmp_income = next((k for k in evidence if "CMP_" in k and "OPERATING_INCOME" in k), None)
            if cmp_income and cmp_income not in ids:
                ids.append(cmp_income)
            else:
                fin_income = next((k for k in evidence if "OPERATING_INCOME" in k), None)
                if fin_income and fin_income not in ids:
                    ids.append(fin_income)

        has_revenue_evidence = any("REVENUE" in k or "revenue" in k for k in ids)
        if not has_revenue_evidence and re.search(r"매출", text):
            cmp_rev = next((k for k in evidence if "CMP_" in k and "REVENUE" in k), None)
            if cmp_rev and cmp_rev not in ids:
                ids.append(cmp_rev)
            else:
                fin_rev = next((k for k in evidence if "REVENUE" in k), None)
                if fin_rev and fin_rev not in ids:
                    ids.append(fin_rev)
        updated["evidence_ids"] = ids
    if isinstance(updated.get("blocks"), list):
        new_blocks = []
        for block in updated["blocks"]:
            if isinstance(block, dict) and isinstance(block.get("evidence_ids"), list) and all(isinstance(i, str) for i in block["evidence_ids"]):
                b_ids = list(dict.fromkeys(block["evidence_ids"]))
                for placeholder in re.findall(r"\{\{([A-Z0-9_a-z-]+)\}\}", str(block.get("text", ""))):
                    if placeholder in evidence and placeholder not in b_ids:
                        b_ids.append(placeholder)
                block = {**block, "evidence_ids": b_ids}
            new_blocks.append(block)
        updated["blocks"] = new_blocks
    return updated


MECHANISM_QUESTION = re.compile(
    r"(?:줄면|늘면|오르면|내리면|떨어지면|감소하면|증가하면|높아지면|낮아지면|커지면|작아지면).*(?:그만큼|같은\s*(?:비율|폭)|비례|똑같이|그대로|도\s*(?:감소|증가|줄|늘|오르|내리|떨어|커|작))")


_WON_PARTICLES = {"와": "과", "가": "이", "를": "을", "는": "은", "로": "으로"}


def fix_won_particles(text: str) -> str:
    """금액이 '원'으로 끝난 뒤의 받침 있는 조사를 바로잡는다('240,750.00원와' -> '240,750.00원과'). 숫자 바로 뒤 '원'만 대상으로 한다."""
    return re.sub(r"(\d[\d,.]*\s?(?:조\s?|억\s?)?원)(와|가|를|는|로)(?=[\s,.)]|$)",
                  lambda m: m.group(1) + _WON_PARTICLES[m.group(2)], text)


def unsupported_chat_claim(text: str) -> bool:
    """자료에 없는 제공자 사정이나 기사 본문을 읽은 듯한 설명은 거절한다."""
    compact = re.sub(r"\s+", "", str(text or ""))
    if re.search(r"(야후|Yahoo|제공자|데이터소스|데이터제공).{0,30}(제공하지|주지않|지원하지|계산되지)", compact, re.IGNORECASE):
        return True
    return re.search(r"기사본문|본문에는|본문을|기사전문|기사내용", compact) is not None


def validate_follow_up(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise AppError("chat_follow", "이어서 물어볼 질문을 확인하지 못했습니다.")
    text = " ".join(value.split())
    if text.count("?") + text.count("？") != 1 or re.search(r"\d", text):
        raise AppError("chat_follow", "이어서 물어볼 질문을 확인하지 못했습니다.")
    if not text.endswith(("?", "？")) or re.search(r"[.!。！\n]", text):
        raise AppError("chat_follow", "이어서 물어볼 질문은 한 문장으로 작성해 주세요.")
    compact = re.sub(r"\s+", "", text).replace("매도사이드카", "사이드카").replace("매수사이드카", "사이드카")
    if re.search(r"다음에\s*궁금|다른\s*궁금한\s*점", text):
        raise AppError("chat_follow", "이어서 물어볼 질문을 확인하지 못했습니다.")
    if any(word in compact for word in ("매수", "매도", "목표주가", "투자추천", "수익보장")):
        raise AppError("chat_follow", "이어서 물어볼 질문을 확인하지 못했습니다.")
    if asserts_valuation(text) or wrong_per_formula(text) or unsupported_chat_claim(text):
        raise AppError("chat_follow", "이어서 물어볼 질문을 확인하지 못했습니다.")
    return text


def resolve_follow_up(raw, messages, result, discovery=None):
    # AI의 질문을 사용자 발화 버튼으로 복제하지 않는다. 필요 없는 질문은 생략한다.
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        text = validate_follow_up(raw)
    except AppError:
        return ""
    if any(m.get("follow_up") == text for m in messages[-6:]):
        return ""
    return text


def normalize_attachments(files: list[tuple[str, bytes]]) -> list[dict]:
    images = 0
    documents = 0
    items = []
    for name, data in files:
        if not isinstance(name, str) or not isinstance(data, bytes):
            raise AppError("chat_attachment", "첨부 파일을 읽지 못했습니다.")
        suffix = Path(name).suffix.lower()
        if not data or len(data) > MAX_ATTACHMENT_BYTES:
            raise AppError("chat_attachment", "첨부 파일은 1바이트 이상 5MB 이하만 사용할 수 있습니다.")
        if suffix in IMAGE_SUFFIXES:
            images += 1
            kind = "image"
            text = ""
        elif suffix == ".txt":
            documents += 1
            kind = "text"
            text = data.decode("utf-8", errors="replace")
        elif suffix == ".pdf":
            documents += 1
            kind = "pdf"
            text = ""
        else:
            raise AppError("chat_attachment", "첨부는 png, jpg, webp, txt, pdf만 사용할 수 있습니다.")
        if images > 2 or documents > 2:
            raise AppError("chat_attachment", "이미지와 문서는 각각 2개까지 첨부할 수 있습니다.")
        items.append({
            "name": Path(name).name,
            "kind": kind,
            "size": len(data),
            "data": data,
            "text": text,
        })
    return items


def attachments_for_model(items: list[dict]) -> dict:
    texts = []
    files = []
    for item in items:
        if item.get("kind") == "text":
            body = str(item.get("text") or "")
            texts.append({
                "name": item.get("name", ""),
                "text": body[:MAX_TEXT_CHARS],
                "truncated": len(body) > MAX_TEXT_CHARS,
            })
        else:
            files.append({"name": item.get("name", ""), "kind": item.get("kind", "")})
    return {"texts": texts, "files": files}


OUTLOOK_QUESTION = re.compile(r"올해|내년|전망|향후|앞으로|어떨")
PREDICTIVE_PRICE_QUESTION = re.compile(
    r"내일|다음\s*(?:주|달|분기|해)|얼마까지|오를까|떨어질까|내릴까|상승할까|하락할까|목표가|얼마나\s*갈까|얼마\s*갈까|예측"
)
JUDGMENT_QUESTION = re.compile(r"사도|살까|사야|매수|담아|들어가도|투자.{0,6}(?:어때|괜찮|매력)|전망|올해|내년|어떨")
COST_OR_NET_QUESTION = re.compile(r"원가|판관|판매관리|순이익|비용")
CORE_COMPARISON_ITEMS = {"revenue", "operating_income", "operating_margin"}

CHAT_INSTRUCTION = """
확인된 자료로 한국어 주식 분석 질문에 직접 답합니다. AI 본문은 정중한 입니다·합니다체만 사용합니다.
질문 종류에 맞춰 구성합니다. 단순 조회·단일 지표 후속은 확인값과 뜻을 합쳐 보통 한두 문장으로 답합니다. 결론·숫자·의미를 각각 별도 문장으로 반복하지 않습니다. 평가에는 비교·판단을, 상세 원인 질문에는 설명 깊이를 더합니다.
두괄식 직접 답변 원칙을 따릅니다: 1) 첫 문장에 사용자 질문에 대한 직접적인 결론을 먼저 제시하고, 2) 이를 뒷받침하는 핵심 확인 수치를 제시한 뒤, 3) 수치 간의 관계·변화의 의미를 설명한 뒤 마침표로 끝냅니다. 질문하지 않은 결측 항목, 예측 불가능성, '추가 확인이 필요합니다'나 '실적 지속성을 뒷받침할 추가 자료 확인이 필요합니다' 같은 습관적 면책·한계 문장은 덧붙이지 않습니다. 오해를 바로잡거나, 핵심 정보가 없어 질문에 답할 수 없거나, 미래 전망의 범위를 구분해야 할 때만 짧게 밝힙니다.
단순 개념은 뜻과 차이만 짧게 답합니다. 직전 대화에서 이미 설명한 금융 개념·정의는 반복하지 말고 사용자가 새로 질문한 평가·비교·원인 관점에 집중합니다. '알려드리겠습니다' 예고 대신 실질적인 분석을 바로 제공합니다. 특정 기업 없이 원리를 묻는 질문(예: 영업일이 줄면 매출도 같은 비율로 줄어드는지)은 첫 문장에서 '그만큼 줄지는 단정할 수 없다/그렇다'처럼 결론을 밝히고, 매출이 가동일수·단가·수요·재고 같은 요인으로 결정된다는 일반 원리로 설명합니다. 근거에 없는 특정 기업의 생산 방식·전략을 사실처럼 쓰지 않고, 질문과 무관한 근거 수치는 끌어 쓰지 않습니다.
JSON: {"text":"질문의 핵심 답", "evidence_ids":["PER"], "follow_up":"", "blocks":[]}
answer_style=issues이면 blocks에 {"title":"핵심 이슈 요약", "text":"확인된 사실과 질문에 필요한 설명", "evidence_ids":["NEWS_1"], "implication":null}을 작성합니다. presentation의 분량/최대 개수와 issue_groups의 독립 사건을 지킵니다. 같은 그룹의 여러 기사는 한 카드에 합치고 다른 사건의 근거는 섞지 않습니다. 카드의 evidence_ids에는 issue_groups 항목의 evidence_ids에 있는 NEWS id만 쓰고, 카드 수는 issue_groups 항목 수를 넘기지 않습니다. 충돌 수치는 평균/최신 값으로 임의 확정하지 않고 차이를 설명합니다. implication은 별도 근거 있는 해석이 필요할 때만 정중한 문장으로 작성하며 공지/일정에는 null로 생략합니다. 본문·제목에 [NEWS_1]이나 URL을 쓰지 않습니다. answer_style=plain이면 blocks는 빈 배열입니다.
전체 text와 블록은 합쳐 최대 3000자입니다. 각 설명은 evidence_ids로만 확인돼야 합니다.
날짜·종목코드·기사 개수 숫자를 임의로 쓰지 않습니다. value_text가 있는 금융 지표는 {{PER}}, {{PRICE}}, {{FACT_실제ID}}처럼 실제 키의 자리표시자를 씁니다. {{ }} 안에는 evidence에 있는 키 이름만 쓰며 금액·비율 같은 숫자를 넣지 않습니다. 뉴스·공시 수치는 자리표시자 없이 기사 원문 표기 그대로 직접 씁니다.
자리표시자는 evidence의 실제 키 중 value_text가 있는 키만 쓰고 해당 evidence_ids에도 넣습니다. 치환값에는 단위가 이미 포함되므로 뒤에 원·배를 덧붙이지 않습니다. 숫자 자체나 investment_amount 같은 항목명, structured_facts 내부 fact_id를 중괄호로 감싸지 않습니다. 검증된 비정형 사실의 금액은 직접 쓰되 원문과 동일한 값으로 억원·조원 등 읽기 쉬운 단위로 표현합니다.
annual_comparison은 당기·전기 금액과 증감률을 주어-서술어가 호응하는 한국어로 씁니다('매출은 증감률% 증가했고 영업이익은 증감률% 증가했으며 영업이익률은 차이%p 상승했습니다'). comparison_style=rates이면 CMP 대신 증감률 문장으로 직접 쓰며, verified_sentence_examples는 수치 형식의 참고 예시이며 모두 복사할 의무는 없습니다. 질문에 필요한 사실과 의미를 한 번씩 자연스럽게 묶으며, 같은 금액·증감률을 다른 표현으로 다시 쓰거나 억원·조원으로 환산하지 않고 연도·금액을 문장 밖에 따로 쓰지 않으며, CMP 치환 뒤에 증가·상승을 중복하지 않습니다.
뉴스의 scope=headline_only는 제목, article_excerpt는 검색 발췌까지 확인한 자료입니다. official_disclosure만 실제 공식 원문입니다. 확보한 범위를 넘는 본문·공시 확인을 만들지 않습니다. 보도된 사실은 보도 귀속을 자연스럽게 밝힙니다. 같은 키워드라도 별개 사건을 합치지 않습니다.
structured_facts의 status=verified 수치는 항목·기업·단위·기간·방향·잠정/합산/과거 상태를 유지해 직접 인용할 수 있습니다. 날짜도 실제 원문 Fact에 있을 때만 쓰고 조회/발행일을 사건일로 바꾸지 않습니다. 미등록 수치는 추측하지 않습니다.
stock_name·theme가 분석 대상입니다. 사업·사건 연결 근거가 없는 다른 회사·지주회사 기사는 생략하며, 개수를 채우려고 사건을 만들지 않습니다.
published_at은 발행 시각이며 사건 발생일이 아닙니다. 제목에 순서가 없으면 발행일만 보고 사건 순서로 단정하지 않습니다.
명시적 문장/줄 수는 카드 형식보다 우선합니다. 세 문장/세 줄과 세 가지 이슈는 다른 요청입니다. 각 이슈 한 문장 요청은 카드별 본문+implication 합계 한 문장입니다. 출처 상세를 본문 분량에 덧붙이지 않습니다.
값이 없는 원인은 reason에 확인된 범위만 설명하며, 미확인 원인을 공시 누락이나 제공자 미지원으로 추측하지 않습니다.
매매 지시·목표주가·수익 보장을 하지 않으며, PER가 낮다는 이유만으로 저평가라고 단정하지 않습니다.
지표를 말할 때는 지표 이름을 글자로 쓰고 바로 뒤에 자리표시자를 붙입니다('PER은 {{PER}}입니다', '현재가는 {{PRICE}}입니다'). 자리표시자로 지표 이름을 대신하거나 같은 지표를 한 문장에 두 번 쓰지 않습니다. 주가·PER 등 금융 지표의 기준 시점을 밝힐 때는 evidence의 as_of 또는 period에 적힌 기준일(YYYY년 M월 D일)만 쓰며 근거에 없는 시점을 임의로 쓰지 않습니다. 장 마감 후이거나 당일 이전 자료이면 기준일(또는 종가)을 함께 표기할 수 있습니다.
'사도 될까', '어때', '전망' 같은 판단 질문에는 수치를 나열하지 말고 첫 문장에 확인된 근거의 균형을 요약한 조건부 평가를 쓴 뒤, 질문에 필요한 핵심 근거의 의미를 연결해 설명합니다. 전망 후속에서는 앞서 설명한 과거 실적 숫자를 다시 나열하지 않고 미래 판단 조건에 집중합니다. 결론을 바꿀 만큼 중요한 제약(현재가가 오래된 자료인 경우, 비교 자료가 없어 상대 평가가 불가능한 경우 등)만 한 문장으로 밝히고, 그렇지 않으면 덧붙이지 않습니다. 비교·계산이 가능하면 '추가 자료 확인이 필요합니다'나 '구체적 계획 등 추가 확인이 필요합니다' 같은 의례적 문장으로 끝내지 말고 핵심 판단 요인만 밝히며 실제 판단을 제시합니다.
today는 오늘 날짜이고 this_year가 올해, next_year가 내년이며 latest_confirmed_annual_year가 확정 연간 실적의 마지막 연도입니다. 올해·내년 질문에는 evidence의 기간(확정 연간 실적의 연도, PER 계산 이익의 기준일)을 today와 비교해 '확정된 실적', '회사 계획·보도', '조건부 해석'을 구분합니다. 확인된 실적 기간과 요청한 전망 기간을 구분하며, '미래 확정 실적이 없다'거나 '회사 계획이 포함되어 있지 않다'는 식의 부재 해명 문장은 덧붙이지 않습니다. 회사 계획·예상치가 없으면 확인된 과거 흐름을 짧게 짚고 앞으로 볼 판단 조건(수요·가격·비용 등)을 일반 원리로 간결하게 설명합니다. 그 조건이 현재 회사에서 이미 성립했다고 단정하지 않습니다. 연도는 숫자 대신 '올해·내년·작년' 같은 상대 표현으로 쓰고, 연간 수치를 쓸 때는 검증된 값·방향을 지키되 질문에 필요한 핵심만 선택합니다. verified_sentence_examples를 그대로 복사할 의무는 없고 같은 금액·변화율을 반복하지 않습니다.
follow_up은 질문이 모호해 답할 수 없을 때만 쓰고, 그 밖에는 항상 빈 문자열입니다. 요청하지 않은 추가 분석을 권하는 질문을 만들지 않습니다.
질문이 시장 예상치(컨센서스) 상회 여부나 어닝 서프라이즈를 묻는데 evidence에 같은 기준의 예상치가 없으면, 예상치 상회 여부는 확인할 수 없다는 점을 첫 문단에서 직접 밝히고 확인되는 전년 대비 등의 비교만 답합니다. 발표치·예상치·전년 동기를 서로 다른 기준끼리 섞지 않고, 주가가 올랐는지·내렸는지 묻는 질문은 확인된 가격 변화와 실적 개선을 구분하되 하락·상승의 원인을 단정하지 않습니다. 주가 변동과 뉴스의 인과를 묻는 질문('주가가 오른 건 뉴스 때문이야?' 등)에서 관련 뉴스가 없으면 첫 문장에서 '현재 수집된 최근 뉴스 기사로는 주가 상승의 직접적 원인을 확인하기 어렵습니다'라고 밝히고 현재 주가를 제시합니다. 반면 공급 계약이나 실적 개선 등 관련 호재 뉴스가 있으면 첫 문장에서 보도된 소식(공급 계약 등)이 시장 기대감에 영향을 주었을 가능성을 언급하되, 뉴스가 상승의 유일한 원인이라고 단정하지는 않습니다. 회사의 목표·전망(가이던스)은 확정 실적과 구분하고 영업현금흐름 같은 지표를 다른 지표(잉여현금흐름 등)와 같은 것으로 쓰지 않습니다. 회사 계획·투자 발표를 이미 발표된 실적의 원인으로 연결하지 않고, 계약 전체 금액을 연간 매출 감소액으로 바꾸지 않으며, 시장 전망을 확정 지표로 쓰지 않습니다. 기사 수와 독립 사건 수를 구분합니다. 비율은 읽기 쉬운 단위로 쓰고 %와 %p를 구분합니다.
"""


def _direct_answer(text, result, attachments, evidence, *, strict=False, messages=None):
    if strict and result is not None:
        from src.agents.period_scope import missing_quarter_answer
        from src.agents.quarterly import contextual_quarter
        period_request = contextual_quarter(text, messages or [])
        unavailable = missing_quarter_answer(text, evidence, request=period_request)
        if unavailable:
            from src.agents.quarterly import market_evidence
            if not market_evidence(text, evidence):
                return [], [], (unavailable, [], "")
    keys = list(dict.fromkeys(re.findall(r"(?<![A-Z])(?:PER|PBR|ROE|EPS|BPS)(?![A-Z])", text.upper())))
    korean_keys = []
    if re.search(r"배당수익률|배당률|배당금", text):
        korean_keys.append("배당수익률")
    if re.search(r"시가총액|시총", text):
        korean_keys.append("시가총액")
    all_concept_keys = [*keys, *korean_keys]
    if not keys and messages and not OUTLOOK_QUESTION.search(text):
        # 올해·내년 전망 질문은 직전 대화의 지표를 이어받는 값 질문이 아니라 종합 평가 질문이다.
        keys = infer_implicit_metrics(text, messages)
    composite = strict and bool(re.search(r"뉴스|기사|재무|실적|차트|거래량", text))
    targeted = result is not None and (any(w in text for w in ("현재", "이 종목", "선택", "이번", result.financial.stock.name)) or not is_concept_question(text))
    if all_concept_keys and is_concept_question(text) and not targeted and not attachments and not composite:
        return all_concept_keys, [], (concept_answer(all_concept_keys), [], "")
    if korean_keys and result is not None and not attachments and not composite:
        if re.search(r"얼마|몇|알려|확인|수치|값", text) and not is_evaluation_question(text):
            stock_name = result.financial.stock.name
            metric_label = "배당수익률(배당금)" if "배당수익률" in korean_keys else "시가총액"
            msg = f"{stock_name}의 {metric_label}은 현재 기본 수집된 재무 지표에 포함되어 있지 않습니다. 현재 확인 가능한 기본 지표는 주가, PER, PBR, ROE, EPS, BPS입니다."
            return keys, [], (msg, [], "")
    if result is not None and not OUTLOOK_QUESTION.search(text) and PREDICTIVE_PRICE_QUESTION.search(text) and re.search(r"주가|가격|얼마|상승|하락|오를|내릴", text) and not is_concept_question(text):
        stock_name = result.financial.stock.name
        price_item = evidence.get("PRICE")
        as_of_label = ""
        if price_item and price_item.get("as_of"):
            m = re.match(r"(20\d{2})-(\d{2})-(\d{2})", str(price_item["as_of"]))
            if m:
                as_of_label = f"({m.group(1)}년 {int(m.group(2))}월 {int(m.group(3))}일 기준)"
        price_str = f" {price_item['value_text']}" if price_item and price_item.get("value_text") else ""
        msg = (
            f"내일의 구체적인 주가 등락이나 도달 가격을 단정하여 예측할 수는 없습니다. "
            f"현재 확인된 {stock_name}의 주가는{price_str}입니다{as_of_label}. "
            f"단기 주가는 특정 목표치보다는 시장 전체의 수급 상황, 거시경제 지표, 동종 업황의 투자 심리 등에 따라 변동될 수 있습니다."
        )
        used = [dict(price_item, id="PRICE", answer_origin="verified_forecast_refusal")] if price_item else []
        return keys, ["PRICE"] if price_item else [], (msg, used, "")
    required = list(keys) if targeted else []
    if (result is not None and re.search(r"주가|현재가|가격", text) and not is_concept_question(text)
            and (not OUTLOOK_QUESTION.search(text) or re.search(r"현재|지금|얼마|몇\s*원|주가도|가격도",text))):
        required.append("PRICE")
    # 값 확인·누락 질문에는 조회값을 코드에서 직접 답한다. 모델의 정의로 대체하지 않는다.
    value_query = (
        required
        and re.search(r"얼마|몇|값|수치|없|확인|알려", text)
        and not is_evaluation_question(text)
        and not PREDICTIVE_PRICE_QUESTION.search(text)
        and not re.search(r"해석|어떻게|위험|비교|종합|왜.*(?:높|낮|변|올|내)", text)
    )
    missing_query = (len(required) == 1 and evidence[required[0]].get("value") is None
                     and re.search(r"없|누락|안\s*(?:나|보)|미확인", text)
                     and not re.search(r"뉴스|기사|차트|재무|실적|비교|종합|매수|매도", text))
    if (value_query or missing_query) and not attachments and not composite:
        used = [dict(evidence[k], id=k) for k in dict.fromkeys(required)]
        lines = []
        for item in used:
            if item.get("value") is not None:
                if len(used) == 1 and item["id"] == "PER":
                    period_label = f" ({item['period']})" if item.get("period") and "미확인" not in item["period"] else ""
                    lines.append(
                        f"{item['text']}입니다{period_label}. 주가가 계산에 사용된 주당순이익의 {item['value_text']} 수준에서 형성되어 있음을 나타내는 지표입니다."
                    )
                elif len(used) == 1 and item["id"] == "PRICE":
                    as_of = str(item.get("as_of") or "")
                    m = re.match(r"(20\d{2})-(\d{2})-(\d{2})", as_of)
                    as_of_label = f" ({m.group(1)}년 {int(m.group(2))}월 {int(m.group(3))}일 기준)" if m else ""
                    lines.append(f"{item['text']}입니다{as_of_label}.")
                elif len(used) == 1 and item["id"] in TERMS:
                    lines.append(f"{item['text']}입니다. {TERMS[item['id']][0]}")
                else:
                    lines.append(item["text"] + "입니다.")
            else:
                lines.append(item["text"] + ".")
                lines.append(item.get("reason") or "이번 자료에서는 누락 원인을 확인할 수 없습니다. 값이 영이라는 뜻은 아닙니다.")
        return keys, required, ("\n\n".join(lines), used, "")
    return keys, required, None


def _answer_request(text, result, messages, attachments, evidence, keys, required):
    from src.agents.followup import is_conversation_summary_request
    is_conv_summary = is_conversation_summary_request(text)
    groups=card_groups(group_issues(evidence))
    contract=parse_presentation(text,has_news=bool(result is not None and groups))
    request = {"task": "chat_answer", "question": normalize_message(text),
        "answer_style": contract.style, "presentation":contract.payload(),
        "issue_groups":[g.payload() for g in groups],
        "stock_name": None if is_conv_summary else (result.financial.stock.name if result else None), "theme": result.theme if result else None,
        "conversation": conversation_context(messages, None if is_conv_summary else result), "evidence": evidence,
        "required_evidence_ids": required, "attachments": attachments_for_model(attachments or [])}
    if groups:
        reported = any(v.get("scope") in {"headline_only", "article_excerpt"}
                       for k,v in evidence.items() if k.startswith("NEWS_") and k != "NEWS_STATUS")
        request["news_answer_contract"] = {
            "available_issue_groups": len(groups),
            "explain_shortfall": bool(contract.explicit_issues and len(groups) < contract.max_issues),
            "report_attribution": "보도 내용은 첫 문장 안에서 관련 보도에 따르면 등으로 귀속합니다. 회사가 제시한 이유는 회사 설명으로 전달합니다." if reported else "확보한 공식 원문 범위만 답합니다.",
            "avoid_repetition": "카드 본문에 설명할 내용을 도입에서 반복하지 않습니다. 단일 사건 후속 질문은 답과 의미를 연결한 글로 씁니다.",
        }
    request['interpretation_policy']=INTERPRETATION_POLICY
    request["concept_reference"] = {k: TERMS[k] for k in keys}
    if any(word in text for word in ("매수", "매도", "지정가", "시장가")):
        request["concept_reference"].update(TRADING_CONCEPTS)
    return request


from src.agents.grounding import REVIEW_INSTRUCTION, review_response


def _check_answer(payload, evidence, required, result, request, settings, text):
    if isinstance(payload,dict) and isinstance(payload.get('blocks'),list):
        payload={**payload,'blocks':[_canonical_block(block) for block in payload['blocks']]}
    if settings.strict_news and isinstance(payload, dict):
        from src.agents.financial_numbers import normalize_financial_units
        payload = recover_evidence_ids(payload, evidence)
        if isinstance(payload.get("text"), str):
            normalized=normalize_metric_subject(payload["text"],evidence)
            payload = {**payload, "text": normalize_financial_units(normalized, evidence)}
    response = validate_response(payload, evidence, request.get("answer_style", "plain"), question=text)
    contract=parse_presentation(text,has_news=request.get('answer_style')=='issues')
    if contract.max_lines:
        # 문장 내용은 바꾸지 않고 요청한 줄 구조만 보장한다. 소수점은 분리하지 않는다.
        lines = sentences(response.intro)
        if len(lines) > contract.max_lines:
            raise AppError("chat_length", f"요청한 {contract.max_lines}줄 이내로 요약해야 합니다.")
        response = replace(response, intro="\n".join(lines))
    # 이슈 카드(blocks) 형식에서는 도입에 범위 고지를 보존하고, 일반 단문 대화는 하단 출처로 일원화한다.
    if not contract.max_sentences and any(item.get("scope") == "headline_only" for item in response.evidence) and not re.search(r"제목|헤드라인", response.intro):
        response = replace(response, intro="수집된 뉴스 제목 기준입니다. " + response.intro)
    if request.get("outlook_answer_context"):
        from src.agents.outlook import arrange_conclusion
        response=arrange_conclusion(response,request.get("summary_of_question",text),messages=request.get("conversation"))
    response = attribute_reported_news(response)
    response = deduplicate_margin_note(response)
    answer, used, _ = response
    enforce_presentation(response,contract)
    enforce_single_margin_change(response)
    if request.get("outlook_answer_context"):
        from src.agents.outlook import enforce_scope
        response = enforce_scope(response,request.get("summary_of_question",text),messages=request.get("conversation"))
    if 'issue_groups' in request and response.blocks:
        validate_issue_cards(response,evidence,group_issues(evidence),max_issues=contract.max_issues)
    if not set(required).issubset({e["id"] for e in used}):
        raise AppError("chat_evidence", "질문한 지표의 근거가 빠졌습니다.")
    used_ids = {item["id"] for item in used}
    for group in request.get("required_groups", {}).values():
        expected = set(group["ids"])
        complete = expected.issubset(used_ids) if group["mode"] == "all" else bool(expected & used_ids)
        if not complete:
            raise AppError("chat_scope", "요청한 자료 범위 중 일부가 답변에서 빠졌습니다.")
    raw_text = payload['text']+' '.join(block['text']+' '+str(block.get('implication') or '') for block in payload.get('blocks',()))
    if request.get("comparison_style") == "rates" and "{{CMP_" in raw_text:
        raise AppError("chat_comparison_style", "확인된 증감률 문장으로 비교 내용을 작성해야 합니다.")
    if re.search(r"\{\{CMP_[A-Z0-9_]+\}\}\s*(?:로|으로)?\s*(?:증가|감소|상승|하락)", raw_text) or re.search(
        r"\([0-9.,]+%(?:p)?\s*(?:증가|감소|상승|하락)\)\s*(?:로|으로)?\s*(?:증가|감소|상승|하락)", response.text
    ):
        raise AppError("chat_comparison_style", "비교 자리표시자 뒤에 증감 표현을 중복하지 않아야 합니다.")
    if settings.strict_news and "PER" in used_ids:
        metric = evidence["PER"]
        period_unknown = not metric.get("period") or "미확인" in metric["period"]
        current_earnings = re.search(r"현재\s*시점(?:의|에서)?\s*(?:주당순이익|순이익|이익)", response.text)
        if period_unknown and current_earnings and not re.search(r"아닙|아니|않|볼\s*수\s*없", response.text[current_earnings.end():current_earnings.end() + 30]):
            raise AppError("chat_time_basis", "PER 계산에 쓰인 이익의 기준 기간을 확인하지 못했습니다.")
    if evidence or request["concept_reference"]:
        verdict, units = review_response(response, evidence, request, settings, _invoke)
        failures = failed_checks(verdict)
        unit_failures = failed_unit_reviews(verdict, units, require_relevance=request.get("review_profile") == "scoped-v1")
        if unit_failures and "evidence_match" not in failures:
            failures.append("evidence_match")
        if failures or not isinstance(verdict, dict) or verdict.get("supported") is not True or verdict.get("answers_question") is not True:
            # 검증 모델의 자유 서술을 새 지시/사실로 전달하지 않고 실패 축만 재작성에 사용한다.
            request["review_feedback"] = {
                "supported": isinstance(verdict, dict) and verdict.get("supported") is True,
                "answers_question": isinstance(verdict, dict) and verdict.get("answers_question") is True,
            }
            request["failed_quality_checks"] = failures
            request["failed_review_units"] = unit_failures
            request["unsupported_statements"] = [
                re.sub(r"\d[\d,.]*", "[미검증 수치]", unit["statement"])[:2000]
                for unit in units if unit["id"] in unit_failures
            ]
            raise AppError("chat_grounding", "답변의 사실 근거나 질문 충족 여부를 확인하지 못했습니다.")
    return response


def _metric_fallback(text, required, attachments, evidence):
    if (len(required) == 1 and required[0] in TERMS and not attachments
            and (re.search(r"해석|이해|설명|의미", text) or is_evaluation_question(text))
            and not re.search(r"뉴스|실적|위험|원인|왜|매수|매도|사도|살까|다른|차트", text)):
        key = required[0]
        item = dict(evidence[key], id=key, answer_origin="verified_metric_fallback")
        return verified_metric_explanation(key, item), [item], ""
    return None


_EOK = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{5,}(?:\.\d+)?)\s*억원")


_GENERIC_CAVEAT = re.compile(
    r"개별\s*투자\s*(?:목표|성향)|투자\s*시점의\s*시장\s*(?:상황|환경)|"
    r"추가\s*(?:적인\s*)?(?:자료|데이터|정보|공시|내역)?\s*(?:의\s*)?(?:확인|분석|검토)이?\s*(?:필요|요구)|"
    r"확인할\s*추가\s*(?:자료|데이터|정보)|"
    r"실적\s*지속성을\s*뒷받침할\s*(?:추가|자료)|"
    r"고려하시기\s*바랍니다|"
    r"(?:최종\s*)?투자\s*판단(?:은|이)?\s*(?:본인|투자자)|참고(?:용)?으로\s*활용|"
    r"주가\s*변동과\s*(?:직접(?:적으로)?\s*)?연결.*(?:확인되지\s*않|확인하기\s*어렵|파악하기\s*어렵|단정하기\s*어렵|찾을\s*수\s*없)|"
    r"(?:원가\s*구조|세부\s*비용).*(?:단정하기\s*어려|확인하기\s*어려|파악하기\s*어려)|"
    r"(?:확인된|제공된|요청하신)\s*(?:자료|뉴스)?\s*범위\s*내에서.*(?:단정하기\s*어려|확인하기\s*어려)"
)
_CLAUSE_END = ((r"(?:있으나|있지만|있으며|있고)$", "있습니다."), (r"(?:이나|이지만|이며|이고)$", "입니다."),
               (r"(?:했으나|했지만|했으며|했고)$", "했습니다."))


def _strip_caveat_line(line):
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
        if _GENERIC_CAVEAT.search(sentence):
            head, sep, tail = sentence.rpartition(", ")
            matched_clause = False
            if sep and _GENERIC_CAVEAT.search(tail) and not re.search(r"\d", tail):
                for pattern, ending in _CLAUSE_END:
                    if re.search(pattern, head):
                        sentence = re.sub(pattern, ending, head)
                        matched_clause = True
                        break
            if not matched_clause:
                continue
        kept.append(sentence)
    return " ".join(kept)


def strip_habitual_caveats(text):
    """숫자가 없는 습관적 면책 문장·절을 표시 단계에서만 제거한다(줄 구분과 검증된 수치 문장은 유지한다)."""
    lines = [_strip_caveat_line(line) if line.strip() else line for line in text.split("\n")]
    result = "\n".join(lines)
    return result if result.strip() else text


def humanize_amounts(text):
    """검증을 마친 본문의 1만 억원 이상 금액을 조 단위로 바꿔 읽기 쉽게 한다(화면 표시 전용, 값은 반올림 표기)."""
    def repl(match):
        value = float(match.group(1).replace(",", ""))
        if value < 10000:
            return match.group(0)
        return f"{value / 10000:,.1f}조 원"
    return _EOK.sub(repl, text)


def _verified_fallback(text, evidence, request):
    """모델 답변이 검증을 통과하지 못했을 때, 이미 검증된 사실만 모아 제한 답변을 만든다.

    새 문장을 지어내지 않고 (1) 검증 문장(verified_sentence_examples), (2) 확인된 현재가·PER 값,
    (3) 관련성이 확인된 뉴스 제목만 쓴다. 심층 분석 성공이 아니므로 answer_origin으로 표시한다.
    """
    parts, items = [], []
    if request.get("question_goal") == "company_overview":
        from src.agents.company_overview import comparison_fallback
        overview = comparison_fallback(evidence)
        if overview:
            return humanize_amounts(overview[0]), overview[1], ""
    wants_news = request.get("answer_style") == "issues" or re.search(r"뉴스|기사|이슈|소식|보도|공시", text)
    wants_fin = re.search(r"실적|매출|영업이익|이익률|원가|판관|판매관리|재무|사도|살까|매수|전망|요약|어때|괜찮|올해|내년|어떨|향후|앞으로|지속|PER|주가|현재가|차이|왜|이유|원인|배경", text)
    if wants_fin:
        sentences_ = [x for x in request.get("verified_sentence_examples", request.get("must_include_sentences", [])) if isinstance(x, str)]
        if sentences_:
            parts.append(" ".join(sentences_))
            items += [dict(evidence[k], id=k, answer_origin="verified_fallback") for k in evidence
                      if evidence[k].get("kind") in {"annual_comparison", "quarterly_comparison"} and evidence[k].get("status") == "ok"]
        quote = [f"{label} {evidence[key]['value_text']}" for key, label in (("PRICE", "현재가"), ("PER", "PER"))
                 if key in evidence and evidence[key].get("status") == "ok" and evidence[key].get("value_text")]
        if quote:
            parts.append("확인된 " + ", ".join(quote) + "입니다.")
            items += [dict(evidence[k], id=k, answer_origin="verified_fallback") for k in ("PRICE", "PER")
                      if k in evidence and evidence[k].get("status") == "ok"]
    from src.agents.outlook import is_outlook
    if is_outlook(text):
        parts.append("과거 실적 개선 흐름이 앞으로의 지속적인 성장을 보장하지는 않습니다. 향후 실적의 지속 여부는 시장 수요, 판매가격, 비용 구조 등 핵심 요인에 달려 있습니다.")
        if not items:
            items += [dict(evidence[k], id=k, answer_origin="verified_fallback") for k in evidence
                      if evidence[k].get("kind") in {"annual_comparison", "quarterly_comparison"} and evidence[k].get("status") == "ok"]
    judgment = bool(JUDGMENT_QUESTION.search(text))
    if judgment and parts and not wants_news:
        # 판단 질문에 수치만 나열하지 않도록, 수치 하나로 매수 여부를 정할 수 없다는 점을 코드가 고정 문장으로 먼저 밝힌다(새 사실·수치 없음).
        parts.insert(0, "이 질문은 아래 확인된 수치만으로 매수 여부나 저평가 여부를 단정할 수 없습니다. 확인된 실적과 지표는 다음과 같습니다.")
    if wants_news or (judgment and parts):
        groups = request.get("issue_groups") or []
        heads = [g["evidence_ids"][0] for g in groups if g.get("evidence_ids")]
        rest = [k for k, v in evidence.items() if k.startswith("NEWS_") and k != "NEWS_STATUS" and k not in heads and v.get("text") and v.get("admitted", True)]
        asked = re.search(r"([1-9])\s*(?:가지|개|건)", text)
        limit = int(asked.group(1)) if asked else (2 if judgment and not wants_news else 3)
        titles = [(k, evidence[k]["text"]) for k in [*heads, *rest] if k in evidence and evidence[k].get("text") and k != "NEWS_STATUS"][:limit]
        if titles:
            parts.append(("관련성이 확인된 최근 소식은 다음과 같습니다.\n" if wants_news else "참고할 만한 최근 보도 제목은 다음과 같습니다.\n") + "\n".join(
                f"{n}. {t}" for n, (_, t) in enumerate(titles, 1)))
            items += [dict(evidence[k], id=k, answer_origin="verified_fallback") for k, _ in titles]
    if not parts:
        return None
    return humanize_amounts("\n\n".join(parts)), items, ""


def _apply_retry_feedback(request, payload, error):
    request["validation_error"] = error.code
    # 잘못 생성된 수치를 다시 사실 문맥으로 전달하지 않는다.
    request["rejected_answer"] = re.sub(r"\d[\d,.]*", "[미검증 수치]", str(payload.get("text", ""))) if isinstance(payload, dict) else "형식 오류"
    if isinstance(payload, dict) and isinstance(payload.get("blocks"), list):
        request["rejected_blocks"] = [
            {key: re.sub(r"\d[\d,.]*", "[미검증 수치]", str(block.get(key, "")))[:2000]
             for key in ("title", "text", "implication")}
            for block in payload["blocks"][:3] if isinstance(block, dict)
        ]
    leftovers = getattr(error, "leftover_contexts", None)
    if leftovers:
        request["unverified_number_contexts"] = leftovers
    guidance = [
        *(["unverified_number_contexts는 앞 답변에서 검증되지 않은 숫자(□)가 남은 문구입니다. 해당 숫자를 지우거나 verified 문장·자리표시자로 대체하고, 연도는 확인된 비교 문장 밖에서 따로 쓰지 않습니다."] if leftovers else []),
        "첫 문장에 질문의 답을 제시하고, 확인된 자료만 정중한 입니다·합니다체로 설명합니다.",
        *(["연도 숫자를 따로 쓰지 말고 '올해·내년·작년·전년'처럼 상대 표현으로 바꾸며, 연간 금액·증감률은 verified_sentence_examples나 확인된 비교 문장 밖에서 단독 금액으로 다시 쓰지 않습니다."] if leftovers else []),
        "수치는 evidence의 확인된 자리표시자, annual_comparison(CMP)의 확인된 증감률·항목 수치 또는 structured_facts의 status=verified 사실만 사용합니다. 회사·항목·단위·기간·방향·잠정/합산/이력 조건을 유지하고 필요한 근거 ID를 모두 포함합니다.",
        "본문과 제목의 근거 번호·종목코드·URL은 제거합니다. 날짜는 검증된 사건일/기간만 쓰며 출처 ID는 evidence_ids에만 둡니다.",
        "수집하지 않은 비교·원인·누락 사유를 추측하지 않습니다. 불필요한 후속 질문은 생략합니다.",
        *(["verified_sentence_examples의 확인된 값·단위·방향을 참고하되 문장을 그대로 나열할 의무는 없습니다. 필요한 수치와 의미를 한 번씩만 씁니다."] if request.get("verified_sentence_examples") else []),
        "{{ }} 자리표시자에는 evidence의 키 이름(PER, PRICE, FACT_… 등)만 쓰고 숫자를 넣지 않습니다. 뉴스·공시 수치는 자리표시자 없이 기사 원문 표기 그대로 쓰고, 근거 기사에 없는 수치는 쓰지 않습니다.",
    ]
    question = request["question"]
    for key in request.get("failed_quality_checks", []):
        guidance.append("보완할 기준: " + QUALITY_CHECKS[key])
    review = request.get("review_feedback", {})
    if review.get("supported") is False:
        guidance.append("앞 답변의 근거 적합성이 거절됐습니다. 근거에 없는 사건·시점·원인·비교는 제거하고 확인 범위를 명시합니다.")
    if request.get("unsupported_statements"):
        guidance.append("unsupported_statements는 앞 답변에서 검증하지 못한 문장입니다. 사실 근거로 사용하지 말고 evidence와 대조해 수정합니다. 자료 한계 설명은 확인 범위에 맞게 유지합니다.")
    if review.get("answers_question") is False:
        guidance.append("앞 답변은 질문을 충족하지 못했습니다. 제목·정의를 반복하지 말고 사용자가 물은 의미와 확인 가능한 해석의 한계를 직접 설명합니다.")
    guidance.extend(parse_presentation(question,has_news=request.get('answer_style')=='issues').instructions())
    if re.search(r"(?<![A-Z])PER(?![A-Z])", question.upper()):
        guidance.extend((
            "낮은 PER를 저평가로 단정하거나 주의문을 덧붙여 정당화하지 않습니다. 사용자가 낮다고 말했어도 비교 자료가 없다면 그 회사의 주가가 이익 대비 낮은 수준이라는 사실로 승인하지 않습니다.",
            "PER는 주가를 주당순이익으로 나눈 배수입니다. 일반 원리와 회사의 확인된 사실을 구분합니다.",
        ))
    if re.search(r"뉴스|기사", question):
        guidance.append("각 근거의 제목/검색 발췌/공식 원문 scope를 지키고 보도 사실은 보도에 귀속합니다. 발행일을 사건일로 쓰거나 자료에 없는 원인·실현된 실적을 만들지 않습니다.")
    if re.search(r"차트|거래량|추이", question):
        guidance.append("HISTORY의 조회 기간과 값만 해석합니다. 가격 변화의 원인을 만들어 넣지 않습니다.")
    if re.search(r"재무|실적|매출|영업이익", question):
        guidance.append("재무 자료의 기간과 연결·별도 기준을 일치시키고 실제 수집한 사실만 비교합니다.")
    guidance.append("오류 종류: " + error.code)
    if error.code == "chat_outlook_scope":
        guidance.append("질문의 올해/내년을 그대로 유지합니다. 첫 문장에 전망의 지속 여부나 주가 질문의 답을 먼저 씁니다. 과거 결과만으로 시작하지 않습니다. 아직 오지 않은 해의 확정 실적이 없다거나 회사 계획이 없다는 식의 불필요한 부재 해명 문장은 절대 쓰지 말고, 확인된 과거 흐름과 앞으로 볼 핵심 판단 요인(수요·가격·비용 등)만 간결하게 설명합니다.")
    if error.code == "chat_repetition":
        guidance.append("전기→당기 이익률과 %p 변화는 한 번만 씁니다. 뒤에는 같은 변화 수치를 다시 쓰지 않고 매출에서 영업이익으로 남기는 비중의 의미를 설명합니다.")
    if error.code == "chat_comparison_style":
        if request.get("comparison_style") == "rates":
            guidance.append("comparison_style=rates입니다. CMP 자리표시자를 제거하고 제공된 change_pct/delta_pp를 항목별 %/%p 증감 문장으로 직접 씁니다.")
        else:
            guidance.append("CMP 자리표시자 자체에 연도·수치·증감 설명이 포함됩니다. 자리표시자 바로 뒤에 '로 감소/상승/하락'을 중복하지 않습니다. 자리표시자는 유지하고 그 의미를 별도 문장으로 설명합니다.")
    if error.code == "chat_time_basis":
        guidance.append("PER의 계산 이익 기간이 미확인일 때 현재 시점 이익으로 계산됐다고 쓰지 않습니다. 확인된 PER 값과 일반적인 뜻을 설명하며 미확인 시각을 본문에 길게 나열하지 않습니다.")
    request["validation_feedback"] = " ".join(guidance)
    if request.get("review_profile") == "scoped-v1":
        # 오류 축과 현재의 확인된 근거로 다시 생성한다. 거절된 전체 답변을
        # 반복 입력해 잘못된 기간·비교 형식이 답변 초안으로 고착되지 않게 한다.
        request.pop("rejected_answer", None)
        request.pop("rejected_blocks", None)


def answer_question(text: str, result: AnalysisResult | None, messages: list[dict],
                    settings: Settings, attachments: list[dict] | None = None,
                    discovery: CandidateDiscoveryResult | None = None, *,
                    limited_on_failure: bool = False) -> ChatResponse | tuple[str, list[dict], str]:
    """limited_on_failure=True이면 검증 실패 시 오류 대신 확인된 사실만 담은 제한 답변을 돌려준다(화면 전용)."""
    from contextlib import nullcontext
    from src.agents.local_verification import turn_budget
    budget_ctx = turn_budget(getattr(settings, "local_turn_timeout", 300.0)) if settings.ai_provider == "local" else nullcontext()
    with budget_ctx:
        return _answer_question_impl(text, result, messages, settings, attachments, discovery, limited_on_failure)


def _answer_question_impl(text: str, result: AnalysisResult | None, messages: list[dict],
                          settings: Settings, attachments: list[dict] | None = None,
                          discovery: CandidateDiscoveryResult | None = None,
                          limited_on_failure: bool = False) -> ChatResponse | tuple[str, list[dict], str]:
    evidence = build_evidence(result)
    from src.agents.followup import is_conversation_summary_request
    is_conv_summary = is_conversation_summary_request(text)
    scoped_messages = messages if is_conv_summary else _current_stock_messages(messages, result)
    keys, required, direct = _direct_answer(text, result, attachments, evidence, strict=settings.strict_news, messages=scoped_messages)
    if direct is not None:
        try:
            enforce_presentation(ChatResponse(direct[0],direct[1],direct[2]),parse_presentation(text))
        except AppError:
            direct=None  # 긴 고정 설명 대신 같은 개념/근거를 사용해 요청 분량으로 생성한다.
        else:
            return direct
    selection = select_evidence(text, scoped_messages, evidence, required, strict=settings.strict_news)
    if result is not None and settings.strict_news and any(
            key.startswith("NEWS_") and key != "NEWS_STATUS" for key in selection.evidence):
        from src.agents.news_relevance import prepare_news, admitted_evidence
        news = prepare_news(result.news, result.financial.stock, result.theme, settings, context_id=result.result_id)
        result = replace(result, news=news)
        evidence = build_evidence(result)
        selection = select_evidence(text, scoped_messages, admitted_evidence(evidence, news.admission), required, strict=True)
    evidence, requirements, required = selection.evidence, list(selection.requirements), list(selection.required_ids)
    principle_only = bool(MECHANISM_QUESTION.search(text) and not re.search(r"20\d{2}|올해|작년|내년|지난해|분기|얼마|몇", text))
    if principle_only:
        # '영업일이 줄면 매출도 그만큼 줄어?'처럼 특정 수치가 아니라 원리를 묻는 질문은 지표 근거를 필수로 요구하지 않는다.
        requirements, required = [], []
    request = _answer_request(text, result, scoped_messages, attachments, evidence, keys, required)
    from src.agents.question_goal import question_goal
    request["question_goal"] = question_goal(text).purpose
    from src.agents.outlook import is_outlook, uses_judgement_style, concept_reference as outlook_concepts, requirements as outlook_requirements, answer_context as outlook_context
    source_question = text
    if selection.reason == "restatement":
        from src.agents.followup import restatement_origin
        source_question=restatement_origin(scoped_messages) or text
        request["summary_of_question"]=source_question
        requirements.append("summary_of_question 에 답했던 직전 답변의 핵심 결론을 요약합니다. 숫자 나열만 남기며 전망/판단의 핵심을 지우지 않습니다.")
    if uses_judgement_style(source_question):
        request["outlook_answer_context"]=outlook_context(source_question,evidence,messages=scoped_messages)
        request["concept_reference"].update(outlook_concepts())
        requirements.extend(outlook_requirements(source_question, messages=scoped_messages))
    if principle_only:
        request["concept_reference"].update(MECHANISM_CONCEPTS)
        request["principle_only"] = True
    request["evidence"] = model_evidence(evidence)
    if JUDGMENT_QUESTION.search(text) and not COST_OR_NET_QUESTION.search(text):
        # 판단 질문에는 항목 전체 나열이 아니라 핵심 비교만 필요하다. 모델에 보이는 근거만 줄이고 검증 근거는 그대로 둔다.
        for key, item in list(request["evidence"].items()):
            if isinstance(item, dict) and item.get("kind") == "annual_comparison" and item.get("item") not in CORE_COMPARISON_ITEMS:
                request["evidence"].pop(key)
    today = datetime.date.today()
    confirmed = [int(y) for item in evidence.values() if item.get("kind") == "annual_comparison" and item.get("status") == "ok"
                 for y in item.get("years", ())]
    request["today"] = today.isoformat()
    request["this_year"], request["next_year"] = today.year, today.year + 1
    if confirmed:
        request["latest_confirmed_annual_year"] = max(confirmed)
    if request.get("news_answer_contract", {}).get("explain_shortfall"):
        count=request["news_answer_contract"]["available_issue_groups"]
        requirements.append(f"요청한 개수보다 적은 이번 자료의 독립 이슈 {count}건만 제시합니다. 도입에서 이번 확인 범위의 건수를 짧게 밝히고 무관한 기사로 채우지 않습니다.")
    request["answer_requirements"] = requirements
    request["selection"] = {"mode": selection.reason, "missing_financial_items": selection.missing}
    if settings.strict_news and (evidence or request["concept_reference"]) and not is_conv_summary:
        request["review_profile"] = "scoped-v1"
    if selection.required_groups and not principle_only:
        request["required_groups"] = selection.required_groups
    if settings.strict_news:
        from src.agents.financial_numbers import use_rate_sentences
        if use_rate_sentences(evidence):
            request["comparison_style"] = "rates"
            sentences = [item["verified_sentence"] for item in request["evidence"].values()
                         if isinstance(item, dict) and item.get("verified_sentence")]
            if sentences:
                request["verified_sentence_examples"] = sentences
        else:
            comparison_keys = [k for k, v in evidence.items() if v.get("kind") == "annual_comparison"]
            if comparison_keys:
                samples = [request["evidence"][k].get("verified_sentence") for k in comparison_keys]
                if all(samples):
                    request["verified_sentence_examples"] = samples
                    requirements.append("이번 비교에는 적자/흑자 전환이 있습니다. verified_sentence_examples의 검증된 값·부호·전환 방향을 사용하며 증감률을 만들지 않습니다. 필요한 비교만 선택해 의미와 함께 자연스럽게 설명하고, 화살표 형태의 CMP 전체를 나열하지 않습니다. 같은 수치를 되풀이하지 않습니다.")
                else:
                    request["comparison_value_placeholders"] = {k: "{{" + k + "}}" for k in comparison_keys}
                    requirements.append("comparison_value_placeholders는 검증된 완전 비교입니다. 직접 쓰기 어려운 수치는 해당 자리표시자로 인용하고 바깥에서 같은 금액·증감 표현을 반복하지 않습니다.")
    if selection.reason in {"quarterly", "restatement"} and not request.get("verified_sentence_examples"):
        request["verified_sentence_examples"] = [item["verified_sentence"] for item in request["evidence"].values()
                                                  if isinstance(item, dict) and item.get("verified_sentence")]
    if result is not None and settings.strict_news and result.news.admission:
        request["news_admission"] = {"NEWS_" + str(a.article_id): {"relation": a.relation,
                                    "subject_quote": a.subject_quote, "support_quote": a.support_quote}
                                    for a in result.news.admission.assessments if a.accepted and "NEWS_" + str(a.article_id) in evidence}
    for attempt in range(2):
        if request.get("outlook_answer_context"):
            from src.agents.outlook import GENERATION_INSTRUCTION, generation_request
            instruction,model_request=GENERATION_INSTRUCTION,generation_request(request)
        else:
            instruction,model_request=CHAT_INSTRUCTION,request
        payload = _invoke(settings, instruction, model_request, 1200, temperature=CHAT_TEMPERATURE)
        try:
            response = _check_answer(payload, evidence, required, result, request, settings, text)
        except AppError as error:
            if error.code not in {"chat_answer", "chat_evidence", "chat_numbers", "chat_voice",
                                  "chat_directness", "chat_claim", "chat_grounding", "chat_length",
                                  "chat_scope", "chat_comparison_style", "chat_time_basis", "chat_issues", "chat_repetition", "chat_outlook_scope"}:
                raise
            from src.diagnostics import record_validation_failure
            record_validation_failure("chat_answer", payload, evidence, error, question=text)
            if attempt:
                fallback = _metric_fallback(text, required, attachments, evidence)
                if fallback is not None:
                    return fallback
                if limited_on_failure:
                    fallback = _verified_fallback(text, evidence, request)
                    if fallback is not None:
                        return fallback
                raise
            _apply_retry_feedback(request, payload, error)
            continue
        follow = resolve_follow_up(payload.get("follow_up", ""), messages, result, discovery)
        intro = response.intro
        notices=()
        if any(item.get("kind") in {"image", "pdf"} for item in attachments or []):
            notice="첨부한 이미지·PDF의 본문은 현재 읽을 수 없습니다. 확인할 내용을 글이나 txt 파일로 입력해 주세요."
            if parse_presentation(text).max_sentences:
                notices=(notice,)
            else:
                intro+='\n\n'+notice
        return replace(response, intro=humanize_amounts(strip_habitual_caveats(intro)), follow_up=follow, notices=notices)
    raise AppError("chat_answer", "답변을 확인하지 못했습니다. 다시 질문해 주세요.")


def _canonical_block(block):
    if not isinstance(block,dict):
        raise AppError('chat_answer','이슈 설명 형식을 확인하지 못했습니다.')
    keys=set(block)-{'implication'}
    if keys=={'title','text','evidence_ids'}:
        return block
    if keys=={'headline','summary','evidence_ids'}:
        return {'title':block['headline'],'text':block['summary'],'evidence_ids':block['evidence_ids'],
                **({'implication':block['implication']} if 'implication' in block else {})}
    raise AppError('chat_answer','이슈 설명 형식을 확인하지 못했습니다.')


def validate_response(payload: dict, evidence: dict[str, dict], style: str, question: str = "", candidates: tuple = (), theme: str = "") -> ChatResponse:
    """블록마다 값·문체·허용 근거를 검사한 후 의미 검증에 전달한다."""
    if style == "company_cards":
        from src.agents.company_cards import validate_company_cards
        return validate_company_cards(payload, evidence, candidates=candidates, question=question, theme=theme)
    if isinstance(payload, dict) and "company_cards" in payload:
        raise AppError("chat_answer", "질문에 맞는 답변 구성을 확인하지 못했습니다.")
    if not isinstance(payload, dict) or set(payload) not in (
        {"text", "evidence_ids", "follow_up"}, {"text", "evidence_ids", "follow_up", "blocks"}
    ):
        raise AppError("chat_answer", "답변 형식을 확인하지 못했습니다.")
    raw_blocks = payload.get("blocks", [])  # 이전 저장/호출자의 단문 계약 호환
    if not isinstance(raw_blocks, list) or len(raw_blocks) > 3 or (raw_blocks and style != "issues"):
        raise AppError("chat_answer", "질문에 맞는 답변 구성을 확인하지 못했습니다.")
    intro, used = validate_answer({k: payload[k] for k in ("text", "evidence_ids", "follow_up")}, evidence, theme=theme, question=question, displayed_issue_count=len(raw_blocks) if style == "issues" else None)
    blocks = []
    groups=group_issues(evidence)
    by_source={key:g for g in groups for key in g.evidence_ids}
    seen = {re.sub(r"\W", "", intro)}
    for block in raw_blocks:
        block=_canonical_block(block)
        title, body, ids = block["title"], block["text"], block["evidence_ids"]
        implication=block.get('implication')
        if implication is not None and (not isinstance(implication,str) or len(implication)>600):
            raise AppError('chat_answer','이슈 영향 해석의 형식을 확인하지 못했습니다.')
        implication=implication.strip() if implication else None
        if not isinstance(title, str) or not title.strip() or len(title) > 100 or "\n" in title or not isinstance(body, str) or len(body) > 2000 or not ids:
            raise AppError("chat_answer", "이슈 제목·설명·근거가 올바르지 않습니다.")
        checked_title, refs = validate_answer({"text": title, "evidence_ids": ids, "follow_up": ""}, evidence, question=question)
        checked_body, _ = validate_answer({"text": body, "evidence_ids": ids, "follow_up": ""}, evidence, question=question)
        if implication:
            implication,_=validate_answer({'text':implication,'evidence_ids':ids,'follow_up':''},evidence,question=question)
            if re.sub(r'\W','',implication)==re.sub(r'\W','',checked_body):
                raise AppError('chat_directness','본문과 영향 해석을 반복했습니다.')
        title_key, body_key = re.sub(r"\W", "", checked_title), re.sub(r"\W", "", checked_body)
        if title_key == body_key or body_key in seen or any(b.title == checked_title for b in blocks):
            raise AppError("chat_directness", "이슈 제목이나 설명을 반복했습니다.")
        seen.add(body_key)
        owner_ids={by_source[key].issue_id for key in ids if key in by_source}
        if len(owner_ids)==1:
            group=next(g for g in groups if g.issue_id in owner_ids)
            ids=list(dict.fromkeys([*group.evidence_ids,*ids]))[:16]
            refs=[dict(evidence[key],id=key) for key in ids]
        blocks.append(AnswerBlock(checked_title, checked_body, tuple(ids), implication))
        used.extend(r for r in refs if r["id"] not in {e["id"] for e in used})
    response = ChatResponse(intro, used, payload["follow_up"], tuple(blocks), tuple(payload["evidence_ids"]))
    if blocks and groups:
        validate_issue_cards(response,evidence,groups)
    if len(response.text) > 3500:
        raise AppError("chat_answer", "답변이 너무 깁니다.")
    return response


def validate_answer(payload: dict, evidence: dict[str, dict], theme: str = "", question: str = "", *, displayed_issue_count: int | None = None) -> tuple[str, list[dict]]:
    if not isinstance(payload, dict) or set(payload) != {"text", "evidence_ids", "follow_up"} or not isinstance(payload["follow_up"], str):
        raise AppError("chat_answer", "답변 형식을 확인하지 못했습니다.")
    ids = payload["evidence_ids"]
    if not isinstance(ids, list) or len(ids) > 16 or any(not isinstance(i, str) or i not in evidence for i in ids) or len(set(ids)) != len(ids):
        raise AppError("chat_evidence", "답변 근거가 수집한 자료와 일치하지 않습니다.")
    answer = payload["text"]
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 3500:
        raise AppError("chat_answer", "답변이 비어 있거나 너무 깁니다.")
    answer = answer.strip()
    if re.search(r"\]\s*\(|<\s*/?\s*[A-Za-z][^>]*>", answer):
        raise AppError("chat_evidence", "출처 링크는 수집한 근거에서만 표시합니다.")
    if re.search(r"현재\s*\{\{(?:PER|PBR|ROE|EPS|BPS)\}\}\s*[은는]\s", answer):
        raise AppError("chat_directness","값으로 지표 이름을 대신했습니다.")
    placeholders = re.findall(r"\{\{([A-Z0-9_a-z-]+)\}\}", answer)
    for key in placeholders:
        if key not in ids or not evidence[key].get("value_text"):
            raise AppError("chat_evidence", "값 자리표시자의 근거를 확인할 수 없습니다.")
    remainder = re.sub(r"\{\{[A-Z0-9_a-z-]+\}\}", "", answer)
    number_check = re.sub(r"(?m)^\s*\d+[.)]\s+", "", answer).replace("1주당", "주당")
    from src.agents.presentation import mask_displayed_issue_count
    number_check = mask_displayed_issue_count(number_check, displayed_issue_count)
    from src.agents.financial_numbers import mask_verified_comparisons
    from src.agents.news_numbers import mask_verified_news
    from src.agents.quarterly import mask_quarterly_numbers
    number_check = mask_quarterly_numbers(number_check, {key: evidence[key] for key in ids})
    number_check = mask_verified_news(number_check, {key:evidence[key] for key in ids})
    number_check = mask_verified_comparisons(number_check, {key: evidence[key] for key in ids})
    number_check = re.sub(r"\{\{[A-Z0-9_a-z-]+\}\}", "", number_check)
    number_check = re.sub(r"(?<![\d.])(?:[1-9]\s*(?:가지|번째|차|단계)|[1-5]\s*개년)(?![가-힣])", "", number_check)
    from src.agents.literal_numbers import mask_literal_source_numbers
    number_check = mask_literal_source_numbers(number_check, {key: evidence[key] for key in ids})
    from src.agents.literal_numbers import mask_data_basis_terms, mask_evidence_years, mask_history_facts, mask_question_quarters, mask_relative_years
    number_check = mask_relative_years(number_check)
    number_check = mask_question_quarters(number_check, question, evidence=evidence)
    number_check = mask_evidence_years(number_check, {key: evidence[key] for key in ids}, remainder)
    number_check = mask_history_facts(number_check, {key: evidence[key] for key in ids})
    number_check = mask_data_basis_terms(number_check, {key: evidence[key] for key in ids})
    for context_str in (theme, question):
        if context_str:
            for term in re.findall(r"[A-Za-z가-힣0-9]+", context_str):
                if (re.search(r"\d", term) and re.search(r"[A-Za-z가-힣]", term)
                        and not re.fullmatch(r"\d+(?:(?:천|만|억|조)?(?:원|배)|퍼센트|년|월|일|주|명|건|개)", term)):
                    number_check = re.sub(re.escape(term), "", number_check, flags=re.IGNORECASE)
    # 매출 증가율과 영업이익 증가율의 배수 관계(예: 4배 빠르게 증가)가 계산값과 일치하면 허용한다.
    cmp_rates = {
        evidence[k].get("item"): float(evidence[k]["change_pct"])
        for k in ids
        if evidence[k].get("kind") == "annual_comparison" and evidence[k].get("change_pct") is not None
    }
    if "revenue" in cmp_rates and "operating_income" in cmp_rates and cmp_rates["revenue"] != 0:
        ratio = abs(cmp_rates["operating_income"] / cmp_rates["revenue"])
        for candidate_ratio in {f"{ratio:.0f}", f"{ratio:.1f}", f"{ratio:.2f}"}:
            if float(candidate_ratio) == round(ratio, 2):
                number_check = re.sub(rf"(?<![\d.]){re.escape(candidate_ratio)}\s*배\s*(?:빠르게|높게|크게|이상)", "", number_check)
    # 모델이 원자료의 값을 직접 쓴 경우에도 단위와 선택한 근거의 값이 같아야 한다.
    # 문장 의미와 값의 연결은 아래의 독립 근거 검사에서 다시 확인한다.
    expected = {"PRICE": "원", "PER": "배", "PBR": "배", "EPS": "원", "BPS": "원", "ROE": "%"}
    multiple_vals = []
    for key in ids:
        item = evidence[key]
        unit_name = expected.get(key) or item.get("unit")
        if unit_name == "배" and item.get("status") == "ok" and item.get("value") is not None:
            multiple_vals.append(float(item["value"]))

    def checked_number(match):
        numeric = float(match.group(1).replace(",", ""))
        unit = match.group(2)
        for key in ids:
            item = evidence[key]
            item_unit = expected.get(key) or item.get("unit")
            if item_unit == unit and item.get("status") == "ok" and item.get("value") is not None and round(float(item["value"]), 2) == numeric:
                return ""
        if unit == "배" and len(multiple_vals) >= 2:
            for idx_a, val_a in enumerate(multiple_vals):
                for val_b in multiple_vals[idx_a + 1:]:
                    if round(abs(val_a - val_b), 2) == numeric:
                        return ""
        return match.group(0)

    number_check = re.sub(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(원|배|%)(?!p)", checked_number, number_check)
    if re.search(r"\d|https?://|www\.", number_check):
        error = AppError("chat_numbers", "본문 수치는 확인된 값 자리표시자로 표시해야 합니다.")
        # 재시도 때 모델이 어느 문구를 고쳐야 하는지 알 수 있도록, 숫자를 가린 앞뒤 문맥만 남긴다(내부 전용).
        error.leftover_contexts = [
            re.sub(r"\d[\d,.]*", "□", number_check[max(0, m.start() - 12):m.end() + 12]).strip()
            for m in list(re.finditer(r"\d[\d,.]*", number_check))[:4]]
        raise error
    if re.search(r"(?:해요|예요|이에요|있어요|없어요|볼까요|뜻이야|상황이야|한다|된다)[.!?。！？]*(?:\s|$)", remainder):
        raise AppError("chat_voice", "정중한 입니다·합니다체로 작성해야 합니다.")
    # 소수점을 문장 경계로 자르면 서로 다른 재무 수치가 동일한 조각으로 오인된다.
    sentence_parts = [v.strip() for v in sentences(remainder) if len(v.strip()) > 8]
    if len(sentence_parts) != len(set(sentence_parts)) or re.fullmatch(r".*(?:알려드리겠습니다|설명하겠습니다)[.! ]*", remainder):
        raise AppError("chat_directness", "답변을 예고하거나 같은 설명을 반복했습니다.")
    if re.search(r"사세요|파세요|담으세요|매수하세요|매도하세요|수익을?\s*보장", remainder) or asserts_valuation(remainder) or wrong_per_formula(remainder):
        raise AppError("chat_claim", "근거 없는 가치 단정 또는 잘못된 설명을 확인했습니다.")
    # 현재 수집 계약에는 업종 평균·시장 순위가 없다. 비교 필요성·유보 고지는 허용한다.
    has_benchmark_evidence = any("평균" in str(evidence[k].get("text", "")) or "PEER" in k or "AVG" in k for k in ids)
    if not has_benchmark_evidence:
        for sent in re.split(r"[.!?\n]+", remainder):
            if re.search(r"평균[’'\"\s]*(?:수준)?.{0,12}(?:가깝|비슷|높습니다|낮습니다|상회|하회)", sent):
                if not re.search(r"단정|알\s*수\s*없|어렵|필요|유보|보류|확인할\s*수\s*없|않|아니|없어", sent):
                    raise AppError("chat_grounding", "수집하지 않은 평균과 비교했습니다.")
    # 미수집 원인은 의미 검사에서도 대조한다. 비교 기준·세부 자료 미제공 한계 고지는 허용한다.
    if re.search(r"(?:공시하지|제공하지|지원하지).*(?:때문|않아서|않아)|(?:공개|공시)되지\s*않(?:아|아서|았기\s*때문에|은\s*(?:것으로|이유))|(?:BPS|주당순자산).*(?:없어서|없기 때문에).*계산", remainder):
        raise AppError("chat_grounding", "누락의 원인을 자료 없이 추측했습니다.")
    for match in re.finditer(r"제공되지\s*않아", remainder):
        prefix = remainder[max(0, match.start() - 25):match.start()]
        if not re.search(r"평균|비교|밴드|추이|동종|업계|업종|본문|세부|부문|원문|원인|자료", prefix):
            raise AppError("chat_grounding", "누락의 원인을 자료 없이 추측했습니다.")
    for key in placeholders:
        value = evidence[key]["value_text"]
        marker = "{{" + key + "}}"
        unit = re.search(r"(원|배|%|주)$", value)
        if unit:
            answer = re.sub(re.escape(marker) + r"\s*" + re.escape(unit.group(1)), lambda _: value, answer)
        answer = answer.replace(marker, value)
    return fix_won_particles(answer), [dict(evidence[i], id=i) for i in ids]
