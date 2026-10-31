"""V03: 같은 원자료의 비용 항등식과 실제 답변 수치·효용 경계 검사."""
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch
import unittest

from scripts.llm_fixture import synthetic_result
from src.agents.answer_quality import select_evidence
from src.agents.chat import validate_answer, answer_question
from src.agents.evidence import build_evidence
from src.agents.interpretation import decisions_for, classify_unit
from src.data.cost_structure import cost_structure_evidence
from src.models import FinancialAccountRow, FinancialStatementData, AnnualFinancialSummary, AppError
from test_financial_interpretation import approve, unit
from src.config import Settings


CODE='123456'
SCALE=Decimal('1e8')


def statement(year, revenue,cost,sga,income,basis='CFS'):
    rows=tuple(FinancialAccountRow('IS',tag,name,key,Decimal(value)*SCALE,
                 bsns_year=str(year),fs_div=basis,rcept_no='fixture'+str(year))
        for tag,name,key,value in (
            ('ifrs-full_Revenue','매출액','revenue',revenue),
            ('ifrs-full_CostOfSales','매출원가','',cost),
            ('nonstandard_sga','판매비와관리비','',sga),
            ('dart_OperatingIncomeLoss','영업이익','operating_income',income)))
    return FinancialStatementData(CODE,'00123456',str(year),'11011',basis,rows=rows,status='ok')


def cost_result():
    return replace(synthetic_result(),financial_statements=(statement(2024,1000,700,200,100),statement(2025,1200,780,240,180)),
        annual_summaries=(AnnualFinancialSummary('2024',revenue=1000*SCALE,operating_income=100*SCALE),
                          AnnualFinancialSummary('2025',revenue=1200*SCALE,operating_income=180*SCALE)))


