"""다양한 테마(자동차, 바이오, 로봇, 조선 등) 실서버 품질 검증 스크립트."""
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


def test_theme(theme_name: str, question: str):
    settings = load_settings()
    print("=" * 70)
    print(f"테마 검증: [{theme_name}] - 질문: '{question}'")
    print("=" * 70)
    t0 = time.time()
    disc = discover_theme_candidates(theme_name, settings=settings)
    dt_disc = time.time() - t0
    cands_str = ", ".join(f"{s.name}({s.code})" for s in disc.candidates)
    print(f"[후보 제안 및 상장 대조] ({dt_disc:.2f}s): {cands_str}")

    t1 = time.time()
    enriched = enrich_discovery(disc, settings)
    dt_enrich = time.time() - t1
    profiles_count = len(getattr(enriched, "business_profiles", ()))
    sources_count = len(getattr(enriched, "business_sources", ()))
    print(f"[공식 사업자료 보강] ({dt_enrich:.2f}s): KIND={profiles_count}개, DART/공식={sources_count}개")

    t2 = time.time()
    resp = discovery_answer(question, enriched, settings, as_cards=True, latest=False)
    dt_resp = time.time() - t2
    total_time = time.time() - t0

    intro = getattr(resp, "intro", getattr(resp, "text", str(resp)))
    cards = getattr(resp, "company_cards", ())
    ev = getattr(resp, "evidence", ())

    print(f"[카드 생성 및 검증] ({dt_resp:.2f}s) - 총 소요시간: {total_time:.2f}s")
    print(f"도입부: {intro}")
    print(f"생성된 카드 수: {len(cards)}개")

    cards_info = []
    for card in cards:
        print(f"\n  * [{card.stock_name} ({card.stock_code})]")
        card_secs = []
        for sec in card.sections:
            print(f"    - [{sec.role}]: {sec.text} (근거: {sec.evidence_ids})")
            card_secs.append({"role": sec.role, "text": sec.text, "eids": sec.evidence_ids})
        cards_info.append({"name": card.stock_name, "code": card.stock_code, "sections": card_secs})

    return {
        "theme": theme_name,
        "question": question,
        "candidates": [{"name": s.name, "code": s.code} for s in disc.candidates],
        "total_elapsed_sec": round(total_time, 2),
        "enrich_elapsed_sec": round(dt_enrich, 2),
        "answer_elapsed_sec": round(dt_resp, 2),
        "intro": intro,
        "card_count": len(cards),
        "cards": cards_info,
        "evidence_count": len(ev),
    }


def main():
    test_themes = [
        ("자동차", "자동차 관련 기업 알려줘"),
        ("바이오", "바이오 제약 관련 기업 알려줘"),
        ("로봇", "로봇 관련 유망 기업 알려줘"),
        ("조선", "조선 해운 관련 기업 알려줘"),
    ]

    results = {}
    for theme_name, question in test_themes:
        try:
            res = test_theme(theme_name, question)
            results[theme_name] = res
        except Exception as e:
            import traceback
            traceback.print_exc()
            results[theme_name] = {"error": str(e)}

    out_file = ROOT / "docs" / "검수" / "계획8_02E_다양한테마_검수결과_2026-10-30.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[기록 완료] {out_file}")


if __name__ == "__main__":
    main()
