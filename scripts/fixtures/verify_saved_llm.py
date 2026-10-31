"""저장 가상 답변의 기대 근거를 오프라인 대조한다. 모델을 호출하지 않는다."""
import argparse
import json
from pathlib import Path
from evaluation_contract import load_suite, assess_contract, DEFAULT_SUITE


def evaluate_suite(suite):
    cases = []
    for case in suite["cases"]:
        result = assess_contract(case["answer"], case["contract"])
        cases.append({"id": case["id"], "expected_status": case["expected_status"],
                      "contract_check": result, "matches_expected": result["status"] == case["expected_status"],
                      "provenance": case["provenance"]})
    return {"synthetic_data": True, "model_calls": 0, "cases": cases,
            "suite_passed": all(case["matches_expected"] for case in cases),
            "note": "기대 근거 계약만 검사했습니다. 실제 모델의 의미 정확성 합격이 아닙니다."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("기존 평가 기록을 덮어쓰지 않습니다.")
    result = evaluate_suite(load_suite(args.suite))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(result["cases"]), "suite_passed": result["suite_passed"], "model_calls": 0}))
    return 0 if result["suite_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
