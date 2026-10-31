"""복합 질문의 범위와 블록별 관련성 계약. 의미 모델의 정확성은 별도 실제 검수한다."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from llm_fixture import synthetic_result
from src.agents.answer_quality import select_evidence, failed_unit_reviews, QUALITY_CHECKS
from src.agents.chat import build_evidence, answer_question
from src.agents.chat import _check_answer, _direct_answer, _apply_retry_feedback
from src.agents.grounding import review_response
from src.agents.output_contract import response_format
from src.config import Settings
from src.models import AppError
from test_news_relevance import classification


class ScopedAnswers(unittest.TestCase):
    def setUp(self):
        self.result = synthetic_result()
        self.evidence = build_evidence(self.result)
        self.settings = Settings("", "", "", "", ai_provider="local", local_model="fixture", news_relevance_mode="strict")

    def test_mixed_selection_retains_both_scopes_without_unasked_metrics(self):
        selected = select_evidence("실적과 관련 뉴스를 함께 설명해 주세요.", [], self.evidence, [], strict=True)
        self.assertEqual(selected.reason, "mixed")
        self.assertEqual(len(selected.required_groups["financial"]["ids"]), 3)
        self.assertEqual(selected.required_groups["news"]["mode"], "any")
        self.assertNotIn("PBR", selected.evidence)
        self.assertNotIn("PRICE", selected.evidence)
        self.assertIn("NEWS_1", selected.evidence)

    def test_value_or_concept_shortcut_does_not_drop_the_news_half_of_a_strict_request(self):
        for text in ("주가와 뉴스를 알려줘", "PER 뜻과 뉴스를 알려줘"):
            with self.subTest(text=text):
                keys, required, direct = _direct_answer(text, self.result, None, self.evidence, strict=True)
                self.assertIsNone(direct)
        self.assertIsNotNone(_direct_answer("주가를 알려줘", self.result, None, self.evidence, strict=True)[2])

    def test_ambiguous_news_followup_does_not_become_an_unasked_financial_overview(self):
        selected = select_evidence("그러면 그 발표로 실적 개선이 확정된 건가요?",
                                  [{"role": "user", "text": "생산라인 뉴스는 무엇입니까?"}], self.evidence, [], strict=True)
        self.assertEqual(selected.reason, "news")
        self.assertIn("NEWS_1", selected.evidence)
        self.assertNotIn("PRICE", selected.evidence)
        self.assertFalse(any(key.startswith("CMP_") for key in selected.evidence))

    def test_no_admitted_news_keeps_financial_evidence_and_a_limited_news_status(self):
        evidence = {key: item for key, item in self.evidence.items() if not key.startswith("NEWS_") or key == "NEWS_STATUS"}
        selected = select_evidence("실적과 뉴스를 함께 설명해 주세요.", [], evidence, [], strict=True)
        self.assertEqual(selected.required_groups["news"]["ids"], ["NEWS_STATUS"])
        self.assertEqual(selected.evidence["NEWS_STATUS"]["admission_status"], "no_supported_articles")
        self.assertEqual(len(selected.required_groups["financial"]["ids"]), 3)
        self.assertNotIn("admission_status", self.evidence["NEWS_STATUS"])

    def test_one_scope_missing_is_rejected_before_an_approving_reviewer(self):
        payload = {"text": "수집된 뉴스 제목 기준입니다. 생산라인 가동 계획이 발표되었습니다.",
                   "evidence_ids": ["NEWS_1"], "follow_up": "", "blocks": []}
        with patch("src.agents.news_relevance._invoke", return_value=classification()), patch("src.agents.chat._invoke", return_value=payload) as invoke:
            with self.assertRaises(AppError) as caught:
                answer_question("실적과 관련 뉴스를 함께 설명해 주세요.", self.result, [], self.settings)
        self.assertEqual(caught.exception.code, "chat_scope")
        self.assertTrue(all(call.args[2]["task"] == "chat_answer" for call in invoke.call_args_list))

    def test_global_approval_cannot_override_a_relevance_failure_or_missing_fields(self):
        units = [{"id": "block_0_0", "evidence": {"NEWS_1": self.evidence["NEWS_1"]}}]
        verdict = {"unit_reviews": [{"id": "block_0_0", "reason": "자료는 맞지만 질문 대상이 다릅니다.",
                                    "supported": True, "on_topic": False, "relevance_evidence_ids": ["NEWS_1"]}],
                   "supported": True, "answers_question": True, "checks": dict.fromkeys(QUALITY_CHECKS, True)}
        self.assertEqual(failed_unit_reviews(verdict, units, require_relevance=True), ["block_0_0"])
        for field in ("on_topic", "relevance_evidence_ids"):
            bad = deepcopy(verdict)
            del bad["unit_reviews"][0][field]
            self.assertTrue(failed_unit_reviews(bad, units, require_relevance=True))
        verdict["unit_reviews"][0]["on_topic"] = True
        self.assertEqual(failed_unit_reviews(verdict, units, require_relevance=True), [])
        for refs in ([], ["NEWS_2"], ["NEWS_1", "NEWS_1"]):
            bad = deepcopy(verdict)
            bad["unit_reviews"][0]["relevance_evidence_ids"] = refs
            self.assertTrue(failed_unit_reviews(bad, units, require_relevance=True))

    def test_old_review_is_not_silently_accepted_as_scoped_v1(self):
        units = [{"id": "intro_0", "evidence": {}}]
        verdict = {"unit_reviews": [{"id": "intro_0", "reason": "기존 심사", "supported": True}]}
        self.assertEqual(failed_unit_reviews(verdict, units), [])
        self.assertEqual(failed_unit_reviews(verdict, units, require_relevance=True), ["intro_0"])
        fmt = response_format({"task": "chat_grounding_review", "review_profile": "scoped-v1", "review_units": units,
                               "evidence": {"NEWS_1": {}}}, "fixture", schema_supported=True)
        required = fmt["json_schema"]["schema"]["properties"]["unit_reviews"]["items"]["required"]
        self.assertIn("on_topic", required)
        self.assertIn("relevance_evidence_ids", required)

    def test_rates_contract_rejects_expanded_placeholder_before_semantic_call(self):
        ids = [k for k in self.evidence if k.startswith("CMP_")]
        evidence = {k: self.evidence[k] for k in ids}
        payload = {"text": "매출은 {{CMP_2024_2025_CFS_REVENUE}} 증가했습니다.", "evidence_ids": ids,
                   "follow_up": "", "blocks": []}
        request = {"answer_style": "plain", "comparison_style": "rates", "concept_reference": {}}
        with patch("src.agents.chat._invoke") as invoke, self.assertRaises(AppError) as caught:
            _check_answer(payload, evidence, [], self.result, request, self.settings, "실적")
        self.assertEqual(caught.exception.code, "chat_comparison_style")
        invoke.assert_not_called()

    def test_zero_missing_rate_and_mixed_bases_keep_full_comparison_format(self):
        from src.agents.financial_numbers import use_rate_sentences
        evidence = {k: deepcopy(v) for k, v in self.evidence.items() if k.startswith("CMP_")}
        self.assertTrue(use_rate_sentences(evidence))
        key = next(iter(evidence))
        for value in (0, "0.000", None, "NaN"):
            changed = deepcopy(evidence)
            changed[key]["change_pct"] = value
            self.assertFalse(use_rate_sentences(changed))
        changed = deepcopy(evidence)
        changed[key]["fs_div"] = "OFS"
        self.assertFalse(use_rate_sentences(changed))

    def test_saved_per_phrase_cannot_invent_current_earnings_period(self):
        from src.agents.knowledge import TERMS
        evidence = {"PER": self.evidence["PER"]}
        payload = {"text": "PER은 12.50배입니다. 해당 수치는 현재 시점의 이익을 바탕으로 산출된 것입니다.",
                   "evidence_ids": ["PER"], "follow_up": "", "blocks": []}
        request = {"answer_style": "plain", "concept_reference": {"PER": TERMS["PER"]}}
        with patch("src.agents.chat._invoke") as invoke, self.assertRaises(AppError) as caught:
            _check_answer(payload, evidence, ["PER"], self.result, request, self.settings, "PER")
        self.assertEqual(caught.exception.code, "chat_time_basis")
        invoke.assert_not_called()

    def test_scoped_retry_preserves_verified_evidence_without_replaying_rejected_answer(self):
        request = {"question": "이 종목 PER을 설명해 주세요.", "review_profile": "scoped-v1",
                   "evidence": {"PER": self.evidence["PER"]}}
        evidence = deepcopy(request["evidence"])
        rejected = {"text": "현재 시점의 이익을 바탕으로 산출했습니다.", "blocks": [{"title": "잘못된 기간", "text": "현재 이익 기준입니다."}]}
        _apply_retry_feedback(request, rejected, AppError("chat_time_basis", "기준 기간 미확인"))
        self.assertNotIn("rejected_answer", request)
        self.assertNotIn("rejected_blocks", request)
        self.assertEqual(request["evidence"], evidence)
        self.assertEqual(request["validation_error"], "chat_time_basis")
        self.assertIn("계산 이익 기간", request["validation_feedback"])

    def test_scoped_review_uses_ordered_units_once_and_retains_financial_footer(self):
        from src.models import ChatResponse
        refs = [dict(self.evidence[k], id=k) for k in self.evidence if k.startswith("CMP_")]
        response = ChatResponse("매출은 20% 증가했습니다.", refs, lead_evidence_ids=tuple(r["id"] for r in refs))
        request = {"question": "실적은?", "review_profile": "scoped-v1", "stock_name": self.result.financial.stock.name,
                   "theme": self.result.theme, "required_groups": {"financial": {"mode": "all", "ids": [r["id"] for r in refs]}}}
        with patch("src.agents.chat._invoke", return_value={}) as invoke:
            review_response(response, self.evidence, request, self.settings, invoke)
        sent = invoke.call_args.args[2]
        self.assertNotIn("answer", sent)
        self.assertEqual(sent["review_units"][0]["statement"], response.text)
        self.assertEqual(len(sent["displayed_data_sources"]), 3)
        self.assertEqual(sent["required_groups"], request["required_groups"])

    def test_k01_and_k03_position_variants_and_intro_dependency_on_excluded_claim_fail(self):
        from src.models import AnswerBlock, ChatResponse
        from src.agents.answer_quality import review_units
        good_block = AnswerBlock("생산라인 계획", "반도체 메모리 생산라인 가동 계획이 보도되었습니다.", ("NEWS_1",))
        bad_block = AnswerBlock("지주회사 소식", "지주회사 이사회 경영 강화 소식이 보도되었습니다.", ("NEWS_2",))
        fin_block = AnswerBlock("연간 실적", "매출은 20% 증가했고 영업이익은 80% 증가했습니다.", ("CMP_2024_2025_CFS_REVENUE",))

        # P6-K01: 앞(block_0)·중간(block_1)·뒤(block_2) 어디에 부적합 단위가 있어도 전체 총평 true로 덮이지 않고 거절된다.
        for blocks, bad_unit_id in (
            ((bad_block, good_block, fin_block), "block_0_0"),
            ((fin_block, bad_block, good_block), "block_1_0"),
            ((fin_block, good_block, bad_block), "block_2_0"),
        ):
            response = ChatResponse("수집된 뉴스 제목 기준입니다. 주요 소식을 요약합니다.", [], blocks=blocks, lead_evidence_ids=("NEWS_1",))
            units = review_units(response, self.evidence)
            unit_reviews = []
            for unit in units:
                is_bad = unit["id"] == bad_unit_id
                ev_keys = list(unit["evidence"])
                unit_reviews.append({
                    "id": unit["id"],
                    "reason": "대상 무관" if is_bad else "확인됨",
                    "supported": True,
                    "on_topic": not is_bad,
                    "relevance_evidence_ids": ev_keys[:1],
                })
            verdict = {
                "unit_reviews": unit_reviews,
                "supported": True,
                "answers_question": True,
                "checks": dict.fromkeys(QUALITY_CHECKS, True),
            }
            self.assertEqual(failed_unit_reviews(verdict, units, require_relevance=True), [bad_unit_id])

        # P6-K03: 부적합 블록(bad_block)을 제외했더라도 도입·결론(intro)이 여전히 제외된 주장에 기대어 미검증/무관 판정을 받으면 통과하지 않는다.
        partial_response = ChatResponse(
            "수집된 뉴스 제목 기준입니다. 생산라인 계획과 지주회사 이사회 경영 강화로 지배구조 개선이 기대됩니다.",
            [],
            blocks=(good_block,),
            lead_evidence_ids=("NEWS_1",),
        )
        partial_units = review_units(partial_response, self.evidence)
        partial_reviews = [
            {
                "id": u["id"],
                "reason": "제외된 지주회사 주장 포함" if u["id"] == "intro_1" else "확인됨",
                "supported": u["id"] != "intro_1",
                "on_topic": u["id"] != "intro_1",
                "relevance_evidence_ids": ["NEWS_1"],
            }
            for u in partial_units
        ]
        partial_verdict = {
            "unit_reviews": partial_reviews,
            "supported": True,
            "answers_question": True,
            "checks": dict.fromkeys(QUALITY_CHECKS, True),
        }
        self.assertEqual(failed_unit_reviews(partial_verdict, partial_units, require_relevance=True), ["intro_1"])

    def test_j04_multiturn_financial_per_news_and_stock_switch_preserve_scope_and_canvas(self):
        from dataclasses import replace
        from src.ui.state import add_canvas, get_result, store_analysis_result
        history = []

        # Turn 1: 재무 질문 (Stock A)
        sel_fin = select_evidence("2025년 매출과 영업이익을 보면 실적이 좋아진 거야?", history, self.evidence, [], strict=True)
        self.assertEqual(sel_fin.reason, "financials")
        self.assertEqual(len(sel_fin.required_groups["financial"]["ids"]), 3)
        history.extend([
            {"role": "user", "text": "2025년 매출과 영업이익을 보면 실적이 좋아진 거야?"},
            {"role": "assistant", "text": "실적이 개선되었습니다.", "result_target": {"code": "123456", "name": "가상검수회사"}},
        ])

        # Turn 2: PER 질문 (Stock A)
        sel_per = select_evidence("그럼 PER은 어떤 편이야?", history, self.evidence, ["PER"], strict=True)
        self.assertEqual(sel_per.reason, "metric")
        self.assertEqual(list(sel_per.evidence), ["PER"])
        history.extend([
            {"role": "user", "text": "그럼 PER은 어떤 편이야?"},
            {"role": "assistant", "text": "PER은 12.50배입니다.", "result_target": {"code": "123456", "name": "가상검수회사"}},
        ])

        # Turn 3: '그 발표' 후속 질문 (중간에 PER 턴이 끼어 있어도 뉴스 사건 범위로 정확히 연결)
        sel_news = select_evidence("그러면 그 발표로 실적 개선이 확정된 건가요?", history, self.evidence, [], strict=True)
        self.assertEqual(sel_news.reason, "news")
        self.assertIn("NEWS_1", sel_news.evidence)
        self.assertFalse(any(k.startswith("CMP_") for k in sel_news.evidence))
        history.extend([
            {"role": "user", "text": "그러면 그 발표로 실적 개선이 확정된 건가요?"},
            {"role": "assistant", "text": "제목만으로는 실적 반영이 확정되지 않았습니다.", "result_target": {"code": "123456", "name": "가상검수회사"}},
        ])

        # Turn 4: 다른 종목(Stock B) 전환 시 이전 종목(Stock A)의 캔버스 스냅샷은 유지되고 대화 문맥은 분리됨
        state = {}
        store_analysis_result(state, self.result, ("반도체", "123456"))
        add_canvas(state, self.result)
        stock_b = replace(self.result.financial.stock, code="654321", name="다른검수회사")
        result_b = replace(
            self.result,
            result_id="result-stock-b",
            financial=replace(self.result.financial, stock=stock_b),
        )
        store_analysis_result(state, result_b, ("반도체", "654321"))
        self.assertEqual(get_result(state, self.result.result_id).financial.stock.name, "가상검수회사")
        self.assertEqual(get_result(state, result_b.result_id).financial.stock.name, "다른검수회사")
        self.assertEqual(state["canvases"][0]["result"].financial.stock.code, "123456")

        from src.agents.chat import conversation_context
        scoped_ctx = conversation_context(history, result_b)
        self.assertEqual(scoped_ctx, [])

    def test_l01_and_l02_substituted_cmp_duplication_and_multi_base_consistency(self):
        from dataclasses import replace
        from src.models import AnnualFinancialSummary
        from src.ui.state import ensure_export_bundle
        from src.agents.chat import validate_response
        # P6-L01: comparison_style != "rates" (예: 복수 회계 기준)에서 {{CMP_...}} 치환 시 뒤에 '증가/상승'을 중복하면 거절된다.
        ids = [k for k in self.evidence if k.startswith("CMP_")]
        evidence = {k: self.evidence[k] for k in ids}
        dup_payload = {
            "text": "매출은 {{CMP_2024_2025_CFS_REVENUE}} 증가했습니다.",
            "evidence_ids": ["CMP_2024_2025_CFS_REVENUE"],
            "follow_up": "",
            "blocks": [],
        }
        request = {"answer_style": "plain", "concept_reference": {}}
        with patch("src.agents.chat._invoke") as invoke, self.assertRaises(AppError) as caught:
            _check_answer(dup_payload, evidence, [], self.result, request, self.settings, "실적")
        self.assertEqual(caught.exception.code, "chat_comparison_style")
        invoke.assert_not_called()

        clean_payload = {
            "text": "실적 비교 결과는 {{CMP_2024_2025_CFS_REVENUE}}입니다.",
            "evidence_ids": ["CMP_2024_2025_CFS_REVENUE"],
            "follow_up": "",
            "blocks": [],
        }
        checked = validate_response(clean_payload, evidence, "plain")
        self.assertNotIn("증가) 증가", checked.text)
        self.assertIn("2024년 100.0억원 → 2025년 120.0억원 (20.00% 증가)", checked.text)

        # P6-L02: 단일(CFS) 및 복수(CFS+OFS) 회계 기준에서 근거·캔버스·Excel 원자료 수치가 동일하게 유지된다.
        ofs_summaries = (
            *self.result.annual_summaries,
            replace(self.result.annual_summaries[0], fs_div="OFS", revenue=8_000_000_000, operating_income=1_000_000_000, net_income=800_000_000),
            replace(self.result.annual_summaries[1], fs_div="OFS", revenue=9_600_000_000, operating_income=1_800_000_000, net_income=1_400_000_000),
        )
        multi_result = replace(self.result, annual_summaries=ofs_summaries)
        multi_ev = build_evidence(multi_result)
        self.assertIn("CMP_2024_2025_CFS_REVENUE", multi_ev)
        self.assertIn("CMP_2024_2025_OFS_REVENUE", multi_ev)
        self.assertEqual(multi_ev["CMP_2024_2025_CFS_REVENUE"]["current"], "12000000000")
        self.assertEqual(multi_ev["CMP_2024_2025_OFS_REVENUE"]["current"], "9600000000")
        self.assertIn("80.0억원 → 2025년 96.0억원", multi_ev["CMP_2024_2025_OFS_REVENUE"]["value_text"])
        excel_bytes, excel_name = ensure_export_bundle({}, multi_result)
        self.assertTrue(len(excel_bytes) > 1000)
        self.assertTrue(excel_name.endswith(".xlsx"))

    def test_l04_context_budget_and_selection_preserve_required_evidence_and_sources(self):
        from src.agents.providers.local import estimate_context_budget
        from src.source_presentation import data_source_label
        selected = select_evidence("실적과 관련 뉴스를 함께 설명해 주세요.", [], self.evidence, [], strict=True)
        budget = estimate_context_budget([("system", "지시문"), ("user", str(selected.evidence))], max_tokens=2200, context_window=4096)
        self.assertTrue(budget["fits_context"])
        self.assertEqual(budget["reserved_output_tokens"], 2200)
        self.assertGreater(budget["input_chars"], 0)
        # 축소 후에도 필수 재무 비교 3개와 뉴스 근거 및 하단 표시 출처가 모두 유지된다.
        for req_id in selected.required_groups["financial"]["ids"]:
            self.assertIn(req_id, selected.evidence)
        sources = [data_source_label(dict(selected.evidence[k], id=k)) for k in selected.evidence if k != "NEWS_STATUS"]
        self.assertTrue(any("OpenDART" in str(s) for s in sources))
        self.assertTrue(any("NAVER" in str(s) or "뉴스" in str(s) for s in sources))

    def test_l07_http_timeout_and_total_turn_budget_are_distinguished(self):
        import time
        import httpx
        from src.agents.local_verification import turn_budget
        from src.agents.providers.local import invoke as local_invoke
        # 1) 개별 HTTP 요청 타임아웃은 ai_local_timeout으로 분류된다.
        with patch("httpx.Client.post", side_effect=httpx.ReadTimeout("read timed out")):
            with self.assertRaises(AppError) as caught:
                local_invoke(self.settings, "지시", {"task": "chat_answer"}, 200, 0.2)
        self.assertEqual(caught.exception.code, "ai_local_timeout")

        # 2) 질문 전체 누적 시간 예산(turn_budget) 만료 시에는 추가 HTTP 호출 전에 ai_local_turn_timeout으로 중단한다.
        with turn_budget(-0.1), patch("httpx.Client.post") as post_mock:
            with self.assertRaises(AppError) as caught_turn:
                local_invoke(self.settings, "지시", {"task": "chat_answer"}, 200, 0.2)
            self.assertEqual(caught_turn.exception.code, "ai_local_turn_timeout")
            post_mock.assert_not_called()