class CostStructureTests(unittest.TestCase):
    def setUp(self):
        self.result=cost_result()
        self.settings=Settings('fixture','fixture','','')

    def test_reconciled_cost_ratios_have_exact_values_periods_and_input_ids(self):
        facts=cost_structure_evidence(self.result.financial_statements,stock_code=CODE,result_id='cost')
        cost=facts['CMP_2024_2025_CFS_COST_OF_SALES_RATIO']
        sga=facts['CMP_2024_2025_CFS_SELLING_EXPENSES_RATIO']
        self.assertEqual((Decimal(cost['previous']),Decimal(cost['current']),Decimal(cost['delta_pp'])),(70,65,-5))
        self.assertEqual((Decimal(sga['previous']),Decimal(sga['current']),Decimal(sga['delta_pp'])),(20,20,0))
        self.assertEqual(len(cost['input_fact_ids']),8)
        self.assertEqual(cost['years'],[2024,2025])
        self.assertTrue(cost['cost_bridge_reconciled'])

    def test_missing_account_mixed_basis_or_period_or_unbalanced_statement_not_used(self):
        old,current=self.result.financial_statements
        cases=((old,replace(current,rows=current.rows[:-1])),(old,replace(current,fs_div='OFS')),
               (old,replace(current,reprt_code='11012')),(old,statement(2025,1200,780,240,999)),
               (replace(old,code='654321'),current),(old,old,current))
        for statements in cases:
            with self.subTest(statements=statements):
                self.assertFalse(cost_structure_evidence(statements,stock_code=CODE,result_id='cost'))

    def test_zero_revenue_wrong_currency_or_conflicting_duplicate_account_is_not_used(self):
        old,current=self.result.financial_statements
        wrong=replace(current,rows=current.rows+(replace(current.rows[1],amount=Decimal(700)*SCALE),))
        currency=replace(current,rows=tuple(replace(row,currency='USD') for row in current.rows))
        for candidate in (statement(2025,0,0,0,0),currency,wrong):
            with self.subTest(candidate=candidate):
                self.assertFalse(cost_structure_evidence((old,candidate),stock_code=CODE,result_id='cost'))

    def test_mismatched_annual_summary_is_not_combined_with_cost_statement(self):
        for income in (999*SCALE,None,True,'NaN','bad'):
            modified=replace(self.result,annual_summaries=(self.result.annual_summaries[0],
                replace(self.result.annual_summaries[1],operating_income=income)))
            with self.subTest(income=income):
                self.assertFalse(any(v.get('cost_bridge_reconciled') for v in build_evidence(modified).values()))

    def test_causal_question_selects_available_costs_instead_of_only_outcomes(self):
        selection=select_evidence('왜 영업이익이 매출보다 많이 늘었어?',[],build_evidence(self.result),[],strict=True)
        items={item.get('item') for item in selection.evidence.values()}
        self.assertTrue({'cost_of_sales_ratio','selling_expenses_ratio','operating_margin'}<=items)
        self.assertTrue(any('원가/판관비 비중' in requirement for requirement in selection.requirements))
        # 실제 후속 원인 질문의 두 비교 항목을 제거하면 정상 증감률도 출처를 잃는다.
        self.assertTrue({'revenue','operating_income'}<=items)
        cost_only=select_evidence('매출원가율과 판관비율의 관계를 설명해줘',[],build_evidence(self.result),[],strict=True)
        self.assertFalse(any(item.get('item')=='revenue' for item in cost_only.evidence.values()))
        self.assertFalse(any(item.get('item')=='operating_income' for item in cost_only.evidence.values()))

    def test_cost_question_requests_financial_data_when_not_collected_yet(self):
        from src.agents.request import request_scope
        from src.analysis_flow import needs_data
        from src.models import now_kst
        for question in ('원가율을 설명해줘','판관비율은 어떤 편이야?','판매관리비를 비교해줘'):
            with self.subTest(question=question):
                self.assertEqual(request_scope(question),'financials')
                result=replace(self.result,section_status={'dart':'not_collected'})
                self.assertTrue(needs_data(result,'financials',question,now=now_kst(),dart_enabled=True))

    def test_verified_cost_pairs_and_stable_sga_are_allowed_but_wrong_unit_or_value_rejected(self):
        evidence=build_evidence(self.result)
        keys=['CMP_2024_2025_CFS_COST_OF_SALES_RATIO','CMP_2024_2025_CFS_SELLING_EXPENSES_RATIO']
        good='매출원가율은 70%에서 65%로 낮아졌고 판관비율은 20%로 유지됐습니다.'
        self.assertIn('70%',validate_answer({'text':good,'evidence_ids':keys,'follow_up':''},evidence)[0])
        for text in (good.replace('65%','60%'),good.replace('20%','25%'),good.replace('낮아졌','높아졌'),
                     '매출원가율은 5% 하락했습니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                validate_answer({'text':text,'evidence_ids':keys,'follow_up':''},evidence)

    def test_cost_ratio_fall_does_not_mean_absolute_cost_cut(self):
        evidence=build_evidence(self.result)
        self.assertTrue(classify_unit(unit('원가 절감 덕분에 이익이 증가했습니다.',evidence)).flags)
        self.assertFalse(classify_unit(unit('매출 대비 원가 부담이 낮아져 수익성이 개선됐습니다.',evidence)).flags)

    def test_available_costs_not_deferred_but_missing_detail_limit_still_allowed(self):
        evidence=build_evidence(self.result)
        text='원가 자료를 추가로 조사해야 이유를 알 수 있습니다.'
        self.assertIn('available_cost_data_deferred',decisions_for([unit(text,evidence)],question='왜 늘었어?',evidence=evidence)[0].flags)
        no_cost={'CMP':{'kind':'annual_comparison','text':'매출과 이익 증가'}}
        self.assertFalse(decisions_for([unit(text,no_cost)],question='왜 늘었어?',evidence=no_cost)[0].flags)

    def test_complete_cost_answer_reaches_shared_review_without_unsupported_business_cause(self):
        evidence=build_evidence(self.result)
        keys=[key for key,item in select_evidence('왜 영업이익이 늘었어?',[],evidence,[],strict=True).evidence.items() if item.get('kind')=='annual_comparison']
        text='매출원가율은 70%에서 65%로 낮아졌고 판관비율은 20%로 유지됐습니다. 비용 비중이 낮아진 만큼 영업이익률이 높아졌습니다.'
        payload={'text':text,'evidence_ids':keys,'follow_up':'','blocks':[]}
        def invoke(settings,instruction,request,*args,**kwargs):
            return payload if request['task']=='chat_answer' else approve(settings,instruction,request,*args,**kwargs)
        with patch('src.agents.chat._invoke',side_effect=invoke):
            response=answer_question('왜 영업이익이 늘었어?',self.result,[],self.settings)
        self.assertIn('매출원가율은 70%에서 65%',response.text)
        self.assertNotIn('추가로 조사',response.text)


if __name__=='__main__':
    unittest.main()
