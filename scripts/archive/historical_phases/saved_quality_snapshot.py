"""실제 검수 기록의 숫자·출처를 복원하는 진단 도구. 제품 데이터 수집 경로에 사용하지 않는다."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from src.models import (AnalysisResult,AnnualFinancialSummary,QuarterlyFinancialSummary,
    FinancialData,FinancialAccountRow,FinancialStatementData,MetricValue,NewsData,StockCandidate)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("docs/검수/계획7-2_2026-10-28/after.json",
           "docs/검수/계획7-2_분기연결_2026-10-28/mixed.json")


def load_snapshot():
    annual_doc, quarter_doc = [json.loads((ROOT/path).read_text(encoding="utf-8")) for path in SOURCES]
    provenance = [{"path":path,"sha256":hashlib.sha256((ROOT/path).read_bytes()).hexdigest()} for path in SOURCES]
    annual_refs = {e["item"]:e for e in annual_doc["turns"][0]["evidence"]}
    costs = {e["item"]:e for e in annual_doc["turns"][1]["evidence"]}
    quarter_turn = quarter_doc["turns"][0]
    market = {e["id"]:e for e in quarter_turn["evidence"] if e["id"] in {"PRICE","PER"}}
    all_refs = [*annual_refs.values(), *costs.values(), *quarter_turn["evidence"]]
    assert all(e.get("stock_code")=="005930" for e in all_refs)
    stock = StockCandidate("삼성전자","005930","KOSPI","005930.KS")
    retrieved = datetime.fromisoformat(market["PRICE"]["retrieved_at"])
    metrics = {key:MetricValue(key, item["value"], "원" if key=="PRICE" else "배",
                    source=item["source"], period=item["period"], formula=item["formula"],
                    as_of=datetime.fromisoformat(item["as_of"]) if str(item["as_of"]).startswith("20") else None,
                    retrieved_at=datetime.fromisoformat(item["retrieved_at"]),status=item["status"])
               for key,item in market.items()}
    finance = FinancialData(stock,market["PRICE"]["value"],market["PER"]["value"],retrieved,
                            price_at=metrics["PRICE"].as_of,metrics=metrics)
    summaries=[];statements=[]
    years=annual_refs["revenue"]["years"]
    for year,side in zip(years,("previous","current")):
        revenue=Decimal(annual_refs["revenue"][side]); income=Decimal(annual_refs["operating_income"][side])
        summaries.append(AnnualFinancialSummary(str(year),revenue=revenue,operating_income=income))
        amounts={"revenue":revenue,"operating_income":income,
                 "cost_of_sales":Decimal(costs["cost_of_sales_ratio"][side+"_cost"]),
                 "selling_expenses":Decimal(costs["selling_expenses_ratio"][side+"_cost"])}
        rows=tuple(FinancialAccountRow("IS","",{"cost_of_sales":"매출원가","selling_expenses":"판매비와관리비"}.get(key,key),
                                      key,value,bsns_year=str(year)) for key,value in amounts.items())
        statements.append(FinancialStatementData("005930",None,str(year),"11011","CFS",rows=rows,
                                                retrieved_at=retrieved,status="ok"))
    quarters=tuple(QuarterlyFinancialSummary(**q) for q in quarter_turn["quarterly_summaries"])
    parents={p["year"]:p for e in quarter_turn["evidence"] for p in e.get("parents",())}
    for q in quarters:
        statements.append(FinancialStatementData("005930",None,q.bsns_year,q.reprt_code,q.fs_div,
            rcept_no=q.rcept_no,retrieved_at=datetime.fromisoformat(parents[q.bsns_year]["retrieved_at"]),status="ok"))
    result=AnalysisResult("삼성전자",(stock,),finance,NewsData((),retrieved,status="not_collected"),None,
                          annual_summaries=tuple(summaries),quarterly_summaries=quarters,
                          financial_statements=tuple(statements),result_id="saved-real-quality-evaluation",
                          section_status={"dart":"ok","dart_quarterly":"ok","quarterly_request":"2025Q3:auto:3m:yoy"})
    return result,provenance
