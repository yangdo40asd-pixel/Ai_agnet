"""기타영업항목이 있는 실제 손익 구조의 동일기간·회계기준·항등식 대조."""
import json
import unittest
from pathlib import Path
from dataclasses import replace
from decimal import Decimal
from src.data.cost_structure import cost_structure_evidence
from src.models import FinancialAccountRow,FinancialStatementData,AppError
from src.agents.financial_numbers import verified_sentence,mask_verified_comparisons
from src.agents.answer_quality import model_evidence
from src.agents.chat import validate_answer
from test_cost_structure import statement,CODE,SCALE


def add_other(s, value, *, account_id='dart_OtherOperatingIncome',name='기타영업수익'):
    row=FinancialAccountRow('IS',account_id,name,'',Decimal(value)*SCALE,bsns_year=s.bsns_year)
    return replace(s,rows=(*s.rows,row))


class OperatingCostBridgeTests(unittest.TestCase):
    def pair(self):
        return (add_other(statement(2024,1000,700,200,110),10),
                add_other(statement(2025,800,650,220,-50),20))

    def test_official_other_operating_income_reconciles_without_residual_guessing(self):
        e=cost_structure_evidence(self.pair(),stock_code=CODE,result_id='test')
        cost=e['CMP_2024_2025_CFS_COST_OF_SALES_RATIO']
        self.assertEqual(Decimal(cost['previous']),70)
        self.assertEqual(Decimal(cost['current']),Decimal('81.25'))
        self.assertEqual(cost['other_operating_components']['other_operating_income']['current'],str(20*SCALE))
        self.assertEqual(len(cost['input_fact_ids']),10)

    def test_missing_other_account_or_nonoperating_income_cannot_fill_gap(self):
        old,new=self.pair()
        for s in (replace(new,rows=new.rows[:-1]),
                  replace(new,rows=(*new.rows[:-1],replace(new.rows[-1],account_id='dart_OtherGains',account_nm='기타수익'))),
                  replace(new,rows=(*new.rows[:-1],replace(new.rows[-1],account_id='dart_OtherLosses',account_nm='기타비용')))):
            self.assertFalse(cost_structure_evidence((old,s),stock_code=CODE,result_id='test'))

    def test_conflicting_or_missing_or_wrong_basis_optional_value_does_not_default_to_zero(self):
        old,new=self.pair(); row=new.rows[-1]
        for s in (replace(new,rows=(*new.rows,replace(row,amount=row.amount+1))),
                  replace(new,rows=(*new.rows[:-1],replace(row,amount=None))),
                  replace(new,rows=(*new.rows[:-1],replace(row,fs_div='OFS'))),
                  replace(new,rows=(*new.rows[:-1],replace(row,currency='USD')))):
            self.assertFalse(cost_structure_evidence((old,s),stock_code=CODE,result_id='test'))

    def test_explicit_other_operating_expense_uses_its_own_sign(self):
        old=add_other(statement(2024,1000,700,200,90),10,account_id='dart_OtherOperatingExpenses',name='기타영업비용')
        new=add_other(statement(2025,800,650,220,-90),20,account_id='dart_OtherOperatingExpenses',name='기타영업비용')
        self.assertTrue(cost_structure_evidence((old,new),stock_code=CODE,result_id='test'))
        self.assertFalse(cost_structure_evidence((old,replace(new,rows=new.rows[:-1])),stock_code=CODE,result_id='test'))

    def test_no_optional_account_creates_no_optional_fact(self):
        e=cost_structure_evidence((statement(2024,1000,700,200,100),statement(2025,1200,780,240,180)),stock_code=CODE,result_id='test')
        self.assertEqual(len(next(iter(e.values()))['input_fact_ids']),8)
        self.assertEqual(next(iter(e.values()))['other_operating_components']['other_operating_income']['present_in_source'],[False,False])

    def test_saved_real_sdi_cost_accounts_are_usable(self):
        doc=json.loads((Path(__file__).parent/'fixtures'/'plan8_sdi_cost_statements.json').read_text(encoding='utf8'))
        statements=[]
        for d in doc['statements']:
            d={**d,'rows':tuple(FinancialAccountRow(**r) for r in d['rows'])};statements.append(FinancialStatementData(**d))
        e=cost_structure_evidence(statements,stock_code='006400',result_id='real-test')
        self.assertEqual(len(e),2)
        cost=e['CMP_2024_2025_CFS_COST_OF_SALES_RATIO'];sga=e['CMP_2024_2025_CFS_SELLING_EXPENSES_RATIO']
        self.assertGreater(Decimal(cost['current']),Decimal(cost['previous']))
        self.assertGreater(Decimal(sga['current']),Decimal(sga['previous']))
        for fact in e.values():
            self.assertEqual(fact['years'],[2024,2025]);self.assertTrue(fact['cost_bridge_reconciled'])


class SignedComparisonSentenceTests(unittest.TestCase):
    def evidence(self):
        return {'CMP_OP':{'kind':'annual_comparison','status':'ok','item':'operating_income','stock_code':CODE,
                         'years':[2024,2025],'fs_div':'CFS','previous':'10000000000','current':'-5000000000','change_pct':None},
                'CMP_M':{'kind':'annual_comparison','status':'ok','item':'operating_margin','stock_code':CODE,
                         'years':[2024,2025],'fs_div':'CFS','previous':'10','current':'-5','delta_pp':'-15'}}

    def test_generated_transition_and_negative_margin_sentences_pass_exact_number_check(self):
        e=self.evidence()
        for item in e.values():
            sentence=verified_sentence(item)
            self.assertTrue(sentence)
            self.assertNotRegex(mask_verified_comparisons(sentence,e),r'\d')

    def test_wrong_signed_margin_pair_or_delta_still_rejected(self):
        e=self.evidence()
        for text in ('영업이익률은 10%에서 -4%로 15.00%p 하락했습니다.',
                     '영업이익률은 10%에서 -5%로 14.00%p 하락했습니다.',
                     '영업이익률은 10%에서 -5%로 15.00%p 상승했습니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):mask_verified_comparisons(text,e)

    def test_model_gets_individual_verified_sentences_without_forcing_rates_for_loss_transition(self):
        e=self.evidence();converted=model_evidence(e)
        self.assertTrue(all(v.get('verified_sentence') for v in converted.values()))
        self.assertNotIn('verified_sentence',e['CMP_OP'])
        mixed={**e,'OTHER':{**e['CMP_OP'],'fs_div':'OFS'}}
        self.assertNotIn('verified_sentence',model_evidence(mixed)['CMP_OP'])


if __name__=='__main__':unittest.main()
