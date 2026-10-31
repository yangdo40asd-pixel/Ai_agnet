"""실제 오승인 저장 원문과 정상 대조의 기대 근거를 외부 호출 없이 검사한다."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluation_contract import load_suite, assess_contract
from verify_saved_llm import evaluate_suite


class SavedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.suite = load_suite()

    def test_saved_wrong_answers_fail_and_valid_answers_keep_their_references(self):
        with patch("socket.socket.connect", side_effect=AssertionError("no network")):
            result = evaluate_suite(self.suite)
        self.assertTrue(result["suite_passed"])
        self.assertEqual(result["model_calls"], 0)
        wrong = next(c for c in result["cases"] if c["id"] == "mixed_latest_wrong")
        self.assertIn("forbidden_references:NEWS_2", wrong["contract_check"]["violations"])
        self.assertEqual(wrong["contract_check"]["semantic_quality"], "unverified")

    def test_original_records_are_not_rewritten_and_hashes_match(self):
        root = Path(__file__).resolve().parents[1]
        for case in self.suite["cases"]:
            source = root / case["provenance"]["file"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), case["provenance"]["sha256"])

    def test_references_in_blocks_cannot_hide_behind_valid_intro(self):
        case = deepcopy(self.suite["cases"][0])
        case["answer"]["evidence_ids"] = []
        case["answer"]["blocks"] = [{"evidence_ids": ["NEWS_2"]}]
        self.assertEqual(assess_contract(case["answer"], case["contract"])["status"], "failed")

    def test_missing_one_requested_scope_is_not_a_complete_answer(self):
        contract = self.suite["live_contracts"]["mixed"]
        answer = {"evidence_ids": contract["required_groups"]["financial"], "blocks": []}
        result = assess_contract(answer, contract)
        self.assertIn("missing_group:news", result["violations"])

    def test_unknown_and_malformed_ids_are_rejected(self):
        contract = self.suite["live_contracts"]["mixed"]
        for answer in ({"evidence_ids": ["invented"]}, {"evidence_ids": "NEWS_1"}, {"blocks": [None]}, {"blocks": {}}):
            with self.subTest(answer=answer):
                self.assertEqual(assess_contract(answer, contract)["status"], "failed")

    def test_contract_uses_supplied_target_ids_not_literal_company_or_article_numbers(self):
        for case in self.suite["cases"]:
            changed = deepcopy(case)
            mapping = {key: "holdout_" + str(index) for index, key in enumerate(case["contract"]["allowed_ids"])}
            answer = changed["answer"]
            answer["text"] = "이름과 표현을 변경한 대조입니다."
            for part in [answer, *answer.get("blocks", [])]:
                part["evidence_ids"] = [mapping[k] for k in part.get("evidence_ids", [])]
            contract = changed["contract"]
            contract["allowed_ids"] = [mapping[k] for k in contract["allowed_ids"]]
            contract["forbidden_ids"] = [mapping[k] for k in contract["forbidden_ids"]]
            contract["required_groups"] = {name: [mapping[k] for k in ids] for name, ids in contract["required_groups"].items()}
            self.assertEqual(assess_contract(answer, contract)["status"], case["expected_status"])
