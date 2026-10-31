"""대상 관계의 증거 경계·공통 채택·인용 차단. 실제 모델 판정과는 구분한다."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from llm_fixture import synthetic_result
from src.agents import news_relevance as policy
from src.agents.chat import answer_question
from src.agents.report import generate_commentary
from src.agents.output_contract import response_format
from src.config import Settings
from src.models import AppError, NewsArticle


def classification():
    return {"assessments": [
        {"id": 1, "relation": "company", "subject_quote": "가상검수회사", "support_quote": "생산라인 가동 계획 발표"},
        {"id": 2, "relation": "group", "subject_quote": "가상그룹 지주회사", "support_quote": "이사회 경영 강화"},
    ]}


class NewsRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.result = synthetic_result()
        self.settings = Settings("", "", "", "", ai_provider="local", local_model="fixture", news_relevance_mode="strict")
        with policy._cache_lock:
            policy._cache.clear()

    def prepare(self, **changes):
        return policy.prepare_news(changes.get("news", self.result.news), changes.get("stock", self.result.financial.stock),
                                   changes.get("theme", self.result.theme), changes.get("settings", self.settings),
                                   context_id=changes.get("context_id", self.result.result_id))

    def test_original_news_and_ids_are_preserved_but_group_is_not_admitted(self):
        with patch.object(policy, "_invoke", return_value=classification()):
            prepared = self.prepare()
        selected = policy.admitted_news(prepared)
        self.assertEqual(prepared.articles, self.result.news.articles)
        self.assertEqual([a.id for a in selected.articles], [1])
        self.assertEqual(prepared.admission.assessments[1].reason, "group_connection_not_supplied")

    def test_company_and_industry_are_different_use_scopes(self):
        article = NewsArticle(3, "반도체 업계 수출 통계 발표", "https://example.com/sector", None, None)
        news = replace(self.result.news, articles=(article,))
        payload = {"assessments": [{"id": 3, "relation": "industry", "subject_quote": "반도체 업계", "support_quote": "수출 통계 발표"}]}
        parsed = policy.parse_assessments(payload, news, self.result.financial.stock, self.result.theme)
        self.assertTrue(parsed[0].accepted)
        self.assertEqual(parsed[0].reason, "industry_context_only")

    def test_company_name_in_group_or_unverified_alias_cannot_supply_missing_relationship(self):
        payload = classification()
        payload["assessments"][1]["relation"] = "company"
        parsed = policy.parse_assessments(payload, self.result.news, self.result.financial.stock, self.result.theme)
        self.assertFalse(parsed[1].accepted)

    def test_invented_quotes_unknown_ids_missing_duplicate_and_malformed_fields_fail(self):
        variants = []
        for field, value in (("id", 99), ("relation", []), ("subject_quote", "제목에 없는 선택 회사"), ("support_quote", "이미 가동 완료")):
            payload = classification()
            payload["assessments"][1][field] = value
            variants.append(payload)
        payload = classification()
        payload["assessments"] = payload["assessments"][:1]
        variants.append(payload)
        payload = classification()
        payload["assessments"][1] = deepcopy(payload["assessments"][0])
        variants.append(payload)
        for payload in variants:
            with self.subTest(payload=payload), self.assertRaises(AppError):
                policy.parse_assessments(payload, self.result.news, self.result.financial.stock, self.result.theme)

    def test_spoof_negative_and_prefix_company_mentions_are_not_company_events(self):
        name = self.result.financial.stock.name
        for title in (
            name + " 사칭 주의",
            name + "와 무관한 동명이인",
            name + "와 관련 없음 해명",
            name + " 단순 인용 시장 보고서",
            name + "서비스 사업 발표",
        ):
            article = NewsArticle(1, title, None, None, None)
            payload = {"assessments": [{"id": 1, "relation": "company", "subject_quote": name, "support_quote": title}]}
            parsed = policy.parse_assessments(payload, replace(self.result.news, articles=(article,)), self.result.financial.stock, self.result.theme)
            self.assertFalse(parsed[0].accepted)

    def test_r04_to_r07_relation_boundaries_match_policy_contract(self):
        name = self.result.financial.stock.name
        # R04: 선택 회사 자체의 지배구조/이사회 소식은 주제만으로 배제하지 않고 company로 채택한다.
        gov_article = NewsArticle(10, f"{name} 이사회 경영 강화 결의", "https://example.com/gov", None, None)
        gov_payload = {"assessments": [{"id": 10, "relation": "company", "subject_quote": name, "support_quote": "이사회 경영 강화 결의"}]}
        gov_parsed = policy.parse_assessments(gov_payload, replace(self.result.news, articles=(gov_article,)), self.result.financial.stock, self.result.theme)
        self.assertTrue(gov_parsed[0].accepted)
        self.assertEqual(gov_parsed[0].reason, "company_mention")

        # R05: 기업집단(group) 기사는 연결 근거가 없으면 제외하고, 그룹명 유사성만으로 추정하지 않으며, 명시적 연결 근거가 제공된 경우만 허용한다.
        grp_article = NewsArticle(11, f"가상검수그룹 지주회사, {name} 생산라인 공동 투자 발표", "https://example.com/grp", None, None)
        grp_payload = {"assessments": [{"id": 11, "relation": "group", "subject_quote": "가상검수그룹 지주회사", "support_quote": f"{name} 생산라인 공동 투자 발표"}]}
        no_conn = policy.parse_assessments(grp_payload, replace(self.result.news, articles=(grp_article,)), self.result.financial.stock, self.result.theme)
        self.assertFalse(no_conn[0].accepted)
        self.assertEqual(no_conn[0].reason, "group_connection_not_supplied")
        with_conn = policy.parse_assessments(
            grp_payload,
            replace(self.result.news, articles=(grp_article,)),
            self.result.financial.stock,
            self.result.theme,
            group_connections=(f"{name} 생산라인 공동 투자 발표",),
        )
        self.assertTrue(with_conn[0].accepted)
        self.assertEqual(with_conn[0].reason, "group_connection_verified")

        # R06/R07: unrelated 및 unknown 분류와 타사 인용 주체는 채택하지 않는다.
        other_articles = (
            NewsArticle(12, f"경쟁사 대표, {name} 거론하며 시장 전망 발표", None, None, None),
            NewsArticle(13, "해외 거시경제 금리 동결 소식", None, None, None),
        )
        other_payload = {"assessments": [
            {"id": 12, "relation": "unknown", "subject_quote": "경쟁사 대표", "support_quote": "시장 전망 발표"},
            {"id": 13, "relation": "unrelated", "subject_quote": "해외 거시경제", "support_quote": "금리 동결 소식"},
        ]}
        other_parsed = policy.parse_assessments(other_payload, replace(self.result.news, articles=other_articles), self.result.financial.stock, self.result.theme)
        self.assertFalse(other_parsed[0].accepted)
        self.assertEqual(other_parsed[0].reason, "relationship_unconfirmed")
        self.assertFalse(other_parsed[1].accepted)
        self.assertEqual(other_parsed[1].reason, "different_subject")

    def test_l06_model_revision_policy_and_ttl_expiration_invalidate_cache(self):
        with patch.object(policy, "_invoke", return_value=classification()) as invoke:
            first = self.prepare()
            # 동일 조건 및 TTL 내에서는 캐시 재사용
            self.assertIs(self.prepare().admission, first.admission)
            self.assertEqual(invoke.call_count, 1)
            # 가중치 리비전 변경(동일 모델 ID라도 가중치 교체) 시 캐시 무효화
            rev_settings = replace(self.settings, local_model_revision="gemma-4-12b-q4-rev2")
            self.prepare(settings=rev_settings)
            self.assertEqual(invoke.call_count, 2)
            # TTL 만료(ttl_seconds=-1) 시 캐시 무효화 및 재판정
            policy.prepare_news(
                self.result.news,
                self.result.financial.stock,
                self.result.theme,
                rev_settings,
                context_id=self.result.result_id,
                ttl_seconds=-1.0,
            )
            self.assertEqual(invoke.call_count, 3)

    def test_cache_reuse_and_target_theme_result_model_article_invalidations(self):
        with patch.object(policy, "_invoke", return_value=classification()) as invoke:
            prepared = self.prepare()
            self.assertIs(self.prepare().admission, prepared.admission)
            invoke.assert_called_once()
            for changes in ({"context_id": "new-result"}, {"theme": "다른테마"},
                            {"stock": replace(self.result.financial.stock, code="654321")},
                            {"settings": replace(self.settings, local_model="different-model")},
                            {"news": replace(self.result.news, retrieved_at=self.result.news.retrieved_at + timedelta(seconds=1))}):
                self.prepare(**changes)
            self.assertEqual(invoke.call_count, 6)

    def test_explicit_schema_is_not_accidentally_candidate_output(self):
        fmt = response_format({"task": "news_relevance", "articles": [{"id": 7, "title": "제목"}]}, "local", schema_supported=True)
        props = fmt["json_schema"]["schema"]["properties"]
        self.assertEqual(props["assessments"]["items"]["properties"]["id"]["enum"], [7])
        self.assertNotIn("stocks", props)

    def test_old_mode_and_empty_news_do_not_request_additional_inference(self):
        with patch.object(policy, "_invoke") as invoke:
            self.assertIs(self.prepare(settings=replace(self.settings, news_relevance_mode="standard")), self.result.news)
            prepared = self.prepare(news=replace(self.result.news, articles=()))
            self.assertEqual(prepared.admission.assessments, ())
            invoke.assert_not_called()

    def test_forbidden_reference_is_rejected_before_semantic_review_in_chat(self):
        payload = {"text": "지주회사 이사회 경영 강화 소식입니다.", "evidence_ids": ["NEWS_2"], "follow_up": "", "blocks": []}
        with patch.object(policy, "_invoke", return_value=classification()), patch("src.agents.chat._invoke", return_value=payload) as invoke:
            with self.assertRaises(AppError) as caught:
                answer_question("관련 뉴스는 무엇입니까?", self.result, [], self.settings)
        self.assertEqual(caught.exception.code, "chat_evidence")
        self.assertEqual(invoke.call_count, 2)
        self.assertTrue(all(c.args[2]["task"] == "chat_answer" for c in invoke.call_args_list))

    def test_basic_report_rejects_same_forbidden_article_and_preserves_raw_data(self):
        payload = {"stock_name": self.result.financial.stock.name, "price": 10000, "per": 12.5,
                   "theme_trend": [{"text": "지주회사 경영 강화 소식이 보도되었습니다.", "news_ids": [2]}],
                   "stock_comment": "", "opportunity": None, "risk": None, "summary": None}
        with patch.object(policy, "_invoke", return_value=classification()), patch("src.agents.report._invoke", return_value=payload):
            with self.assertRaises(AppError) as caught:
                generate_commentary(self.result.theme, self.result.financial, self.result.news, self.settings)
        self.assertEqual(caught.exception.code, "report_evidence")
        self.assertEqual(len(self.result.news.articles), 2)

    def test_news_refresh_binds_admission_to_new_result_without_refetching_finance(self):
        from src.pipeline import analyze_selected_stock
        with patch("src.pipeline.fetch_news", return_value=self.result.news), patch.object(policy, "_invoke", return_value=classification()), patch("src.pipeline.fetch_financial") as finance:
            fresh = analyze_selected_stock(self.result.theme, self.result.candidates, self.result.target_code,
                                           settings=self.settings, scope="news", previous=self.result)
        self.assertNotEqual(fresh.result_id, self.result.result_id)
        self.assertEqual(fresh.news.admission.context_id, fresh.result_id)
        self.assertEqual(len(fresh.news.articles), 2)
        self.assertIs(fresh.financial, self.result.financial)
        finance.assert_not_called()
