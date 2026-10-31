"""재요약의 근거·기간·주제를 유지하고 새 지표로 범위를 넓히지 않는지 검증한다."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from src.agents.followup import is_restatement,restatement_evidence
from src.agents.answer_quality import select_evidence
from src.agents.quarterly import contextual_quarter
from src.agents.evidence import build_evidence
from src.agents.chat import answer_question,_verified_fallback
from src.config import Settings
from test_quarterly_flow import bundle,fake_llm
from scripts.llm_fixture import synthetic_result
from dataclasses import replace


class FollowupFocusTests(unittest.TestCase):
    def setUp(self):
        self.result=replace(synthetic_result(),quarterly_summaries=bundle()["summaries"])
        self.evidence=build_evidence(self.result)
        self.key="Q_CMP_2024_2025_3_CFS_OPERATING_MARGIN"
        self.history=[{"role":"user","text":"2025년 3분기 실적은?"},
                      {"role":"assistant","text":"앞의 설명", "evidence":[dict(self.evidence[self.key],id=self.key)]}]

    def test_only_deictic_restatement_requests_are_classified(self):
        for q in ("짧게 두 문장으로 요약해줘.","너무 길어. 세 줄로만 정리해줘.","두 문장으로", "핵심만 다시 정리해주세요", "그 말을 간결하게 한 문장으로 요약해줘", "방금 전망의 결론만 정리해줘"):
            with self.subTest(q=q):self.assertTrue(is_restatement(q))
        for q in ("2025년 실적 요약", "현대차 요약해줘", "PER 요약", "주가도 넣어서 요약", "투자해도 돼?", "실적이 좋아?"):
            with self.subTest(q=q):self.assertFalse(is_restatement(q))

    def test_restatement_preserves_last_answer_subset_instead_of_all_financials(self):
        selected=select_evidence("짧게 두 문장으로 요약해줘",self.history,self.evidence,[],strict=True)
        self.assertEqual(selected.reason,"restatement")
        self.assertEqual(selected.required_ids,(self.key,))
        self.assertEqual(set(selected.evidence),{self.key})

    def test_repeated_restatements_keep_original_scope(self):
        history=self.history+[{"role":"user","text":"두 문장으로 요약해줘"},self.history[-1]]
        self.assertEqual(set(restatement_evidence("한 줄로 정리해줘",history,self.evidence)),{self.key})

    def test_changed_value_or_stock_does_not_relabel_old_answer_as_current(self):
        for change in ({"current":"999"},{"stock_code":"999999"},{"quarter":2}):
            changed=deepcopy(self.evidence);changed[self.key].update(change)
            self.assertIsNone(restatement_evidence("짧게 요약해줘",self.history,changed))

    def test_missing_last_answer_evidence_does_not_resurrect_older_success(self):
        history=self.history+[{"role":"assistant","text":"조회 실패", "evidence":[]}]
        self.assertIsNone(restatement_evidence("요약해줘",history,self.evidence))

    def test_quarter_restatement_preserves_year_and_auto_basis(self):
        request=contextual_quarter("짧게 두 문장으로 요약해줘",self.history)
        self.assertEqual(request.token,"2025Q3:auto:3m:yoy")

    def test_annual_restatement_does_not_inherit_old_quarter(self):
        key="CMP_2024_2025_CFS_REVENUE"
        history=self.history+[{"role":"user","text":"2025년 연간 실적"},
            {"role":"assistant","text":"연간 설명","evidence":[dict(self.evidence[key],id=key)]}]
        self.assertIsNone(contextual_quarter("두 문장으로 요약해줘",history))
        self.assertEqual(set(restatement_evidence("두 문장으로 요약해줘",history,self.evidence)),{key})

    def test_news_restatement_does_not_expand_to_financial_facts(self):
        news="NEWS_1"
        history=[{"role":"assistant","text":"뉴스 설명","evidence":[dict(self.evidence[news],id=news)]}]
        self.assertEqual(set(restatement_evidence("뉴스를 두 문장으로 요약해줘",history,self.evidence)),{news})
        self.assertEqual(set(restatement_evidence("두 문장으로 요약해줘",history,self.evidence)),{news})

    def test_generation_examples_are_not_forced_copy_and_semantic_review_stays(self):
        settings=Settings("","","","",news_relevance_mode="strict")
        with patch("src.agents.chat._invoke",side_effect=fake_llm) as invoke:
            response=answer_question("그럼 영업이익률은?",self.result,self.history,settings)
        request=invoke.call_args_list[0].args[2]
        self.assertNotIn("must_include_sentences",request)
        self.assertEqual(invoke.call_args_list[-1].args[2]["task"],"chat_grounding_review")
        self.assertTrue(response.evidence)

    def test_quarter_fallback_keeps_provenance_and_is_never_counted_as_llm_analysis(self):
        response=_verified_fallback("실적",{self.key:self.evidence[self.key]},
            {"verified_sentence_examples":["영업이익률은 확인된 값입니다."]})
        self.assertEqual(response[1][0]["kind"],"quarterly_comparison")
        self.assertEqual(response[1][0]["answer_origin"],"verified_fallback")

    def test_legacy_fallback_request_still_retains_checked_facts(self):
        key="CMP_2024_2025_CFS_REVENUE"
        sentence="매출은 확인된 전년 비교입니다."
        result=_verified_fallback("실적",{key:self.evidence[key]}, {"must_include_sentences":[sentence]})
        self.assertIn(sentence,result[0])
        self.assertEqual(result[1][0]["answer_origin"],"verified_fallback")


class FollowupRoutingTests(unittest.TestCase):
    def test_summary_routes_without_classifier_and_keeps_original_question(self):
        from src.agents.request import route_message
        settings=Settings("","","","")
        with patch("src.agents.request._invoke") as classify:
            intent=route_message("짧게 두 문장으로 요약해줘",None,"005930",[],settings)
        self.assertEqual(intent.action,"answer");classify.assert_not_called()

    def test_quarter_evaluation_does_not_switch_to_annual(self):
        from test_quarterly import evidence
        refs=evidence()
        history=[{"role":"user","text":"2025년 3분기 실적은?"},
                 {"role":"assistant","text":"실적 설명","evidence":[dict(v,id=k) for k,v in refs.items() if v["kind"]=="quarterly_comparison"]}]
        selected=select_evidence("그 정도면 괜찮아?",history,refs,[],strict=True)
        self.assertEqual(selected.reason,"quarterly")
        self.assertTrue(all(v["quarter"]==3 for v in selected.evidence.values()))

    def test_actual_ui_summary_keeps_subset_without_recollecting(self):
        from test_quarterly_flow import QuarterlyUiTests
        flow=QuarterlyUiTests("runTest");flow.setUp();self.addCleanup(flow.doCleanups)
        flow.flow.submit_theme("예시회사 2025년 3분기 실적은?")
        flow.flow.submit_theme("그럼 영업이익률은?")
        state=flow.flow.app.session_state
        before=state["dashboard_result"].result_id
        flow.flow.submit_theme("짧게 두 문장으로 요약해줘")
        refs=state["chat_messages"][-1]["evidence"]
        self.assertEqual({e["item"] for e in refs},{"operating_margin"})
        self.assertEqual(flow.collect.call_count,1)
        self.assertEqual(state["dashboard_result"].result_id,before)
        self.assertEqual(state["chat_request"].status,"completed")


class FinancialAdverbTests(unittest.TestCase):
    def test_discourse_adverb_does_not_change_exact_value_year_or_direction_checks(self):
        import re
        from src.agents.financial_numbers import mask_verified_comparisons
        from src.models import AppError
        fact={"kind":"annual_comparison","status":"ok","item":"selling_expenses_ratio",
              "stock_code":"123456","years":[2024,2025],"fs_div":"CFS",
              "previous":"27.12","current":"26.31","delta_pp":"-0.81","cost_bridge_reconciled":True}
        for adverb in ("", "또한 ", "역시 "):
            text=f"판매관리비율은 {adverb}2024년 27.12%에서 2025년 26.31%로 0.81%p 하락했습니다."
            self.assertFalse(re.search(r"\d",mask_verified_comparisons(text,{"CMP_SGA":fact})))
            for bad in (text.replace("0.81%p","0.82%p"),text.replace("2024년","2023년"),
                        text.replace("26.31%","26.32%"),text.replace("하락","상승")):
                with self.subTest(bad=bad), self.assertRaises(AppError):mask_verified_comparisons(bad,{"CMP_SGA":fact})


class DisplayedNewsFollowupTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {key: {"text": text,"url": "https://source.example/" + key,"stock_code": "005930"}
                         for key,text in (("NEWS_1","시장 기사"),("NEWS_4","브랜드 가치 기사"),("NEWS_8","사내대출 기사"))}
        self.message = {"role": "assistant", "text": "확인된 두 이슈입니다.",
                        "evidence": [dict(item,id=key) for key,item in self.evidence.items()],
                        "blocks": [{"evidence_ids": ["NEWS_4"]}, {"evidence_ids": ["NEWS_8"]}]}

    def select(self, question, history=None, evidence=None):
        return select_evidence(question, history if history is not None else [self.message],
                               evidence if evidence is not None else self.evidence, [], strict=True)

    def test_first_means_first_displayed_card_not_first_fetched_article(self):
        for question,key in (("첫 번째 이슈 자세히", "NEWS_4"),("두 번째 이슈 자세히", "NEWS_8"),("1번 이슈 자세히", "NEWS_4")):
            with self.subTest(question=question):
                selected=self.select(question)
                self.assertEqual(set(selected.evidence),{key})
                self.assertEqual(selected.required_ids,(key,))

    def test_summary_between_cards_and_followup_does_not_reset_order(self):
        history=[self.message,{"role":"user","text":"두 문장으로 요약"},
                 {"role":"assistant","text":"요약입니다.","evidence":self.message["evidence"]}]
        self.assertEqual(set(self.select("첫 번째 이슈 자세히",history).evidence),{"NEWS_4"})

    def test_missing_card_does_not_substitute_unshown_third_article(self):
        selected=self.select("세 번째 이슈 자세히")
        self.assertEqual(set(selected.evidence),{"NEWS_STATUS"})
        self.assertEqual(selected.evidence["NEWS_STATUS"]["status"],"displayed_issue_unavailable")

    def test_refreshed_article_id_cannot_silently_replace_historical_card(self):
        changed=deepcopy(self.evidence);changed["NEWS_4"]["url"]="https://different.example/"
        self.assertEqual(set(self.select("첫 번째 이슈 자세히",evidence=changed).evidence),{"NEWS_STATUS"})

    def test_legacy_number_selection_without_displayed_cards_is_preserved(self):
        self.assertEqual(set(self.select("첫 번째 이슈 자세히",history=[]).evidence),{"NEWS_1"})

    def test_brand_and_employee_loan_remain_distinct_without_inventing_impact(self):
        from src.agents.issues import group_issues,card_groups,validate_issue_cards
        from src.models import ChatResponse,AnswerBlock,AppError
        evidence={"NEWS_4":{"text":"삼성전자 글로벌 브랜드가치 세계 5위", "stock_name":"삼성전자"},
                  "NEWS_8":{"text":"삼성전자 사내대출 시행 후 동탄 집값 상승…19조 투자 천안", "stock_name":"삼성전자"}}
        groups=group_issues(evidence)
        self.assertEqual([g.kind for g in groups],["brand","employee_finance"])
        self.assertEqual(len(card_groups(groups)),2)
        good=ChatResponse("확인된 두 이슈입니다.",[],blocks=(
            AnswerBlock("브랜드", "보도된 브랜드 순위입니다.",("NEWS_4",)),
            AnswerBlock("사내대출", "보도된 사내대출입니다.",("NEWS_8",))))
        validate_issue_cards(good,evidence,groups)
        bad=replace(good,blocks=(replace(good.blocks[0],evidence_ids=("NEWS_4","NEWS_8")),))
        with self.assertRaises(AppError):validate_issue_cards(bad,evidence,groups)
        duplicated={**evidence,"NEWS_9":dict(evidence["NEWS_4"])}
        self.assertEqual(len(card_groups(group_issues(duplicated))),2)


class NewsPresentationFocusTests(unittest.TestCase):
    def test_single_followup_is_prose_but_explicit_cards_remain_cards(self):
        from src.agents.presentation import parse_presentation
        for question in ("첫 번째 이슈를 자세히 설명해줘", "그 뉴스의 의미는?"):
            self.assertEqual(parse_presentation(question,has_news=True).style,"plain")
        for question in ("첫 번째 이슈를 카드로 보여줘", "이슈 두 개 알려줘"):
            self.assertEqual(parse_presentation(question,has_news=True).style,"issues")

    def test_restatement_keeps_report_attribution_as_well_as_citations(self):
        item={"text":"가상회사 브랜드 가치 보도","scope":"article_excerpt"}
        selected=select_evidence("두 문장으로 요약해줘",[{"role":"assistant","text":"이슈입니다.",
            "evidence":[dict(item,id="NEWS_4")]}],{"NEWS_4":item},[],strict=True)
        self.assertTrue(any("귀속" in r for r in selected.requirements))

    def test_shortfall_is_a_request_contract_not_forced_three_cards(self):
        from src.agents.chat import _answer_request
        evidence={"NEWS_4":{"text":"가상회사 브랜드 가치 발표","stock_name":"가상회사","scope":"article_excerpt"}}
        request=_answer_request("이슈 세 가지 알려줘",synthetic_result(),[],[],evidence,[],[])
        self.assertEqual(request["news_answer_contract"]["available_issue_groups"],1)
        self.assertTrue(request["news_answer_contract"]["explain_shortfall"])


class ReportAttributionTests(unittest.TestCase):
    def test_report_prefix_is_scoped_and_does_not_add_facts_or_sentences(self):
        from src.agents.presentation import attribute_reported_news,sentences
        from src.models import ChatResponse
        response=ChatResponse("가상회사의 브랜드 가치가 유지됐습니다. 회사는 전략 효과를 설명했습니다.",
            [{"id":"NEWS_4","scope":"article_excerpt"}])
        updated=attribute_reported_news(response)
        self.assertTrue(updated.intro.startswith("관련 보도에 따르면, "))
        self.assertEqual(len(sentences(updated.intro)),2)
        self.assertEqual(updated.evidence,response.evidence)
        self.assertEqual(attribute_reported_news(updated),updated)
        for refs in ([{"id":"PER","scope":"metric"}], [{"id":"NEWS_4","scope":"official_disclosure"}],
                     [{"id":"NEWS_4","scope":"article_excerpt"},{"id":"CMP_A","kind":"annual_comparison"}],[]):
            other=replace(response,evidence=refs)
            self.assertEqual(attribute_reported_news(other),other)


class DisplayedIssueCountTests(unittest.TestCase):
    def test_only_actual_card_count_in_issue_intro_is_accepted(self):
        from src.agents.presentation import mask_displayed_issue_count
        self.assertEqual(mask_displayed_issue_count("확인된 이슈는 총 2건입니다.",2),"확인된 이슈는 총 건입니다.")
        for text,count in (("확인된 이슈는 총 3건입니다.",2),("계약 2건입니다.",2),
                           ("이슈는 2억원입니다.",2),("이슈는 2%입니다.",2),("확인된 이슈는 2건입니다.",None)):
            self.assertEqual(mask_displayed_issue_count(text,count),text)

    def test_count_does_not_approve_duplicate_cards_or_wrong_financial_numbers(self):
        from src.agents.chat import validate_response
        from src.models import AppError
        evidence={"NEWS_4":{"text":"가상회사 브랜드가치 발표","stock_name":"가상회사"},
                  "NEWS_8":{"text":"가상회사 사내대출 시행","stock_name":"가상회사"}}
        blocks=[{"title":"브랜드 가치","text":"브랜드 가치 발표 보도입니다.","evidence_ids":["NEWS_4"]},
                {"title":"사내대출","text":"사내대출 시행 보도입니다.","evidence_ids":["NEWS_8"]}]
        payload={"text":"확인된 이슈는 총 2건입니다.","evidence_ids":["NEWS_4","NEWS_8"],"follow_up":"","blocks":blocks}
        self.assertEqual(len(validate_response(payload,evidence,"issues").blocks),2)
        for change in ({"text":"확인된 이슈는 총 3건입니다."},
                       {"text":"확인된 이슈는 총 2건이며 매출은 999억원입니다."},
                       {"blocks":[blocks[0],{**blocks[1],"evidence_ids":["NEWS_4"]}]}):
            with self.subTest(change=change),self.assertRaises(AppError):
                validate_response({**payload,**change},evidence,"issues")


class SingleMetricRepetitionTests(unittest.TestCase):
    def test_same_margin_delta_is_not_repeated_in_explanation(self):
        from src.agents.presentation import enforce_single_margin_change
        from src.models import ChatResponse,AppError
        ref={"id":"Q_CMP_MARGIN","kind":"quarterly_comparison","item":"operating_margin","delta_pp":"2.531436879"}
        good=ChatResponse("이익률은 11.61%에서 14.14%로 2.53%p 올랐으며 매출에서 이익으로 남기는 비중이 커졌습니다.",[ref])
        enforce_single_margin_change(good)
        bad=replace(good,intro=good.intro+" 이는 2.53%p 개선됐다는 뜻입니다.")
        with self.assertRaises(AppError):enforce_single_margin_change(bad)
        # 서로 다른 항목에 같은 변화가 있는 정상 비교를 반복으로 오인하지 않는다.
        enforce_single_margin_change(replace(bad,evidence=[ref,{**ref,"id":"OTHER","item":"other_margin"}]))

    def test_generic_source_prefix_is_replaced_not_stacked(self):
        from src.agents.presentation import attribute_reported_news
        from src.models import ChatResponse
        response=ChatResponse("확인된 자료에 따르면 가상회사의 브랜드 가치가 유지됐습니다.",
                             [{"id":"NEWS_4","scope":"article_excerpt"}])
        self.assertEqual(attribute_reported_news(response).intro,"관련 보도에 따르면, 가상회사의 브랜드 가치가 유지됐습니다.")


class OutlookSelectionTests(unittest.TestCase):
    def setUp(self):
        self.result=synthetic_result()
        self.evidence=build_evidence(self.result)

    def test_outlook_does_not_force_all_old_financial_comparisons(self):
        selected=select_evidence("내년에는 주가가 오를까?",[],self.evidence,[],strict=True)
        self.assertEqual(selected.reason,"outlook")
        self.assertEqual(selected.required_ids,())
        self.assertEqual(selected.required_groups["outlook_background"]["mode"],"any")
        self.assertNotIn("PER",selected.evidence)
        self.assertNotIn("PRICE",selected.evidence)
        self.assertTrue(any("아직 오지 않은" in r for r in selected.requirements))

    def test_unrelated_brand_ranking_is_not_earnings_forecast_evidence(self):
        evidence={**self.evidence,"NEWS_4":{"text":"가상회사 브랜드가치 세계 5위","stock_name":"가상회사"},
                  "NEWS_8":{"text":"가상회사 장비 공급 계약","stock_name":"가상회사"}}
        selected=select_evidence("내년 실적 전망은?",[],evidence,[],strict=True)
        self.assertNotIn("NEWS_4",selected.evidence)
        self.assertIn("NEWS_8",selected.evidence)

    def test_future_price_question_is_not_implicitly_a_current_quote_lookup(self):
        from src.agents.chat import _direct_answer
        _,required,_=_direct_answer("내년 주가가 오를까?",self.result,[],self.evidence,strict=True)
        self.assertNotIn("PRICE",required)
        _,required,_=_direct_answer("지금 주가와 내년 전망을 함께 알려줘",self.result,[],self.evidence,strict=True)
        self.assertIn("PRICE",required)

    def test_multi_fact_restatement_may_cite_relevant_subset_but_not_outside_sources(self):
        keys=[k for k,v in self.evidence.items() if v.get("kind")=="annual_comparison"][:2]
        history=[{"role":"user","text":"내년 주가는?"},{"role":"assistant","text":"전망 설명입니다.",
                  "evidence":[dict(self.evidence[k],id=k) for k in keys]}]
        selected=select_evidence("한 문장으로 요약해줘",history,self.evidence,[],strict=True)
        self.assertEqual(set(selected.evidence),set(keys))
        self.assertEqual(selected.required_ids,())
        self.assertEqual(selected.required_groups["summary_source"]["mode"],"any")

    def test_repeated_restatement_retains_original_question_not_last_summary_command(self):
        from src.agents.followup import restatement_origin
        history=[{"role":"user","text":"내년 주가가 오를까?"},{"role":"assistant","text":"전망 설명"},
                 {"role":"user","text":"한 문장으로 요약해줘"},{"role":"assistant","text":"요약"}]
        self.assertEqual(restatement_origin(history),"내년 주가가 오를까?")


class ValuationDeferralTests(unittest.TestCase):
    def test_explicit_deferral_is_not_a_value_assertion_and_later_assertion_still_fails(self):
        from src.agents.report import asserts_valuation
        self.assertFalse(asserts_valuation("저평가로 단정하기보다는 실적 변화를 함께 고려해야 합니다."))
        self.assertTrue(asserts_valuation("저평가입니다. 그렇게 단정하기보다는 자료를 볼 수도 있습니다."))
        self.assertTrue(asserts_valuation("저평가로 단정하기보다는 확인해야 하지만 이 기업은 저평가입니다."))


class NewsSummaryCoverageTests(unittest.TestCase):
    def test_summary_keeps_each_issue_but_duplicate_sources_are_any_not_all(self):
        evidence={"NEWS_4":{"text":"가상회사 브랜드가치 발표","stock_name":"가상회사","scope":"article_excerpt"},
                  "NEWS_11":{"text":"가상회사 브랜드가치 발표 소식","stock_name":"가상회사","scope":"article_excerpt"},
                  "NEWS_8":{"text":"가상회사 사내대출 시행","stock_name":"가상회사","scope":"article_excerpt"}}
        history=[{"role":"assistant","text":"두 이슈입니다.","evidence":[dict(v,id=k) for k,v in evidence.items()]}]
        selected=select_evidence("두 문장으로 요약해줘",history,evidence,[],strict=True)
        self.assertEqual(selected.required_ids,())
        self.assertEqual(len(selected.required_groups),2)
        self.assertIn({"mode":"any","ids":["NEWS_4","NEWS_11"]},selected.required_groups.values())
        self.assertIn({"mode":"any","ids":["NEWS_8"]},selected.required_groups.values())


class OutlookGenerationViewTests(unittest.TestCase):
    def test_generation_view_keeps_all_facts_and_does_not_mutate_validation_or_fallback(self):
        from src.agents.outlook import generation_request,GENERATION_INSTRUCTION
        request={"evidence":{"CMP_X":{"value":"123"}},"required_groups":{"background":{"mode":"any","ids":["CMP_X"]}},
                 "verified_sentence_examples":["원본 검증 문장"],"comparison_style":"rates"}
        view=generation_request(request)
        self.assertEqual(view["evidence"],request["evidence"])
        self.assertEqual(view["required_groups"],request["required_groups"])
        self.assertNotIn("verified_sentence_examples",view)
        self.assertNotIn("comparison_style",view)
        self.assertEqual(request["verified_sentence_examples"],["원본 검증 문장"])
        self.assertIn("회계기준",GENERATION_INSTRUCTION)


class OutlookInterpretationBoundaryTests(unittest.TestCase):
    def test_criteria_modality_is_not_a_price_hypothesis_but_actual_hypothesis_remains(self):
        from src.agents.interpretation import classify_unit
        evidence={"CMP_X":{"kind":"annual_comparison","item":"operating_income"}}
        good={"id":"intro_0","statement":"내년 주가 상승 여부는 수요와 비용을 확인해야 판단할 수 있습니다.","evidence":evidence}
        self.assertNotEqual(classify_unit(good).tier,"T4")
        for text in ("주가가 오를 수 있으며 수요를 확인해야 판단할 수 있습니다.",
                     "주가가 확실히 상승할 것입니다. 수요를 확인해야 판단할 수 있습니다.",
                     "공장 가동으로 출하가 늘 수 있으며 수요를 확인해야 판단할 수 있습니다."):
            with self.subTest(text=text):self.assertEqual(classify_unit({**good,"statement":text}).tier,"T4")

    def test_per_quote_cannot_establish_relative_low_price_and_warning_does_not_immunize(self):
        from src.agents.interpretation import classify_unit
        unit={"id":"intro_0","evidence":{"PER":{"value":"10.81"}},
              "statement":"이는 단순히 주가가 이익 대비 낮은 수준임을 나타낼 뿐 투자 적정성을 단정하는 기준은 아닙니다."}
        self.assertIn("relative_per_without_benchmark",classify_unit(unit).flags)
        self.assertIn("relative_per_without_benchmark",classify_unit({**unit,"statement":"현재 PER은 낮은 수준입니다."}).flags)
        good={**unit,"statement":"PER은 주가가 주당순이익의 몇 배인지 나타내며 이 값만으로 저평가를 단정할 수 없습니다."}
        self.assertNotEqual(classify_unit(good).tier,"T4")
        deferred={**unit,"statement":"주가가 이익 대비 낮은 수준임을 확인할 수 없습니다."}
        self.assertNotIn("relative_per_without_benchmark",classify_unit(deferred).flags)


class InvestmentJudgementStyleTests(unittest.TestCase):
    def test_buy_judgement_is_separate_from_order_or_trade_flow_queries(self):
        from src.agents.outlook import uses_judgement_style,answer_context
        for text in ("PER이 낮으니 사도 되는 거야?","매수할까?","내년 주가가 오를까?"):
            self.assertTrue(uses_judgement_style(text))
        for text in ("외국인 매수 금액 알려줘","매수 뜻이 뭐야?","연간 영업이익은 얼마야?"):
            self.assertFalse(uses_judgement_style(text))
        self.assertEqual(answer_context("PER이 낮으니 사도 돼?",{})["focus"],"investment_judgement")


class ExpectedEarningsCriterionTests(unittest.TestCase):
    def test_expected_earnings_noun_in_advisory_comparison_is_not_a_price_prediction(self):
        from src.agents.interpretation import classify_unit
        unit={"id":"intro_0","evidence":{},"statement":"주가 향방을 판단하기 위해서는 향후 예상되는 이익과 그 기대치 대비 현재 가격을 함께 고려해야 합니다."}
        self.assertNotEqual(classify_unit(unit).tier,"T4")
        for text in ("예상되는 이익 증가로 주가가 오를 수 있으므로 현재 가격을 고려해야 합니다.",
                     "주가를 판단하기 위해서는 예상되는 이익과 현재 가격을 비교해야 하며 주가는 오를 수 있습니다.",
                     "예상되는 이익은 크게 늘어날 전망입니다."):
            with self.subTest(text=text):self.assertEqual(classify_unit({**unit,"statement":text}).tier,"T4")

    def test_outlook_horizon_and_future_actual_filler_are_checked_without_changing_facts(self):
        from src.agents.outlook import enforce_scope
        from src.models import ChatResponse,AppError
        response=ChatResponse("현재 자료에는 내년 이후의 확정된 실적 계획이 포함되어 있지 않습니다.",[])
        with self.assertRaises(AppError):enforce_scope(response,"올해 실적도 좋아질까?")
        enforce_scope(response,"내년 확정 실적은 나왔어?")
        enforce_scope(ChatResponse("올해 실적을 판단하려면 최근 회사 계획과 수요 변화를 확인해야 합니다.",[]),"올해 실적도 좋아질까?")


class EarningsHypothesisBoundaryTests(unittest.TestCase):
    def test_verified_contract_with_conditions_is_reviewable_not_automatically_approved(self):
        from src.agents.interpretation import classify_unit,apply_veto
        source={"NEWS_1":{"text":"가상회사 장비 공급 계약 체결"}}
        unit={"id":"intro_0","evidence":source,
              "statement":"확인된 공급 계약이 계획대로 이행되고 판매로 이어지면 매출이 늘어날 수 있습니다."}
        decision=classify_unit(unit)
        self.assertEqual(decision.tier,"T3")
        self.assertFalse(decision.flags)
        self.assertFalse(apply_veto({"supported":False},(decision,))["supported"])
        for change in ({"evidence":{"CMP_X":{"text":"지난해 연간 매출 증가"}}},
                       {"statement":"확인된 공급 계약으로 내년 매출이 크게 늘어날 수 있습니다."}):
            self.assertEqual(classify_unit({**unit,**change}).tier,"T4")


class RetrospectiveAssessmentTests(unittest.TestCase):
    def test_past_verified_assessment_is_not_an_earnings_forecast(self):
        from src.agents.interpretation import classify_unit
        unit={"id":"intro_0","evidence":{"CMP_X":{"kind":"annual_comparison","item":"operating_margin"}},
              "statement":"매출 증가와 함께 영업이익과 이익률이 개선되었으므로 실적이 전반적으로 좋아졌다고 판단할 수 있습니다."}
        self.assertEqual(classify_unit(unit).tier,"T2")
        self.assertEqual(classify_unit({**unit,"statement":"실적이 전반적으로 좋아질 수 있습니다."}).tier,"T4")
        self.assertEqual(classify_unit({**unit,"statement":"실적이 좋아질 수 있으며 작년에는 좋아졌다고 판단할 수 있습니다."}).tier,"T4")


class OutlookDirectnessTests(unittest.TestCase):
    def test_future_question_begins_with_requested_focus_not_only_old_numbers(self):
        from src.agents.outlook import enforce_scope,answer_context
        from src.models import ChatResponse,AppError
        old=ChatResponse("작년 매출과 영업이익이 증가했습니다. 내년 주가는 이익 기대와 현재 가격을 함께 봐야 합니다.",[])
        with self.assertRaises(AppError):enforce_scope(old,"내년 주가가 오를까?")
        enforce_scope(ChatResponse("과거 실적이 개선됐어도 내년 주가 상승을 보장하지는 않습니다. 앞으로 이익 기대와 가격을 함께 확인해야 합니다.",[]),"내년 주가가 오를까?")
        self.assertEqual(answer_context("올해 영업이익이 상승할까?",{})["focus"],"earnings_outlook")


class JudgementHistoryViewTests(unittest.TestCase):
    def test_prior_ai_wording_is_not_the_next_draft_but_source_state_is_preserved(self):
        from src.agents.outlook import generation_request
        history=[{"role":"user","text":"PER은?"},{"role":"assistant","text":"이전 긴 수치 답변"},
                 {"role":"user","text":"올해 실적은?"},{"role":"assistant","text":"직전 답변"}]
        request={"question":"내년 주가가 오를까?","conversation":history,"evidence":{"CMP_X":{"current":"123"}}}
        view=generation_request(request)
        self.assertTrue(all(m["role"]=="user" for m in view["conversation"]))
        self.assertEqual(request["conversation"],history)
        self.assertEqual(view["evidence"],request["evidence"])
        summary=generation_request({**request,"summary_of_question":"내년 주가가 오를까?"})
        self.assertEqual(summary["conversation"],history[-2:])
        review=generation_request({**request,"question":"이전 답변의 전망이 왜 틀렸어?"})
        self.assertEqual(review["conversation"],history)


class OutlookArrangementTests(unittest.TestCase):
    def test_only_sentence_order_changes_and_validation_sources_remain(self):
        from src.agents.outlook import arrange_conclusion,enforce_scope
        from src.agents.presentation import sentences
        from src.models import ChatResponse
        original=ChatResponse("지난해 매출과 이익이 증가했습니다. 이러한 흐름이 올해도 지속될지는 수요와 비용을 확인해야 판단할 수 있습니다.",[{"id":"CMP_X"}])
        updated=arrange_conclusion(original,"올해 실적도 좋아질까?")
        self.assertEqual(sorted(sentences(updated.intro)),sorted(sentences(original.intro)))
        self.assertTrue(updated.intro.startswith("이러한 흐름이 올해"))
        self.assertEqual(updated.evidence,original.evidence)
        self.assertTrue(original.intro.startswith("지난해"))
        enforce_scope(updated,"올해 실적도 좋아질까?")
        self.assertEqual(arrange_conclusion(original,"지난해 실적은?"),original)


class EmbeddedQuestionBoundaryTests(unittest.TestCase):
    def test_asking_to_check_continuation_is_not_claiming_continuation(self):
        from src.agents.interpretation import classify_unit
        unit={"id":"intro_0","evidence":{"PER":{"value":"10.81"}},
              "statement":"투자 판단을 위해서는 과거 이익 성장세가 지속될 수 있는지와 동종 업계의 배수를 확인해야 합니다."}
        self.assertNotEqual(classify_unit(unit).tier,"T4")
        for text in ("이익 성장세가 지속될 수 있습니다. 가능한지 확인해야 합니다.",
                     "이익은 늘어날 수 있으며 얼마나 지속될 수 있는지 확인해야 합니다."):
            self.assertEqual(classify_unit({**unit,"statement":text}).tier,"T4")

    def test_metric_placeholder_is_not_a_metric_name(self):
        from src.agents.chat import validate_answer
        from src.models import AppError
        evidence={"PER":{"value_text":"10.81배","value":10.81,"status":"ok"}}
        payload={"text":"현재 {{PER}}은 10.81배입니다.","evidence_ids":["PER"],"follow_up":""}
        with self.assertRaises(AppError):validate_answer(payload,evidence)
        validate_answer({**payload,"text":"현재 PER은 {{PER}}입니다."},evidence)


class ForwardPlanAvailabilityTests(unittest.TestCase):
    def test_company_plan_missing_is_material_and_not_future_actual_filler(self):
        from src.agents.outlook import enforce_scope
        from src.models import ChatResponse,AppError
        plan=ChatResponse("현재 자료에는 내년 실적에 대한 확정된 회사 계획이 포함되어 있지 않습니다.",[])
        enforce_scope(plan,"내년 실적 전망은?")
        enforce_scope(ChatResponse("현재 자료에는 내년 이후의 확정된 실적 계획이 포함되어 있지 않습니다.",[]),"내년 실적 전망은?")
        actual=ChatResponse("내년 실적 전망을 확정할 수는 없습니다. 현재 자료에는 내년의 확정된 연간 실적이 없습니다.",[])
        with self.assertRaises(AppError):enforce_scope(actual,"내년 실적 전망은?")


class StockPriceFocusTests(unittest.TestCase):
    def test_product_selling_price_is_not_stock_price_conclusion(self):
        from src.agents.outlook import arrange_conclusion,enforce_scope,answer_context
        from src.models import ChatResponse
        response=ChatResponse("내년 실적은 수요와 판매 가격을 확인해야 판단할 수 있습니다. 과거 실적이 개선됐어도 내년 주가 상승을 보장하지는 않습니다.",[])
        updated=arrange_conclusion(response,"내년 주가가 오를까?")
        self.assertTrue(updated.intro.startswith("과거 실적이"))
        enforce_scope(updated,"내년 주가가 오를까?")
        self.assertEqual(answer_context("내년 제품 판매 가격 전망은?",{})["focus"],"earnings_outlook")


class ComparisonCitationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.evidence=build_evidence(synthetic_result())
        self.revenue="CMP_2024_2025_CFS_REVENUE"
        self.income="CMP_2024_2025_CFS_OPERATING_INCOME"

    def test_unique_exact_rounded_comparison_uses_original_numeric_validator(self):
        from src.agents.financial_numbers import comparison_source_ids
        from src.agents.chat import recover_evidence_ids,validate_response
        from src.agents.financial_numbers import verified_sentence
        text=verified_sentence(self.evidence[self.revenue])+" "+verified_sentence(self.evidence[self.income])
        payload={"text":text,"evidence_ids":[],"follow_up":"","blocks":[]}
        self.assertEqual(set(comparison_source_ids(text,self.evidence)),{self.revenue,self.income})
        updated=recover_evidence_ids(payload,self.evidence)
        self.assertEqual(set(updated["evidence_ids"]),{self.revenue,self.income})
        validate_response(updated,self.evidence,"plain")
        self.assertEqual(payload["evidence_ids"],[])
        self.assertEqual(comparison_source_ids("매출 증가율(20.00%)",self.evidence),(self.revenue,))

    def test_wrong_value_direction_year_and_ambiguous_basis_are_not_approved(self):
        from src.agents.financial_numbers import verified_sentence,comparison_source_ids
        from src.agents.chat import recover_evidence_ids,validate_response
        from src.models import AppError
        text=verified_sentence(self.evidence[self.revenue])
        wrong=[text.replace("증가","감소"),text.replace("20.00%","21.00%"),"2023년 "+text]
        for body in wrong:
            payload={"text":body,"evidence_ids":[],"follow_up":"","blocks":[]}
            with self.subTest(body=body),self.assertRaises(AppError):
                validate_response(recover_evidence_ids(payload,self.evidence),self.evidence,"plain")
        ambiguous={**self.evidence,"OFS_REVENUE":{**self.evidence[self.revenue],"fs_div":"OFS"}}
        self.assertNotIn(self.revenue,comparison_source_ids(text,ambiguous))


class SafeDisplayNormalizationTests(unittest.TestCase):
    def test_only_redundant_same_verified_parenthetical_is_removed(self):
        from src.agents.presentation import deduplicate_margin_note
        from src.models import ChatResponse
        ref={"id":"Q_CMP_MARGIN","kind":"quarterly_comparison","item":"operating_margin","delta_pp":"2.531436879"}
        original=ChatResponse("이익률은 11.61% → 14.14% (2.53%p 상승)로, 전년 대비 2.53%p 상승했습니다.",[ref])
        fixed=deduplicate_margin_note(original)
        self.assertEqual(fixed.intro.count("2.53%p"),1)
        self.assertIn("11.61% → 14.14%",fixed.intro)
        self.assertEqual(fixed.evidence,original.evidence)
        single=replace(original,intro="이익률은 11.61% → 14.14% (2.53%p 상승)입니다.")
        self.assertEqual(deduplicate_margin_note(single),single)
        ambiguous=replace(original,evidence=[ref,{**ref,"id":"OTHER","item":"other_margin"}])
        self.assertEqual(deduplicate_margin_note(ambiguous),ambiguous)

    def test_metric_name_is_repaired_but_incorrect_value_stays_rejected(self):
        from src.agents.presentation import normalize_metric_subject
        from src.agents.chat import validate_answer
        from src.models import AppError
        evidence={"PER":{"value_text":"10.81배","value":10.81,"status":"ok"}}
        self.assertEqual(normalize_metric_subject("현재 {{PER}}은 10.81배입니다.",evidence),"현재 PER은 10.81배입니다.")
        normal=normalize_metric_subject("현재 {{PER}}은 999배입니다.",evidence)
        with self.assertRaises(AppError):validate_answer({"text":normal,"evidence_ids":["PER"],"follow_up":""},evidence)
        self.assertEqual(normalize_metric_subject("현재 {{PBR}}은 값입니다.",evidence),"현재 {{PBR}}은 값입니다.")


class CostQuestionOperandSelectionTests(unittest.TestCase):
    def test_cost_focus_keeps_explicit_growth_operands_but_does_not_expand_simple_cost_question(self):
        result=synthetic_result();evidence=build_evidence(result)
        # 실제 원가 계산 모듈의 필드는 이 테스트에서 구조만 주입한다(모델/외부 호출 없음).
        for item in ("cost_of_sales_ratio","selling_expenses_ratio"):
            evidence["CMP_COST_"+item]={"kind":"annual_comparison","status":"ok","item":item,"years":[2024,2025],
                "fs_div":"CFS","cost_bridge_reconciled":True,"stock_code":result.target_code}
        selected=select_evidence("왜 영업이익이 매출보다 더 늘었어? 자세히 설명해줘",[],evidence,[],strict=True)
        fields={v.get("item") for v in selected.evidence.values() if v.get("kind")=="annual_comparison"}
        self.assertTrue({"revenue","operating_income","operating_margin","cost_of_sales_ratio","selling_expenses_ratio"}<=fields)
        simple=select_evidence("매출원가율과 판관비율의 관계를 설명해줘",[],evidence,[],strict=True)
        simple_fields={v.get("item") for v in simple.evidence.values() if v.get("kind")=="annual_comparison"}
        self.assertNotIn("revenue",simple_fields)
        self.assertNotIn("operating_income",simple_fields)


class MetricQuestionRoleTests(unittest.TestCase):
    def test_relative_assessment_does_not_force_repeating_definition(self):
        evidence={"PER":{"value_text":"10.81배","value":10.81,"status":"ok"}}
        relative=select_evidence("삼성전자 PER은 어떤 수준이야?",[],evidence,["PER"],strict=True)
        self.assertTrue(any("정의·공식을 반복하지" in r for r in relative.requirements))
        meaning=select_evidence("이 종목 PER의 의미를 설명해줘",[],evidence,["PER"],strict=True)
        self.assertTrue(any("값과 그 의미" in r for r in meaning.requirements))
