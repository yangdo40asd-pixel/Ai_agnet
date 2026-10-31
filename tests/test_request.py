"""단계 S02: KRX 공식 명칭 최장 일치·관계 주체/대상·단일 파이프라인 차단."""
import unittest
from unittest.mock import patch
import pandas as pd

from src.agents.request import parse_entities, company_to_lookup, route_message
from src.config import Settings
from src.models import CandidateDiscoveryResult, now_kst
from src.data.stock import resolve_candidates


def listing_fixture():
    return pd.DataFrame([
        {"Name": name, "Code": code, "Market": "KOSPI"}
        for name, code in (("삼성", "000001"), ("삼성전자", "005930"),
                           ("삼성전자우", "005935"), ("삼성물산", "028260"),
                           ("SK하이닉스", "000660"), ("가상신규회사", "111111"))
    ])


class EntityRoutingTests(unittest.TestCase):
    def setUp(self):
        self.listing = listing_fixture()
        self.settings = Settings("test", "test", "", "")

    def test_exact_company_excludes_modifiers_and_attached_particle(self):
        for text in ("삼성전자 종목 이슈 세 줄 요약", "삼성전자 어떻게 생각해?", "삼성전자를 분석해줘",
                     "삼성전자 주요 이슈 요약", "가상신규회사 최근 실적을 설명해줘", "005930 분석해줘"):
            with self.subTest(text=text):
                entities = parse_entities(text, listing=self.listing)
                expected = "가상신규회사" if text.startswith("가상") else "삼성전자"
                self.assertEqual(entities.primary_stock.name, expected)
                self.assertEqual(len(entities.mentioned_stocks), 1)
                self.assertEqual(company_to_lookup(text, listing=self.listing), expected)

    def test_longest_match_preferred_share_and_no_embedded_fake_name(self):
        self.assertEqual(parse_entities("삼성전자우 분석해줘", listing=self.listing).primary_stock.name, "삼성전자우")
        for text in ("가짜삼성전자 뉴스", "삼성전자가짜 뉴스", "X005930Y 분석해줘", "삼성전자가짜주식회사 분석"):
            with self.subTest(text=text):
                self.assertIsNone(parse_entities(text, listing=self.listing).primary_stock)

    def test_shareholding_subject_target_and_reverse_order(self):
        for text in ("삼성물산이 보유한 삼성전자 지분 알려줘", "삼성물산의 삼성전자 지분", "삼성전자 지분을 삼성물산이 보유한 비율"):
            with self.subTest(text=text):
                entities = parse_entities(text, listing=self.listing)
                self.assertEqual(entities.intent, "shareholding_query")
                self.assertEqual(entities.subject_company.name, "삼성물산")
                self.assertEqual(entities.target_company.name, "삼성전자")
                self.assertIsNone(entities.primary_stock)
                self.assertEqual(len(entities.mentioned_stocks), 2)
                self.assertEqual(company_to_lookup(text, listing=self.listing), "")

    def test_comparison_supply_chain_and_unknown_second_company_never_select_first(self):
        for text, intent in (("삼성전자와 SK하이닉스 비교", "comparison_query"),
                             ("삼성전자와SK하이닉스 비교", "comparison_query"),
                             ("삼성전자와 SK하이닉스 공급 관계", "supply_chain_query"),
                             ("삼성전자와 미확인회사 비교해줘", "comparison_query")):
            with self.subTest(text=text):
                entities = parse_entities(text, listing=self.listing)
                self.assertEqual(entities.intent, intent)
                self.assertIsNone(entities.primary_stock)

    def test_comparison_route_defers_supported_scope_to_comparison_flow(self):
        with patch("src.agents.request._invoke") as invoke:
            intent = route_message("삼성전자와 SK하이닉스 비교", None, "", [],
                                   self.settings, listing=self.listing)
        self.assertEqual(intent.action, "comparison_query")
        self.assertEqual(intent.reason, "")
        self.assertIsNone(intent.entities.primary_stock)
        invoke.assert_not_called()

    def test_route_relations_before_candidate_selection_and_without_classifier(self):
        stocks = resolve_candidates(("삼성물산", "삼성전자"), self.listing)
        discovery = CandidateDiscoveryResult("반도체", stocks, now_kst())
        with patch("src.agents.request._invoke") as invoke:
            for known in (discovery, None):
                intent = route_message("삼성물산이 보유한 삼성전자 지분 알려줘", known, "005930", [],
                                       self.settings, listing=self.listing)
                self.assertEqual(intent.action, "shareholding_query")
                self.assertIsNone(intent.entities.primary_stock)
                self.assertFalse(intent.code)
            invoke.assert_not_called()

    def test_new_single_company_routes_from_master_without_model_guess(self):
        with patch("src.agents.request._invoke") as invoke:
            intent = route_message("삼성전자 종목 이슈 세 줄 요약", None, None, [], self.settings, listing=self.listing)
            self.assertEqual((intent.action, intent.company, intent.code), ("lookup", "삼성전자", "005930"))
            invoke.assert_not_called()

    def test_model_cannot_override_explicit_unresolved_name(self):
        with patch("src.agents.request._invoke") as invoke:
            intent = route_message("미확인회사 뉴스 알려줘", None, "005930", [], self.settings, listing=self.listing)
            self.assertEqual(intent.action, "clarify")
            invoke.assert_not_called()

    def test_switch_single_stock_remains_single_and_concept_is_not_relationship(self):
        entities = parse_entities("SK하이닉스로 바꿔서 비교해줘", listing=self.listing)
        self.assertEqual(entities.primary_stock.name, "SK하이닉스")
        self.assertEqual(parse_entities("지분이 뭐야?", listing=self.listing).intent, "single_stock")
        self.assertIsNone(parse_entities("이 종목 뉴스와 실적을 비교해줘", listing=self.listing).primary_stock)

    def test_current_stock_modifier_is_not_a_new_company(self):
        for question in ("이 종목 뉴스 이슈를 설명해줘", "이 회사 실적은 어때?", "현재 종목 주가 알려줘"):
            with self.subTest(question=question):
                self.assertEqual(company_to_lookup(question), "")
                with patch("src.agents.request._invoke") as invoke, patch("src.data.stock.load_listing") as loader:
                    intent = route_message(question, None, "005930", [], self.settings, listing_loader=loader)
                    self.assertEqual(intent.action, "answer")
                    loader.assert_not_called()
                    invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
