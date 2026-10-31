"""02-C 기업 카드 응답 생성·검증·저장 호환성 테스트 (CARD-I6, CARD-I7)."""
import unittest
from unittest.mock import patch
from dataclasses import replace
from datetime import datetime
from src.models import (
    AppError, ChatResponse, CompanyCard, CompanyCardSection,
    StockCandidate, CandidateDiscoveryResult, CompanyBusinessProfile, KST, now_kst
)
from src.agents.company_cards import validate_company_cards, build_fallback_cards
from src.agents.output_contract import response_format
from src.agents.answer_quality import review_units, QUALITY_CHECKS
from src.agents.discovery_answer import discovery_answer
from src.ui.answer import response_fields, source_groups
from src.config import Settings


STOCKS = (
    StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
    StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
    StockCandidate("한미반도체", "042700", "KOSPI", "042700.KS"),
)

SETTINGS = Settings("fixture", "fixture", "", "")

EVIDENCE = {
    "BUSINESS_005930": {
        "id": "BUSINESS_005930",
        "kind": "company_profile",
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "text": "삼성전자 · 업종: 통신 및 방송 장비 제조업 · 주요제품: 스마트폰, DRAM",
        "source": "한국거래소 KIND",
        "scope": "company_profile",
        "retrieved_at": "2026-10-29T10:00:00",
    },
    "005930_SECTION_1": {
        "id": "005930_SECTION_1",
        "kind": "company_business_section",
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "text": "삼성전자 DS부문은 메모리 반도체(DRAM, NAND Flash)를 생산 및 판매하고 있습니다.",
        "source": "OpenDART 정기보고서 사업 원문",
        "scope": "official_business",
        "retrieved_at": "2026-10-29T10:00:00",
    },
    "BUSINESS_000660": {
        "id": "BUSINESS_000660",
        "kind": "company_profile",
        "stock_code": "000660",
        "stock_name": "SK하이닉스",
        "text": "SK하이닉스 · 업종: 반도체 제조업 · 주요제품: DRAM, NAND Flash, MCP",
        "source": "한국거래소 KIND",
        "scope": "company_profile",
        "retrieved_at": "2026-10-29T10:00:00",
    },
    "BUSINESS_042700": {
        "id": "BUSINESS_042700",
        "kind": "company_profile",
        "stock_code": "042700",
        "stock_name": "한미반도체",
        "text": "한미반도체 · 업종: 반도체 제조용 기계 제조업 · 주요제품: 반도체 제조용 장비",
        "source": "한국거래소 KIND",
        "scope": "company_profile",
        "retrieved_at": "2026-10-29T10:00:00",
    },
    "042700_SECTION_1": {
        "id": "042700_SECTION_1",
        "kind": "company_business_section",
        "stock_code": "042700",
        "stock_name": "한미반도체",
        "text": "한미반도체는 듀얼 헤드 TC 본더 등 반도체 후공정 핵심 패키징 장비를 공급합니다.",
        "source": "OpenDART 정기보고서 사업 원문",
        "scope": "official_business",
        "retrieved_at": "2026-10-29T10:00:00",
    },
}


