"""한정된 실제 보고서·뉴스 수집. 모델 호출·설정 변경·재시도 루프 없음."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys,time
from urllib.parse import urlsplit
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.config import load_settings
from src.models import now_kst,AppError
from src.pipeline import identify_stock
from src.data.dart import fetch_corp_codes
from src.data.quarterly import collect_quarterly_financials
from src.data.report_period import QuarterRequest
from src.data.news import fetch_news
import requests


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    settings=load_settings();record={"started_at":now_kst().isoformat(),"http":[],"periods":[],"max_calls":24,"max_seconds":150}
    started=time.monotonic();original=requests.sessions.Session.request
    def save():args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    def request(session,method,url,*values,**kwargs):
        remaining=150-(time.monotonic()-started)
        if len(record["http"])>=24 or remaining<=0:raise requests.RequestException("검수 예산 종료")
        entry={"host":urlsplit(str(url)).hostname,"path":urlsplit(str(url)).path,
               "params":{k:v for k,v in (kwargs.get("params") or {}).items() if k in {"corp_code","bsns_year","reprt_code","fs_div"}}}
        record["http"].append(entry);begin=time.monotonic();kwargs["timeout"]=min(15,remaining)
        try:
            response=original(session,method,url,*values,**kwargs);entry["status"]=response.status_code;return response
        except requests.RequestException as error:entry["exception"]=type(error).__name__;raise
        finally:entry["seconds"]=round(time.monotonic()-begin,3);save()
    with patch("requests.sessions.Session.request",request):
        try:
            fetch_corp_codes(settings)  # 실패 시 같은 ZIP을 종목별로 반복하지 않는다.
            stocks={name:identify_stock(name) for name in ("삼성전자","SK하이닉스")}
            record["stocks"]={name:asdict(stock) for name,stock in stocks.items()};save()
            for name,quarter in (("삼성전자",1),("삼성전자",2),("삼성전자",4),("SK하이닉스",3)):
                print("COLLECT",name,quarter,flush=True)
                bundle=collect_quarterly_financials(stocks[name],QuarterRequest(2025,quarter),settings)
                record["periods"].append({"name":name,"quarter":quarter,"status":bundle["status"],
                    "summaries":[asdict(q) for q in bundle["summaries"]],"statements":[asdict(s) for s in bundle["statements"]],"calls":bundle["calls"]})
                save()
            news=fetch_news("반도체","삼성전자",settings)
            record["news"]=asdict(news);save()
        except AppError as error:record.update(error_code=error.code,message=error.message);save()
    record["seconds"]=round(time.monotonic()-started,3);save()
    print(json.dumps({"periods":[(p["name"],p["quarter"],p["status"],len(p["summaries"])) for p in record["periods"]],
                     "news_status":record.get("news",{}).get("status"),"news_count":len(record.get("news",{}).get("articles",[])),
                     "error_code":record.get("error_code"),"seconds":record["seconds"]},ensure_ascii=False))

if __name__=="__main__":main()
