"""W-B에서 발생한 자연스러운 금액 표현과 가짜 자리표시자의 경계를 고정한다."""
from copy import deepcopy
import unittest

from scripts.verify_phase_w import fixture
from src.agents.chat import validate_response
from src.agents.evidence import build_evidence
from src.models import AppError


class RecordedWContractTests(unittest.TestCase):
    def setUp(self):
        self.result=fixture()
        self.evidence=build_evidence(self.result)

    def test_recorded_postposed_investment_is_a_valid_source_scoped_answer(self):
        payload={'text':'관련 보도에 따르면 삼성전자는 2000억원의 투자 계획을 발표했습니다.',
                 'evidence_ids':['NEWS_1'],'follow_up':'','blocks':[]}
        answer=validate_response(payload,self.evidence,'plain')
        self.assertIn('2000억원',answer.text)

    def test_recorded_invented_placeholder_remains_rejected_in_card(self):
        payload={'text':'관련 보도에 따르면 삼성전자는 2000억원의 투자 계획을 발표했습니다.',
                 'evidence_ids':['NEWS_1'],'follow_up':'',
                 'blocks':[{'title':'생산라인 투자 계획',
                            'text':'삼성전자는 {{investment_amount}} 투자를 계획했습니다.',
                            'evidence_ids':['NEWS_1'],'implication':None}]}
        with self.assertRaises(AppError) as raised:
            validate_response(payload,self.evidence,'issues')
        self.assertEqual(raised.exception.code,'chat_evidence')

    def test_valid_investment_number_cannot_become_revenue_or_foreign_number(self):
        payload={'text':'삼성전자 매출 2000억원입니다.','evidence_ids':['NEWS_1'],
                 'follow_up':'','blocks':[]}
        for text in ('삼성전자 매출 2000억원입니다.','삼성전자 3000억원 투자 계획입니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                validate_response({**deepcopy(payload),'text':text},self.evidence,'plain')