class Plan8CompanyCardsTests(unittest.TestCase):
    def test_model_dataclass_contract_and_unpacking(self):
        sec = CompanyCardSection("summary", "메모리 반도체 제조사입니다.", ("BUSINESS_005930",))
        self.assertEqual(sec.role, "summary")
        self.assertEqual(sec.text, "메모리 반도체 제조사입니다.")
        self.assertEqual(sec.evidence_ids, ("BUSINESS_005930",))

        card = CompanyCard("005930", "삼성전자", (sec,), card_id="CARD_005930")
        self.assertEqual(card.stock_code, "005930")
        self.assertEqual(card.stock_name, "삼성전자")
        self.assertEqual(len(card.sections), 1)

        resp = ChatResponse("소개합니다.", [dict(EVIDENCE["BUSINESS_005930"], id="BUSINESS_005930")], company_cards=(card,))
        # 3값 언패킹 호환성 유지 확인
        text, ev, follow = resp
        self.assertIn("소개합니다.", text)
        self.assertIn("**삼성전자**", text)
        self.assertIn("메모리 반도체 제조사입니다.", text)
        self.assertEqual(len(ev), 1)
        self.assertEqual(follow, "")

    def test_validate_company_cards_valid_payload(self):
        payload = {
            "text": "반도체 테마 관련 후보 기업들입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [
                        {"role": "summary", "text": "글로벌 메모리 반도체 종합 제조사입니다.", "evidence_ids": ["BUSINESS_005930"]},
                        {"role": "business", "text": "DRAM과 낸드플래시 등 주요 메모리 제품을 생산합니다.", "evidence_ids": ["005930_SECTION_1"]},
                    ],
                },
                {
                    "stock_code": "000660",
                    "sections": [
                        {"role": "summary", "text": "메모리 반도체(DRAM, NAND Flash)를 생산하는 기업입니다.", "evidence_ids": ["BUSINESS_000660"]},
                    ],
                },
                {
                    "stock_code": "042700",
                    "sections": [
                        {"role": "summary", "text": "반도체 후공정 패키징 장비 공급사입니다.", "evidence_ids": ["BUSINESS_042700"]},
                        {"role": "business", "text": "듀얼 헤드 본더 등 첨단 공정 패키징 장비를 제작합니다.", "evidence_ids": ["042700_SECTION_1"]},
                    ],
                },
            ],
        }
        resp = validate_company_cards(payload, EVIDENCE, candidates=STOCKS, question="반도체 관련주 알려줘")
        self.assertIsInstance(resp, ChatResponse)
        self.assertEqual(len(resp.company_cards), 3)
        self.assertEqual(resp.company_cards[0].stock_code, "005930")
        self.assertEqual(resp.company_cards[1].stock_code, "000660")
        self.assertEqual(resp.company_cards[2].stock_code, "042700")
        self.assertEqual(len(resp.company_cards[0].sections), 2)
        self.assertEqual(resp.company_cards[0].sections[0].role, "summary")

    def test_cross_company_evidence_ownership_rejected(self):
        # 042700(한미반도체) 카드에 005930(삼성전자)의 근거를 교차 인용하면 반드시 거절되어야 함
        payload = {
            "text": "반도체 테마 관련 후보입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [{"role": "summary", "text": "삼성전자 메모리 사업입니다.", "evidence_ids": ["BUSINESS_005930"]}],
                },
                {
                    "stock_code": "000660",
                    "sections": [{"role": "summary", "text": "SK하이닉스 메모리 사업입니다.", "evidence_ids": ["BUSINESS_000660"]}],
                },
                {
                    "stock_code": "042700",
                    "sections": [{"role": "summary", "text": "한미반도체 장비 사업입니다.", "evidence_ids": ["005930_SECTION_1"]}], # 교차 인용
                },
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(payload, EVIDENCE, candidates=STOCKS, question="반도체 관련주")
        self.assertEqual(ctx.exception.code, "company_card_evidence_ownership")

    def test_duplicate_role_within_card_rejected(self):
        payload = {
            "text": "반도체 테마 관련 후보입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [
                        {"role": "summary", "text": "삼성전자 요약 첫 번째입니다.", "evidence_ids": ["BUSINESS_005930"]},
                        {"role": "summary", "text": "삼성전자 요약 두 번째입니다.", "evidence_ids": ["BUSINESS_005930"]}, # 중복 role
                    ],
                },
                {
                    "stock_code": "000660",
                    "sections": [{"role": "summary", "text": "SK하이닉스 메모리 사업입니다.", "evidence_ids": ["BUSINESS_000660"]}],
                },
                {
                    "stock_code": "042700",
                    "sections": [{"role": "summary", "text": "한미반도체 장비 사업입니다.", "evidence_ids": ["BUSINESS_042700"]}],
                },
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(payload, EVIDENCE, candidates=STOCKS, question="반도체 관련주")
        self.assertEqual(ctx.exception.code, "company_card_role_duplicate")

    def test_unsupported_role_rejected(self):
        payload = {
            "text": "반도체 테마 관련 후보입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [{"role": "investment_recommendation", "text": "매수 추천합니다.", "evidence_ids": ["BUSINESS_005930"]}],
                },
                {
                    "stock_code": "000660",
                    "sections": [{"role": "summary", "text": "SK하이닉스 메모리 사업입니다.", "evidence_ids": ["BUSINESS_000660"]}],
                },
                {
                    "stock_code": "042700",
                    "sections": [{"role": "summary", "text": "한미반도체 장비 사업입니다.", "evidence_ids": ["BUSINESS_042700"]}],
                },
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(payload, EVIDENCE, candidates=STOCKS, question="반도체 관련주")
        self.assertEqual(ctx.exception.code, "company_card_role")

    def test_candidate_mismatch_rejected(self):
        payload = {
            "text": "반도체 테마 관련 후보입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [{"role": "summary", "text": "삼성전자 요약입니다.", "evidence_ids": ["BUSINESS_005930"]}],
                },
                # 000660 누락, 042700 누락
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(payload, EVIDENCE, candidates=STOCKS, question="반도체 관련주")
        self.assertEqual(ctx.exception.code, "company_card_mismatch")

    def test_response_fields_and_source_groups_serialization(self):
        sec = CompanyCardSection("summary", "메모리 사업을 영위합니다.", ("BUSINESS_005930",))
        card = CompanyCard("005930", "삼성전자", (sec,), card_id="CARD_005930")
        resp = ChatResponse("소개글입니다.", [dict(EVIDENCE["BUSINESS_005930"], id="BUSINESS_005930")], company_cards=(card,))

        # response_fields 직렬화 검사
        fields = response_fields(resp)
        self.assertIn("company_cards", fields)
        self.assertEqual(len(fields["company_cards"]), 1)
        self.assertEqual(fields["company_cards"][0]["stock_code"], "005930")
        self.assertEqual(fields["company_cards"][0]["sections"][0]["role"], "summary")

        # source_groups 인용 수집 호환성 검사
        msg = {
            "intro": resp.intro,
            "evidence": resp.evidence,
            "company_cards": fields["company_cards"],
            "lead_evidence_ids": resp.lead_evidence_ids,
        }
        groups, numbers = source_groups(msg)
        self.assertEqual(len(groups), 1)
        self.assertIn("BUSINESS_005930", numbers)

    def test_review_units_scopes_evidence_per_card_section(self):
        sec1 = CompanyCardSection("summary", "삼성전자 반도체 부문입니다.", ("BUSINESS_005930",))
        sec2 = CompanyCardSection("business", "DRAM 제품을 생산합니다.", ("005930_SECTION_1",))
        card1 = CompanyCard("005930", "삼성전자", (sec1, sec2))

        sec3 = CompanyCardSection("summary", "한미반도체 패키징 장비 부문입니다.", ("042700_SECTION_1",))
        card2 = CompanyCard("042700", "한미반도체", (sec3,))

        resp = ChatResponse("도입부 설명입니다.", [dict(EVIDENCE[k], id=k) for k in EVIDENCE], company_cards=(card1, card2))
        units = review_units(resp, EVIDENCE)

        # intro 단위 1개 + card1 sec1 + card1 sec2 + card2 sec3
        unit_ids = [u["id"] for u in units]
        self.assertTrue(any("card_005930_summary" in uid for uid in unit_ids))
        self.assertTrue(any("card_005930_business" in uid for uid in unit_ids))
        self.assertTrue(any("card_042700_summary" in uid for uid in unit_ids))

        # 각 카드의 unit evidence에는 오직 해당 section의 evidence만 포함되어야 함
        hpsp_unit = next(u for u in units if "card_042700" in u["id"])
        self.assertEqual(set(hpsp_unit["evidence"]), {"042700_SECTION_1"})
        self.assertNotIn("BUSINESS_005930", hpsp_unit["evidence"])

    def test_output_contract_discovery_cards_schema(self):
        payload = {
            "task": "discovery_cards",
            "candidates": [{"code": s.code} for s in STOCKS],
            "evidence": EVIDENCE,
        }
        schema = response_format(payload, "qwen/qwen3.8-27b", schema_supported=True)
        props = schema["json_schema"]["schema"]["properties"]
        self.assertIn("company_cards", props)
        self.assertEqual(props["company_cards"]["minItems"], 3)
        self.assertEqual(props["company_cards"]["maxItems"], 3)

    def test_fallback_cards_builds_valid_cards_for_all_stocks(self):
        discovery = CandidateDiscoveryResult("반도체", STOCKS, now_kst())
        cards = build_fallback_cards(discovery, EVIDENCE, STOCKS)
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0].stock_code, "005930")
        self.assertEqual(cards[1].stock_code, "000660")
        self.assertEqual(cards[2].stock_code, "042700")
        for card in cards:
            self.assertTrue(len(card.sections) >= 1)
            self.assertEqual(card.sections[0].role, "summary")

    def test_dataclass_replace_preserves_company_cards(self):
        sec = CompanyCardSection("summary", "메모리 사업을 영위합니다.", ("BUSINESS_005930",))
        card = CompanyCard("005930", "삼성전자", (sec,), card_id="CARD_005930")
        resp = ChatResponse("소개글입니다.", [dict(EVIDENCE["BUSINESS_005930"], id="BUSINESS_005930")], company_cards=(card,))

        # replace 시 company_cards 보존 확인
        replaced = replace(resp, follow_up="다음 질문 예시")
        self.assertEqual(replaced.follow_up, "다음 질문 예시")
        self.assertEqual(len(replaced.company_cards), 1)
        self.assertEqual(replaced.company_cards[0].stock_code, "005930")

    def test_legacy_message_without_company_cards(self):
        # 구형 메시지(company_cards 필드 부재)에 대한 source_groups 및 response_fields 정상 처리
        legacy_msg = {
            "text": "일반 뉴스 답변입니다.",
            "evidence": [dict(EVIDENCE["BUSINESS_005930"], id="BUSINESS_005930")],
            "follow_up": "",
        }
        groups, numbers = source_groups(legacy_msg)
        self.assertEqual(len(groups), 1)
        self.assertIn("BUSINESS_005930", numbers)

    def test_discovery_answer_as_cards_end_to_end_success(self):
        discovery = CandidateDiscoveryResult(
            "반도체", STOCKS, now_kst(),
            business_profiles=(
                CompanyBusinessProfile("삼성전자", "005930", "제조업", "DRAM", now_kst(), "url"),
                CompanyBusinessProfile("SK하이닉스", "000660", "제조업", "NAND", now_kst(), "url"),
                CompanyBusinessProfile("한미반도체", "042700", "제조업", "장비", now_kst(), "url"),
            )
        )
        def mock_invoke(settings, instruction, req, *args, **kwargs):
            if req.get("task") == "chat_grounding_review":
                return {
                    "checks": dict.fromkeys(QUALITY_CHECKS, True),
                    "supported": True,
                    "answers_question": True,
                    "reason": "모의 심사 합격",
                    "unit_reviews": [{"id": u["id"], "supported": True, "reason": "근거 일치"} for u in req.get("review_units", [])],
                }
            return {
                "text": "반도체 테마 관련 후보 기업의 공식 사업 정보입니다.",
                "evidence_ids": ["BUSINESS_005930"],
                "follow_up": "",
                "company_cards": [
                    {
                        "stock_code": "005930",
                        "sections": [{"role": "summary", "text": "삼성전자는 메모리 반도체를 생산합니다.", "evidence_ids": ["BUSINESS_005930"]}],
                    },
                    {
                        "stock_code": "000660",
                        "sections": [{"role": "summary", "text": "SK하이닉스는 낸드플래시를 공급합니다.", "evidence_ids": ["BUSINESS_000660"]}],
                    },
                    {
                        "stock_code": "042700",
                        "sections": [{"role": "summary", "text": "한미반도체는 반도체 후공정 장비를 제조합니다.", "evidence_ids": ["BUSINESS_042700"]}],
                    },
                ],
            }

        with patch("src.agents.discovery_answer._invoke", side_effect=mock_invoke):
            answer = discovery_answer("반도체 관련 종목 알려줘", discovery, SETTINGS, as_cards=True)

        self.assertIsInstance(answer, ChatResponse)
        self.assertEqual(len(answer.company_cards), 3)
        self.assertEqual(answer.company_cards[0].stock_code, "005930")
        self.assertEqual(answer.company_cards[1].stock_code, "000660")
        self.assertEqual(answer.company_cards[2].stock_code, "042700")
        self.assertIn("**삼성전자**", answer.text)
        self.assertIn("**SK하이닉스**", answer.text)
        self.assertIn("**한미반도체**", answer.text)
        self.assertFalse(any(e.get("answer_origin") for e in answer.evidence))

    def test_discovery_answer_as_cards_fallback_on_llm_failure(self):
        discovery = CandidateDiscoveryResult(
            "반도체", STOCKS, now_kst(),
            business_profiles=(
                CompanyBusinessProfile("삼성전자", "005930", "제조업", "DRAM", now_kst(), "url"),
                CompanyBusinessProfile("SK하이닉스", "000660", "제조업", "NAND", now_kst(), "url"),
                CompanyBusinessProfile("한미반도체", "042700", "제조업", "장비", now_kst(), "url"),
            )
        )
        bad_payload = {
            "text": "가짜 응답",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                # 다른 회사 근거를 교차 인용하여 거절 유발
                {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자", "evidence_ids": ["BUSINESS_042700"]}]},
                {"stock_code": "000660", "sections": [{"role": "summary", "text": "SK하이닉스", "evidence_ids": ["BUSINESS_000660"]}]},
                {"stock_code": "042700", "sections": [{"role": "summary", "text": "한미반도체", "evidence_ids": ["BUSINESS_042700"]}]},
            ]
        }
        with patch("src.agents.discovery_answer._invoke", return_value=bad_payload):
            answer = discovery_answer("반도체 관련 종목 알려줘", discovery, SETTINGS, as_cards=True)

        # 거절 후 대체 카드 fallback 생성 확인
        self.assertIsInstance(answer, ChatResponse)
        self.assertEqual(len(answer.company_cards), 3)
        self.assertTrue(all(e.get("answer_origin") == "verified_business_fallback" for e in answer.evidence))
        self.assertIn("**삼성전자**", answer.text)


    def test_cards_rejected_in_plain_or_issues_mode(self):
        from src.agents.chat import validate_response
        cards_payload = {
            "text": "일반 설명입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자", "evidence_ids": ["BUSINESS_005930"]}]}
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_response(cards_payload, EVIDENCE, style="plain")
        self.assertEqual(ctx.exception.code, "chat_answer")

        with self.assertRaises(AppError) as ctx2:
            validate_response(cards_payload, EVIDENCE, style="issues")
        self.assertEqual(ctx2.exception.code, "chat_answer")

    def test_company_card_candidates_required_and_ownerless_evidence_rejected(self):
        cards_payload = {
            "text": "설명입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자 메모리 반도체 생산 기업입니다.", "evidence_ids": ["BUSINESS_005930"]}]}
            ],
        }
        # candidates 가 빈 튜플이면 거절
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(cards_payload, EVIDENCE, candidates=())
        self.assertEqual(ctx.exception.code, "company_card_candidates")

        # 근거에 stock_code가 없는 소유자 불명 근거 인용 거절
        ownerless_evidence = dict(EVIDENCE)
        ownerless_evidence["OWNERLESS_1"] = {
            "id": "OWNERLESS_1",
            "kind": "company_profile",
            "text": "소유자 정보가 없는 원문입니다.",
            "scope": "company_profile",
        }
        bad_ownerless_payload = {
            "text": "설명입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자 메모리 반도체 생산 기업입니다.", "evidence_ids": ["OWNERLESS_1"]}]}
            ],
        }
        with self.assertRaises(AppError) as ctx2:
            validate_company_cards(bad_ownerless_payload, ownerless_evidence, candidates=(STOCKS[0],))
        self.assertEqual(ctx2.exception.code, "company_card_evidence_ownership")

    def test_malformed_evidence_id_raises_app_error_not_type_error(self):
        for bad_id in ({}, None, 123, []):
            malformed_payload = {
                "text": "설명입니다.",
                "evidence_ids": ["BUSINESS_005930"],
                "follow_up": "",
                "company_cards": [
                    {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자 설명입니다.", "evidence_ids": [bad_id]}]}
                ],
            }
            with self.assertRaises(AppError) as ctx:
                validate_company_cards(malformed_payload, EVIDENCE, candidates=(STOCKS[0],))
            self.assertEqual(ctx.exception.code, "company_card_evidence")

    def test_fallback_cards_no_fabricated_theme_and_under_length_limit(self):
        # 1200자 초과 긴 사업 절이 있어도 대체 카드는 1000자 제한을 넘지 않고 자체 검증 통과
        words = ["전공정", "후공정", "웨이퍼", "어닐링", "패키징", "검사", "세정", "식각", "증착", "이온주입", "노광", "배선", "테스트", "본딩"]
        long_text = " ".join(f"삼성전자는 {w} 단계의 정밀 반도체 제조 장비와 부품을 공급합니다." for w in words * 4)
        long_evidence = {
            "SEC_LONG": {
                "id": "SEC_LONG",
                "kind": "company_business_section",
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "products": long_text,
                "scope": "official_business",
                "theme_supported": False,
            }
        }
        discovery = CandidateDiscoveryResult("양자컴퓨터", (STOCKS[0],), now_kst())
        cards = build_fallback_cards(discovery, long_evidence, (STOCKS[0],))
        self.assertEqual(len(cards), 1)
        for sec in cards[0].sections:
            self.assertLessEqual(len(sec.text), 500)
            self.assertNotIn("양자컴퓨터 관련 후보로 분류된 공식 정보", sec.text)
            self.assertNotIn("공식 정보 기준", sec.text)

        fb_payload = {
            "text": "대체 응답 도입부입니다.",
            "evidence_ids": ["SEC_LONG"],
            "follow_up": "",
            "company_cards": [
                {"stock_code": cards[0].stock_code, "sections": [{"role": s.role, "text": s.text, "evidence_ids": list(s.evidence_ids)} for s in cards[0].sections]}
            ]
        }
        validated = validate_company_cards(fb_payload, long_evidence, candidates=(STOCKS[0],))
        self.assertIsInstance(validated, ChatResponse)

    def test_enforce_presentation_includes_company_cards(self):
        from src.agents.presentation import enforce_presentation, parse_presentation
        sec1 = CompanyCardSection("summary", "첫 번째 문장입니다. 두 번째 문장입니다.", ("BUSINESS_005930",))
        sec2 = CompanyCardSection("business", "세 번째 문장입니다.", ("005930_SECTION_1",))
        card = CompanyCard("005930", "삼성전자", (sec1, sec2))
        resp = ChatResponse("도입 한 문장입니다.", [dict(EVIDENCE["BUSINESS_005930"], id="BUSINESS_005930")], company_cards=(card,))

        # '한 문장' 제한 요청 시 도입+카드의 총 문장 수가 1개를 초과하므로 AppError('chat_length') 발생
        contract = parse_presentation("한 문장으로 요약해줘")
        with self.assertRaises(AppError) as ctx:
            enforce_presentation(resp, contract)
        self.assertEqual(ctx.exception.code, "chat_length")

    def test_duplicate_sentence_between_intro_and_card_rejected(self):
        dup_payload = {
            "text": "삼성전자는 글로벌 메모리 반도체를 생산 및 공급하고 있습니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [
                        {"role": "summary", "text": "삼성전자는 글로벌 메모리 반도체를 생산 및 공급하고 있습니다.", "evidence_ids": ["BUSINESS_005930"]}
                    ],
                },
                {
                    "stock_code": "000660",
                    "sections": [{"role": "summary", "text": "SK하이닉스는 낸드플래시를 공급합니다.", "evidence_ids": ["BUSINESS_000660"]}],
                },
                {
                    "stock_code": "042700",
                    "sections": [{"role": "summary", "text": "한미반도체는 반도체 후공정 장비를 제조합니다.", "evidence_ids": ["BUSINESS_042700"]}],
                },
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(dup_payload, EVIDENCE, candidates=STOCKS, question="반도체 테마")
        self.assertEqual(ctx.exception.code, "chat_directness")


    def test_fallback_respects_sentence_and_line_limits(self):
        from src.agents.presentation import parse_presentation, enforce_presentation
        discovery = CandidateDiscoveryResult(
            "반도체", STOCKS, now_kst(),
            business_profiles=(
                CompanyBusinessProfile("삼성전자", "005930", "제조업", "DRAM", now_kst(), "url"),
                CompanyBusinessProfile("SK하이닉스", "000660", "제조업", "NAND", now_kst(), "url"),
                CompanyBusinessProfile("한미반도체", "042700", "제조업", "장비", now_kst(), "url"),
            )
        )
        with patch("src.agents.discovery_answer._invoke", side_effect=AppError("ai_mock", "모의 생성 실패")):
            # 세 문장 요청: 기업 수 3개와 같으므로 compact 카드 3개로 반환되고 enforce_presentation 통과
            resp_3 = discovery_answer("반도체 관련 기업을 세 문장으로 소개해줘", discovery, SETTINGS, as_cards=True)
            self.assertEqual(len(resp_3.company_cards), 3)
            enforce_presentation(resp_3, parse_presentation("반도체 관련 기업을 세 문장으로 소개해줘"))

            # 두 문장 요청: 기업 수 3개보다 작으므로 plain 텍스트로 전환되고 enforce_presentation 통과
            resp_2 = discovery_answer("반도체 관련 기업을 두 문장으로 소개해줘", discovery, SETTINGS, as_cards=True)
            self.assertEqual(len(resp_2.company_cards), 0)
            enforce_presentation(resp_2, parse_presentation("반도체 관련 기업을 두 문장으로 소개해줘"))

            # 한 문장 요청: 기업 수 3개보다 작으므로 plain 텍스트 1문장으로 반환되고 enforce_presentation 통과
            resp_1 = discovery_answer("반도체 관련 기업을 한 문장으로 요약해줘", discovery, SETTINGS, as_cards=True)
            self.assertEqual(len(resp_1.company_cards), 0)
            enforce_presentation(resp_1, parse_presentation("반도체 관련 기업을 한 문장으로 요약해줘"))

    def test_fallback_preserves_196_char_single_sentence(self):
        from src.agents.discovery_answer import _fallback
        paragraph = (
            "당사는 반도체 제조 공정에서 사용되는 웨이퍼 검사 장비와 세정 장비를 개발하고 생산하며, "
            "고객의 생산 공정 조건에 맞춘 장비 설계와 조립, 설치, 시운전 및 유지보수 업무를 수행하고 있고, "
            "장비에 사용되는 소모성 부품과 교체 부품도 함께 공급하며, "
            "국내외 반도체 제조업체에 대한 제품 판매와 기술 지원 업무를 별도 담당 조직을 통해 수행하고 있습니다."
        )
        single_ev = {
            "SEC_196": {
                "id": "SEC_196",
                "stock_code": STOCKS[0].code,
                "stock_name": STOCKS[0].name,
                "kind": "company_business_section",
                "scope": "official_business",
                "products": paragraph,
                "text": paragraph,
                "theme_supported": True,
                "source": "공식 홈페이지",
                "document_id": "WEB_fixture",
            }
        }
        discovery = CandidateDiscoveryResult("반도체", (STOCKS[0],), now_kst())
        resp = _fallback(discovery, single_ev, (STOCKS[0],), use_cards=True)
        self.assertEqual(len(resp.company_cards), 1)
        card_text = resp.company_cards[0].sections[0].text
        self.assertIn("공식 홈페이지 자료 발췌", card_text)
        self.assertIn("웨이퍼 검사 장비와 세정 장비를 개발하고 생산하며", card_text)
        self.assertNotIn("사업 내용이 확인되었습니다", card_text)

    def test_source_doc_label_accuracy(self):
        from src.agents.company_cards import _source_doc_label
        web_item = {"source": "기업 공식 홈페이지", "document_id": "WEB_005930"}
        dart_item = {"source": "OpenDART 정기보고서", "document_id": "DART_005930_11011"}
        other_item = {"source": "기타 출처", "document_id": "OTHER_005930"}

        self.assertEqual(_source_doc_label(web_item), "공식 홈페이지 자료")
        self.assertEqual(_source_doc_label(dart_item), "공식 사업 보고서")
        self.assertEqual(_source_doc_label(other_item), "공식 사업 자료")

    def test_ungrounded_emphasis_rejected_and_grounded_accepted(self):
        # 원문에 '전문'이 없는 경우 거절
        ungrounded_payload = {
            "text": "반도체 테마 관련 후보입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {
                    "stock_code": "005930",
                    "sections": [{"role": "summary", "text": "삼성전자는 메모리 반도체 전문 기업입니다.", "evidence_ids": ["BUSINESS_005930"]}],
                },
                {
                    "stock_code": "000660",
                    "sections": [{"role": "summary", "text": "SK하이닉스 메모리 사업입니다.", "evidence_ids": ["BUSINESS_000660"]}],
                },
                {
                    "stock_code": "042700",
                    "sections": [{"role": "summary", "text": "한미반도체 장비 사업입니다.", "evidence_ids": ["BUSINESS_042700"]}],
                },
            ],
        }
        with self.assertRaises(AppError) as ctx:
            validate_company_cards(ungrounded_payload, EVIDENCE, candidates=STOCKS, question="반도체")
        self.assertEqual(ctx.exception.code, "chat_claim")
        self.assertIn("전문", ctx.exception.message)

        # 원문에 '전문'이 실제로 명시된 경우 정상 통과
        grounded_evidence = dict(EVIDENCE)
        grounded_evidence["BUSINESS_005930"] = dict(
            EVIDENCE["BUSINESS_005930"],
            text="삼성전자 · 업종: 메모리 반도체 전문 제조업 · 주요제품: DRAM, NAND",
        )
        resp = validate_company_cards(ungrounded_payload, grounded_evidence, candidates=STOCKS, question="반도체")
        self.assertIsInstance(resp, ChatResponse)
        self.assertEqual(len(resp.company_cards), 3)


if __name__ == "__main__":
    unittest.main()
