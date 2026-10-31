"""가상 검수 전용 기대 계약. 출처 ID 대조는 의미 정확성의 증명이 아니다."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == "fixtures" else Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "tests/fixtures/local_relevance_regressions.json"


def load_suite(path=DEFAULT_SUITE):
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    if suite.get("synthetic_data") is not True or suite.get("version") != 1:
        raise ValueError("명시적으로 버전이 지정된 가상 검수 자료만 사용합니다.")
    return suite


def assess_contract(answer, contract):
    """사람이 지정한 가상 입력의 허용·금지·필수 근거를 대조한다."""
    violations = []
    used = set()
    if not isinstance(answer, dict):
        return {"status": "failed", "violations": ["invalid_answer"], "semantic_quality": "unverified"}
    sections = [answer, *answer.get("blocks", [])] if isinstance(answer.get("blocks", []), list) else []
    if not sections:
        violations.append("invalid_blocks")
    for section in sections:
        ids = section.get("evidence_ids", []) if isinstance(section, dict) else None
        if not isinstance(ids, (list, tuple)) or any(not isinstance(key, str) for key in ids):
            violations.append("invalid_references")
            continue
        used.update(ids)
    unknown = used - set(contract["allowed_ids"])
    forbidden = used & set(contract.get("forbidden_ids", []))
    if unknown:
        violations.append("unknown_references:" + ",".join(sorted(unknown)))
    if forbidden:
        violations.append("forbidden_references:" + ",".join(sorted(forbidden)))
    for group, ids in contract.get("required_groups", {}).items():
        if not set(ids).issubset(used):
            violations.append("missing_group:" + group)
    return {"status": "failed" if violations else "passed", "violations": violations,
            "used_ids": sorted(used), "semantic_quality": "unverified"}


def live_contract(case_id):
    """이 도구의 고정 가상 입력에만 적용한다. 일반 앱 정책으로 사용하지 않는다."""
    return load_suite()["live_contracts"].get(case_id)


def validate_dataset(result):
    """검수용 실제 입력이 고정 기대 계약과 같은 자료 버전인지 확인한다."""
    dataset = load_suite()["dataset"]
    actual_news = [("NEWS_" + str(a.id), a.title) for a in result.news.articles]
    expected_news = [(a["id"], a["title"]) for a in dataset["news"]]
    if (result.target_code != dataset["stock_code"] or result.financial.stock.name != dataset["stock_name"]
            or result.theme != dataset["theme"] or actual_news != expected_news
            or sorted(int(a.bsns_year) for a in result.annual_summaries) != dataset["annual_years"]):
        raise ValueError("가상 입력 자료가 변경됐습니다. 기대 계약을 같은 자료 버전으로 먼저 갱신해 주세요.")
