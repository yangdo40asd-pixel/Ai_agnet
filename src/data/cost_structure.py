"""이미 수집한 손익계산서에서만 비용 구성을 계산한다. 새 API 호출·사업 원인 추정은 없다."""
from decimal import Decimal, InvalidOperation
import hashlib
import re

from src.formatting import format_percent


def _matching_rows(statement,field):
    ids={'revenue':{'ifrs-full_Revenue','ifrs_Revenue'},
         'cost_of_sales':{'ifrs-full_CostOfSales','ifrs_CostOfSales'},
         'selling_expenses':{'dart_TotalSellingGeneralAdministrativeExpenses'},
         'other_operating_income':{'dart_OtherOperatingIncome'},
         'other_operating_expenses':{'dart_OtherOperatingExpenses'},
         'operating_income':{'dart_OperatingIncomeLoss'}}[field]
    names={'revenue':{'매출액','매출'},'cost_of_sales':{'매출원가'},
           'selling_expenses':{'판매비와관리비','판매비및관리비','판매관리비','판관비'},
           'other_operating_income':{'기타영업수익'},
           'other_operating_expenses':{'기타영업비용'},
           'operating_income':{'영업이익','영업이익(손실)'}}[field]
    return [r for r in statement.rows if r.sj_div in {'IS','CIS'} and r.currency=='KRW'
          and r.bsns_year==statement.bsns_year and r.fs_div==statement.fs_div and r.reprt_code=='11011'
          and (r.standard_key==field or r.account_id in ids or re.sub(r'\s+','',r.account_nm) in names)]


def _amount(statement,field, *, absent=None):
    rows = _matching_rows(statement, field)
    if not rows:
        return absent
    values=[]
    for row in rows:
        if row.amount is None or isinstance(row.amount,bool):
            continue
        try:
            amount=Decimal(str(row.amount))
        except (InvalidOperation,ValueError):
            continue
        if amount.is_finite():
            values.append(amount)
    if not values or len(set(values))!=1:
        return None
    return values[0]


def cost_structure_evidence(statements, *, stock_code, result_id, annual_summaries=()):
    grouped={}
    for statement in statements:
        if (statement.code==stock_code and statement.status=='ok' and statement.reprt_code=='11011'
                and str(statement.bsns_year).isdigit() and statement.fs_div in {'CFS','OFS'}):
            grouped.setdefault((statement.fs_div,int(statement.bsns_year)),[]).append(statement)
    result={}
    for (basis,year),items in sorted(grouped.items()):
        previous=grouped.get((basis,year-1),())
        if len(items)!=1 or len(previous)!=1:
            continue
        frames=[]
        for statement in (previous[0],items[0]):
            values={field:_amount(statement,field) for field in ('revenue','cost_of_sales','selling_expenses','operating_income')}
            for field in ('other_operating_income', 'other_operating_expenses'):
                values[field] = _amount(statement, field, absent=Decimal(0))
            if (any(value is None for value in values.values()) or values['revenue']<=0
                    or min(values['cost_of_sales'],values['selling_expenses'])<0
                    or (values['revenue']-values['cost_of_sales']-values['selling_expenses']
                        + values['other_operating_income']-values['other_operating_expenses'])!=values['operating_income']):
                break
            frames.append(values)
        if len(frames)!=2:
            continue  # 불완전/다른 비용 체계는 이 항등식으로 설명하지 않는다.
        if annual_summaries:
            matched=[]
            for statement,frame in zip((previous[0],items[0]),frames):
                summaries=[s for s in annual_summaries if s.bsns_year==statement.bsns_year and s.fs_div==basis
                           and s.reprt_code=='11011' and s.currency=='KRW']
                if len(summaries)!=1:
                    break
                summary=summaries[0]
                try:
                    valid=(not isinstance(summary.revenue,bool) and not isinstance(summary.operating_income,bool)
                           and Decimal(str(summary.revenue)).is_finite() and Decimal(str(summary.operating_income)).is_finite()
                           and Decimal(str(summary.revenue))==frame['revenue']
                           and Decimal(str(summary.operating_income))==frame['operating_income'])
                except (InvalidOperation,ValueError,TypeError):
                    valid=False
                if not valid:
                    break
                matched.append(summary)
            if len(matched)!=2:
                continue
        inputs=[]
        for statement,frame in zip((previous[0],items[0]),frames):
            for field,value in frame.items():
                if field in {'other_operating_income', 'other_operating_expenses'} and not _matching_rows(statement, field):
                    continue  # 원문에 없는 계정을 독립 Fact로 만들지 않는다.
                raw=f'{stock_code}|{statement.bsns_year}|{basis}|{statement.rcept_no}|{field}|{value}'
                inputs.append('FS_'+hashlib.sha256(raw.encode()).hexdigest()[:14])
        for field,label in (('cost_of_sales','매출원가율'),('selling_expenses','판매관리비율')):
            old,new=(frame[field]/frame['revenue']*100 for frame in frames)
            delta=new-old
            value_text=f'{year-1}년 {format_percent(old)} → {year}년 {format_percent(new)} ({abs(delta):.2f}%p '+('상승' if delta>0 else '하락' if delta<0 else '변동 없음')+')'
            result[f'CMP_{year-1}_{year}_{basis}_{field.upper()}_RATIO']={
                'source':'OpenDART','scope':'financial_statement','kind':'annual_comparison','status':'ok',
                'stock_code':stock_code,'result_id':result_id,'years':[year-1,year],'period':f'{year-1}년 → {year}년 연간',
                'fs_div':basis,'currency':'KRW','item':field+'_ratio','previous':str(old),'current':str(new),
                'delta_pp':str(delta),'value_text':value_text,'text':label+': '+value_text,
                'previous_cost':str(frames[0][field]),'current_cost':str(frames[1][field]),
                'formula':field+' / revenue * 100; revenue - cost_of_sales - selling_expenses + other_operating_income - other_operating_expenses = operating_income',
                'other_operating_components': {
                    key: {'previous': str(frames[0][key]), 'current': str(frames[1][key]),
                          'present_in_source': [bool(_matching_rows(s, key)) for s in (previous[0],items[0])]}
                    for key in ('other_operating_income', 'other_operating_expenses')},
                'input_fact_ids':inputs,'cost_bridge_reconciled':True}
    return result
