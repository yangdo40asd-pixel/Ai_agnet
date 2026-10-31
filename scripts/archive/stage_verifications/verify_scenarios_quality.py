"""다양한 실사용 시나리오별 실제 답변 품질 및 02-C/02-D 부합성 정밀 검증 스크립트."""
import io
import json
from pathlib import Path
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.pipeline import discover_theme_candidates
from src.discovery_flow import enrich_discovery
from src.agents.discovery_answer import discovery_answer
from src.agents.chat import answer_question
from src.models import StockCandidate, now_kst


def run_scenarios():
    settings = load_settings()
    results = {}

    print("=" * 70)
    print("02-C & 02-D 다양한 실사용 시나리오 정밀 품질 검증")
    print("=" * 70)

    # =========================================================================
    # [시나리오 1] 다른 테마 탐색: 2차전지 ("2차전지 관련 기업 알려줘")
    # 검증 포인트: 배터리 완제품 셀 제조(LG엔솔, 삼성SDI) vs 양극재 소재 제조(에코프로비엠) 구분
    # =========================================================================
    print("\n" + "#" * 60)
    print("[시나리오 1] 다른 테마(2차전지) 최초 탐색 답변 품질 검증")
    print("#" * 60)
    q1 = "2차전지 관련 기업 알려줘"
    disc_battery = discover_theme_candidates("2차전지")
    enriched_battery = enrich_discovery(disc_battery, settings)
    t0 = time.time()
    resp_battery = discovery_answer(q1, enriched_battery, settings, as_cards=True, latest=False)
    dt1 = time.time() - t0

    print(f"질문: '{q1}' (소요시간: {dt1:.2f}s)")
    print(f"도입부: {resp_battery.intro}")
    print(f"생성된 카드 수: {len(resp_battery.company_cards)}개")
    cards_battery_data = []
    for card in resp_battery.company_cards:
        print(f"\n[{card.stock_name} ({card.stock_code})]")
        card_secs = []
        for sec in card.sections:
            print(f"  - [{sec.role}]: {sec.text} (근거: {sec.evidence_ids})")
            card_secs.append({"role": sec.role, "text": sec.text, "eids": sec.evidence_ids})
        cards_battery_data.append({"name": card.stock_name, "code": card.stock_code, "sections": card_secs})

    results["scenario_1_battery"] = {
        "question": q1,
        "elapsed_sec": round(dt1, 2),
        "intro": resp_battery.intro,
        "cards": cards_battery_data,
    }

    # =========================================================================
    # [시나리오 2] 후보 기업 확장 탐색: "관련주 더 보여줘"
    # 검증 포인트: 반도체 테마에서 추가 후보(4~5번째 종목)에 대해 독립적인 카드 생성
    # =========================================================================
    print("\n" + "#" * 60)
    print("[시나리오 2] 테마 관련주 확장('관련주 더 보여줘') 답변 품질 검증")
    print("#" * 60)
    disc_semi_prev = discover_theme_candidates("반도체")
    # previous 전달하여 새 후보 확장
    disc_semi_exp = discover_theme_candidates("반도체", previous=disc_semi_prev)
    enriched_semi_exp = enrich_discovery(disc_semi_exp, settings)
    q2 = "관련주 더 보여줘"
    t0 = time.time()
    resp_semi_exp = discovery_answer(q2, enriched_semi_exp, settings, as_cards=True, latest=True)
    dt2 = time.time() - t0

    print(f"질문: '{q2}' (소요시간: {dt2:.2f}s)")
    print(f"도입부: {resp_semi_exp.intro}")
    print(f"생성된 카드 수: {len(resp_semi_exp.company_cards)}개")
    cards_exp_data = []
    for card in resp_semi_exp.company_cards:
        print(f"\n[{card.stock_name} ({card.stock_code})]")
        card_secs = []
        for sec in card.sections:
            print(f"  - [{sec.role}]: {sec.text} (근거: {sec.evidence_ids})")
            card_secs.append({"role": sec.role, "text": sec.text, "eids": sec.evidence_ids})
        cards_exp_data.append({"name": card.stock_name, "code": card.stock_code, "sections": card_secs})

    results["scenario_2_expansion"] = {
        "question": q2,
        "elapsed_sec": round(dt2, 2),
        "intro": resp_semi_exp.intro,
        "cards": cards_exp_data,
    }

    # =========================================================================
    # [시나리오 3] 카드 확인 후 개별 기업 심층 질문: "한미반도체는 무슨 장비를 만들어?"
    # 검증 포인트: 02-C 규칙에 따라 카드를 강제하지 않고, 해당 기업 장비에 집중한 직결 답변 반환
    # =========================================================================
    print("\n" + "#" * 60)
    print("[시나리오 3] 특정 기업 심층 질의(카드 미강제 및 장비 직결) 품질 검증")
    print("#" * 60)
    q3 = "한미반도체는 어떤 반도체 장비를 주로 생산하는지 구체적으로 알려줘"
    # 한미반도체 대화 문맥 구성
    hanmi_stock = StockCandidate("한미반도체", "042700", "KOSPI", "042700.KS")
    # 한미반도체 사업 근거 선택
    hanmi_sources = [s for s in enriched_semi_exp.business_sources if s.stock_code == "042700"]
    if not hanmi_sources:
        # 반도체 초기 후보에서 가져오기
        enriched_semi_init = enrich_discovery(disc_semi_prev, settings)
        hanmi_sources = [s for s in enriched_semi_init.business_sources if s.stock_code == "042700"]

    enriched_semi_init = enrich_discovery(disc_semi_prev, settings)
    from src.models import AnalysisResult, FinancialData, NewsData
    dummy_fin = FinancialData(hanmi_stock, 100000, 30.0, now_kst())
    dummy_news = NewsData((), now_kst())
    analysis_hanmi = AnalysisResult("반도체", (hanmi_stock,), dummy_fin, dummy_news, None, result_id="hanmi-deep-eval")

    t0 = time.time()
    resp_hanmi = discovery_answer(
        q3,
        enriched_semi_init,
        settings,
        as_cards=True,
    )
    dt3 = time.time() - t0

    resp_text = resp_hanmi.intro
    resp_ev = resp_hanmi.evidence if hasattr(resp_hanmi, "evidence") else resp_hanmi[1]
    resp_cards = getattr(resp_hanmi, "company_cards", ())

    print(f"질문: '{q3}' (소요시간: {dt3:.2f}s)")
    print(f"답변 형식: company_cards={len(resp_cards)}개")
    print(f"실제 도입부:\n{resp_text}")
    for card in resp_cards:
        print(f"\n[{card.stock_name} ({card.stock_code})]")
        for sec in card.sections:
            print(f"  - [{sec.role}]: {sec.text}")
    print(f"인용된 근거 수: {len(resp_ev)}개")

    results["scenario_3_deep_company"] = {
        "question": q3,
        "elapsed_sec": round(dt3, 2),
        "has_cards": bool(resp_cards),
        "card_count": len(resp_cards),
        "text": resp_text,
        "evidence_count": len(resp_ev),
    }

    # =========================================================================
    # [시나리오 4] 초보자용 핵심 요약 제약: "초보자가 이해하기 쉽게 한 문장씩만 핵심 요약해줘"
    # 검증 포인트: 각 카드당 1문장 내외로 초보자 눈높이의 명확한 역할 압축
    # =========================================================================
    print("\n" + "#" * 60)
    print("[시나리오 4] 초보자용 분량 제약('한 문장씩만 핵심 요약해줘') 답변 품질 검증")
    print("#" * 60)
    q4 = "초보자가 이해하기 쉽게 한 문장씩만 핵심 요약해줘"
    enriched_semi_init = enrich_discovery(disc_semi_prev, settings)
    t0 = time.time()
    resp_short = discovery_answer(q4, enriched_semi_init, settings, as_cards=True, latest=False)
    dt4 = time.time() - t0

    print(f"질문: '{q4}' (소요시간: {dt4:.2f}s)")
    print(f"도입부: {resp_short.intro}")
    print(f"생성된 카드 수: {len(resp_short.company_cards)}개")
    cards_short_data = []
    for card in resp_short.company_cards:
        print(f"\n[{card.stock_name} ({card.stock_code})]")
        card_secs = []
        for sec in card.sections:
            print(f"  - [{sec.role}]: {sec.text}")
            card_secs.append({"role": sec.role, "text": sec.text})
        cards_short_data.append({"name": card.stock_name, "code": card.stock_code, "sections": card_secs})

    results["scenario_4_concise"] = {
        "question": q4,
        "elapsed_sec": round(dt4, 2),
        "intro": resp_short.intro,
        "cards": cards_short_data,
    }

    # 파일 저장
    out_path = ROOT / "docs" / "검수" / "계획8_02CD_상황별품질_검수결과_2026-10-30.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[기록 완료] {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    run_scenarios()
