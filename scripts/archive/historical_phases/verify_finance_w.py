"""W-C 금융 API 전용 검수. LLM/앱 실행 없이 실제 자료와 XLSX 바이트를 대조한다."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.config import load_settings
from src.models import AnalysisResult, AppError, FinancialData, NewsData, now_kst
from src.pipeline import identify_stock
from src.data.stock import load_listing, fetch_financial
from src.data.financials import collect_company_financials
from src.data.history import fetch_price_history
from src.data.news import fetch_news
from src.data.disclosures import collect_disclosures
from src.data.relations import extract_relationships
from src.agents.evidence import build_evidence
from src.export.excel import build_workbook_bytes, reconcile_workbook_values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-requests',type=int,default=28)
    parser.add_argument('--max-seconds',type=int,default=240)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('기존 기록을 덮어쓰지 않습니다.')
    settings=replace(load_settings(),request_timeout=12)
    record={'checked_at':now_kst().isoformat(),'synthetic_data':False,'scope':'finance_only_no_llm',
            'max_requests':args.max_requests,'max_seconds':args.max_seconds,'http':[], 'sections':{},
            'manual_visual_check':'not_run','llm_calls':0}
    started=time.monotonic()

    def save():
        record['elapsed_seconds']=round(time.monotonic()-started,3)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')

    def audited(original):
        def call(session,method,url,*values,**kwargs):
            remaining=args.max_seconds-(time.monotonic()-started)
            if remaining<=0 or len(record['http'])>=args.max_requests:
                import requests
                raise requests.RequestException('W-C request/time budget reached')
            parsed=urlsplit(str(url))
            if parsed.hostname in {'localhost','127.0.0.1'} or 'groq' in (parsed.hostname or ''):
                raise AssertionError('W-C에서 LLM 연결 금지')
            entry={'host':parsed.hostname,'path':parsed.path,'method':str(method).upper()}
            record['http'].append(entry)  # 쿼리·인증 헤더·외부 예외 원문은 저장하지 않는다.
            old_timeout=kwargs.get('timeout',12)
            kwargs['timeout']=min(float(old_timeout) if isinstance(old_timeout,(int,float)) else 12,12,remaining)
            t=time.monotonic()
            try:
                response=original(session,method,url,*values,**kwargs)
                entry['status']=response.status_code
                return response
            except Exception as error:
                entry['error_type']=type(error).__name__
                raise
            finally:
                entry['seconds']=round(time.monotonic()-t,3)
        return call

    def section(name,fn):
        t=time.monotonic()
        try:
            value=fn()
            record['sections'][name]={'returned':True,'seconds':round(time.monotonic()-t,3)}
            return value
        except AppError as error:
            record['sections'][name]={'returned':False,'error_code':error.code,'message':error.message}
        except Exception as error:
            record['sections'][name]={'returned':False,'error_type':type(error).__name__}
        finally:
            save()
            print(name, json.dumps(record['sections'].get(name,{}),ensure_ascii=False),flush=True)

    import requests
    import curl_cffi.requests
    with ExitStack() as stack:
        stack.enter_context(patch('requests.sessions.Session.request',audited(requests.sessions.Session.request)))
        stack.enter_context(patch('curl_cffi.requests.Session.request',audited(curl_cffi.requests.Session.request)))
        blocked=stack.enter_context(patch('src.agents.transport._invoke',side_effect=AssertionError('LLM 금지')))
        cloud=stack.enter_context(patch('langchain_groq.ChatGroq',side_effect=AssertionError('Groq 금지')))
        listing=section('krx',load_listing)
        if listing is None:
            record['status']='blocked_by_listing'
            save()
            return 1
        stock=identify_stock('005930',listing=listing)
        record['stock']=asdict(stock)
        record['sections']['krx'].update(status='ok',row_count=len(listing))
        financial=section('yahoo',lambda:fetch_financial(stock))
        if financial is not None:
            record['sections']['yahoo'].update(status=financial.collection_status, data=asdict(financial))
        else:
            financial=FinancialData(stock,None,None,now_kst(),collection_status='failed')
        bundle=section('dart',lambda:collect_company_financials(stock,settings,years=('2025','2024'))) or {}
        record['sections']['dart'].update(status=bundle.get('status','failed'),
                                         message=bundle.get('message'),
                                         summaries=[asdict(s) for s in bundle.get('annual_summaries',())])
        history=section('history',lambda:fetch_price_history(stock,'1M'))
        if history is not None:
            record['sections']['history'].update(status=history.status,bars=len(history.bars),code=history.code)
        news=section('naver',lambda:fetch_news('반도체',stock.name,settings)) or NewsData((),now_kst(),status='failed')
        record['sections']['naver'].update(status=news.status,queries=news.queries,
                                          articles=[asdict(a) for a in news.articles])
        documents,status=section('disclosures',lambda:collect_disclosures(stock,settings,'최근 공식 공시를 확인해 주세요')) or ((),'failed')
        relationships=extract_relationships(documents,stock)
        record['sections']['disclosures'].update(status=status,documents=[asdict(d) for d in documents],
                                                 relationships=[asdict(r) for r in relationships])
        result=AnalysisResult('반도체',(stock,),financial,replace(news,relationships=relationships),None,
                              result_id='w-c-'+uuid4().hex,price_history=history,
                              financial_statements=tuple(bundle.get('statements') or ()),
                              annual_summaries=tuple(bundle.get('annual_summaries') or ()),
                              financial_ratios=bundle.get('ratios'),financial_facts=tuple(bundle.get('facts') or ()),
                              source_documents=documents)
        evidence=build_evidence(result)
        record['result_id']=result.result_id
        record['evidence']=evidence
        record['data_snapshot']=asdict(result)
        record.update(llm_calls=blocked.call_count,groq_calls=cloud.call_count,status='data_collected_export_pending')
        save()  # 엑셀 대조 코드의 실패도 API 재조회 없이 재현할 수 있게 원자료를 먼저 보존한다.
        workbook=build_workbook_bytes(result)
        export=reconcile_workbook_values(result,workbook)
        record['export']=export
        record['xlsx_sha256']=hashlib.sha256(workbook).hexdigest()
        checks={key:export[key] for key in ('all_sheets_present','code_matches','price_matches','per_matches')}
        checks['no_formula_injection']=not export['formula_cells']
        checks['fact_company_matches']=all(f.stock_code==stock.code for f in result.financial_facts)
        checks['annual_basis_separate']=all(s.code==stock.code and s.fs_div=='CFS' for s in result.financial_statements)
        checks['actual_price_available']=financial.price is not None
        checks['actual_annual_available']=bool(result.annual_summaries)
        checks['actual_news_available']=bool(news.articles)
        checks['actual_history_available']=bool(history and history.bars)
        if result.annual_summaries:
            checks['xlsx_revenue_matches']=Decimal(str(export['latest_rev_krw']))==Decimal(str(result.annual_summaries[-1].revenue))
            latest_year=max(int(s.bsns_year) for s in result.annual_summaries)
            checks['ratio_latest_year_matches']=bool(result.financial_ratios and
                str(latest_year) in result.financial_ratios.operating_margin.period)
        record.update(checks=checks,llm_calls=blocked.call_count,groq_calls=cloud.call_count,
                      status='passed_data_checks' if all(checks.values()) else 'partial_or_failed')
        save()
    return 0 if record.get('status')=='passed_data_checks' else 1


if __name__=='__main__':
    sys.exit(main())
