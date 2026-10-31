import json
import unittest
from copy import deepcopy

from src.agents.providers.local_payload import compact_messages


class LocalPayloadTests(unittest.TestCase):
    def test_display_duplicates_removed_but_financial_basis_and_exact_values_remain(self):
        payload={'question':'현재 종목 어떻게 생각해?', 'stock_name':'현재 회사',
                 'evidence':{'CMP_1':{'text':'회사 매출 표시','value_text':'100억원 → 120억원',
                 'previous':'10000000000','current':'12000000000','change_pct':'20.0',
                 'item':'revenue','source':'OpenDART','period':'2024→2025 연간','fs_div':'CFS',
                 'currency':'KRW','as_of':'2025-12-31','retrieved_at':'2026-10-27',
                 'result_id':'r1','stock_code':'123456','status':'ok','reason':''}}}
        before=deepcopy(payload)
        projected=json.loads(compact_messages([('human',json.dumps(payload))])[0][1])
        item=projected['evidence']['CMP_1']
        self.assertNotIn('text',item)
        self.assertNotIn('retrieved_at',item)
        for key in ('value_text','previous','current','change_pct','item','source','period','fs_div','currency','as_of','status','stock_code'):
            self.assertEqual(item[key],payload['evidence']['CMP_1'][key])
        self.assertEqual(payload,before)

    def test_news_scope_and_fact_qualifiers_are_not_compacted_away(self):
        item={'text':'회사 잠정 매출 400억원','excerpt':'원문 내용','scope':'article_excerpt',
              'structured_facts':[{'status':'verified','qualifier':'provisional','validity':'historical',
                  'ownership_basis':'aggregate','value':'40000000000','unit':'원'}],
              'relationship_proofs':[{'scope':'official_disclosure','quote':'공식 역할','validity':'document_only'}]}
        output=compact_messages([('human',json.dumps({'evidence':{'NEWS_1':item}}))])
        self.assertEqual(json.loads(output[0][1])['evidence']['NEWS_1'],item)

    def test_zero_and_false_values_are_not_missing(self):
        payload={'evidence':{'PBR':{'value':0,'status':'ok','valid':False},
                             'EPS':{'value':None,'status':'missing','reason':'이익 자료 없음'}}}
        output=json.loads(compact_messages([('human',json.dumps(payload))])[0][1])
        self.assertEqual(output['evidence']['PBR']['value'],0)
        self.assertIs(output['evidence']['PBR']['valid'],False)
        self.assertEqual(output['evidence']['EPS']['reason'],'이익 자료 없음')

    def test_question_and_instructions_unchanged_without_evidence(self):
        payload={'question':'원문 질문','conversation':[{'text':'이전 종목'}]}
        output=compact_messages([('system','검사 정책'),('human',json.dumps(payload))])
        self.assertEqual(output[0],('system','검사 정책'))
        self.assertEqual(json.loads(output[1][1]),payload)

    def test_scoped_review_check_keys_and_units_preserved(self):
        from src.agents.answer_quality import QUALITY_CHECKS
        payload={'task':'chat_grounding_review','review_profile':'scoped-v1',
                 'quality_checks':QUALITY_CHECKS,'review_units':[{'id':'intro_0','statement':'검사할 원문'}],
                 'required_groups':{'financial':{'mode':'all','ids':['CMP_1']}}}
        before=deepcopy(payload)
        output=json.loads(compact_messages([('human',json.dumps(payload))])[0][1])
        self.assertEqual(set(output['quality_checks']),set(QUALITY_CHECKS))
        self.assertEqual(output['review_units'],payload['review_units'])
        self.assertEqual(output['required_groups'],payload['required_groups'])
        self.assertEqual(payload,before)
