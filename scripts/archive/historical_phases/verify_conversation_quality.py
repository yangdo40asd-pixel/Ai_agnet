"""저장한 실제 API 근거로 로컬 대화를 새로 생성한다. 새 금융 API/UI 실측이 아니다."""
import argparse
from contextlib import ExitStack
from dataclasses import replace,asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from saved_quality_snapshot import load_snapshot
from src.agents.chat import answer_question
from src.agents.providers import local
from src.config import load_settings
from src.models import (AppError,now_kst,StockCandidate,QuarterlyFinancialSummary,FinancialAccountRow,
    FinancialStatementData,AnalysisResult,FinancialData,NewsData,NewsArticle)

QUESTIONS=(
    "삼성전자 2025년 3분기 실적은 좋은 편이야? 세 문장으로 설명해줘.",
    "그럼 영업이익률은?",
    "짧게 두 문장으로 요약해줘.",
    "그럼 2025년 연간 실적은 좋은 편이야?",
    "왜 영업이익이 매출보다 많이 늘었어? 자세히 설명해줘.",
)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--count",type=int,default=3)
    parser.add_argument("--suite",choices=("context","periods","news","judgement","outlook","margin","metric"),default="context")
    parser.add_argument("--source-file",type=Path)
    parser.add_argument("--news-limit",type=int,choices=(10,20),default=10)
    args=parser.parse_args()
    settings=load_settings()
    if settings.ai_provider!="local":raise SystemExit("local 공급자에서만 검수합니다.")
    result,provenance=load_snapshot()
    questions=QUESTIONS
    cases=[]
    if args.suite == "judgement":
        questions=("PER가 무슨 뜻이야?", "삼성전자 PER은 어떤 수준이야?",
                   "그럼 PER이 낮으니 사도 되는 거야?", "올해 실적도 좋아질까?",
                   "내년에는 주가가 오를까?", "방금 답변을 한 문장으로 정리해줘.")
    if args.suite=="metric":
        questions=("PER가 무슨 뜻이야?","삼성전자 PER은 어떤 수준이야?")
    if args.suite=="margin":
        questions=("삼성전자 2025년 3분기 영업이익률은?","짧게 두 문장으로 요약해줘.")
    if args.suite=="outlook":
        questions=("올해 실적도 좋아질까?","내년에는 주가가 오를까?","방금 답변을 한 문장으로 정리해줘.")
    if args.suite in {"periods","news"}:
        if args.source_file is None:raise SystemExit("실제 수집 기록 --source-file이 필요합니다.")
        import hashlib
        data=json.loads(args.source_file.read_text(encoding="utf-8"))
        provenance.append({"path":str(args.source_file),"sha256":hashlib.sha256(args.source_file.read_bytes()).hexdigest()})
        if args.suite=="news":
            raw=data["news"]
            news=NewsData(tuple(NewsArticle(**a) for a in raw["articles"][:args.news_limit]),datetime.fromisoformat(raw["retrieved_at"]),
                          status=raw["status"],source=raw["source"],queries=tuple(raw.get("queries",())))
            result=replace(result,news=news,result_id="saved-real-news-quality")
            questions=("삼성전자 최근 주요 이슈 세 가지를 자세히 알려줘.",
                       "방금 이슈를 두 문장으로 요약해줘.",
                       "첫 번째 이슈를 조금 더 자세히 설명해줘.")
        else:
            for period in data["periods"]:
                stock=StockCandidate(**data["stocks"][period["name"]])
                statements=[]
                for statement in period["statements"]:
                    kwargs=dict(statement)
                    kwargs["retrieved_at"]=datetime.fromisoformat(kwargs["retrieved_at"])
                    kwargs["rows"]=tuple(FinancialAccountRow(**{**r,"amount":Decimal(str(r["amount"])) if r["amount"] is not None else None,
                                                             "cumulative_amount":Decimal(str(r["cumulative_amount"])) if r["cumulative_amount"] is not None else None})
                                         for r in kwargs["rows"])
                    kwargs["annual_history"]=();kwargs["quarterly_history"]=()
                    statements.append(FinancialStatementData(**kwargs))
                snapshot=AnalysisResult(stock.name,(stock,),FinancialData(stock,None,None,now_kst(),collection_status="not_collected"),
                    NewsData((),now_kst(),status="not_collected"),None,
                    quarterly_summaries=tuple(QuarterlyFinancialSummary(**q) for q in period["summaries"]),
                    financial_statements=tuple(statements),result_id=f"saved-real-{stock.code}-{period['quarter']}")
                cases.append((f"{stock.name} 2025년 {period['quarter']}분기 실적은 좋은 편이야? 세 문장으로 설명해줘.",snapshot))
    record={"kind":"saved real API facts; fresh local generation; no new finance API or browser/UI", "started_at":now_kst().isoformat(),
            "sources":provenance,"events":[],"turns":[],"max_llm_calls":16,"max_seconds":240}
    record["provided_news_count"] = len(result.news.articles)
    import hashlib
    record["code_sha256"]={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in
                           ("src/agents/chat.py","src/agents/quarterly.py","src/agents/followup.py",
                            "src/agents/answer_quality.py","src/agents/financial_numbers.py",
                            "src/agents/issues.py","src/agents/presentation.py","src/agents/outlook.py",
                            "src/agents/report.py","src/agents/interpretation.py")}
    start=time.monotonic();history=[]
    def save():args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    original=local.invoke
    def invoke(settings,instruction,payload,max_tokens,temperature):
        if len(record["events"])>=16 or time.monotonic()-start>240:
            raise AppError("ai_verification_budget","검수 예산 종료")
        event={"task":payload.get("task"),"question":payload.get("question"),
               "generation_profile":"judgement" if payload.get("outlook_answer_context") else "general",
               "instruction_sha256":hashlib.sha256(instruction.encode()).hexdigest(),
               "request_sha256":hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest(),
               "validation_error":payload.get("validation_error"),
               "required_groups":payload.get("required_groups",{})};record["events"].append(event)
        save();begin=time.monotonic()
        try:
            reply=original(settings,instruction,payload,max_tokens,temperature)
            event.update(response=reply.content,finish=reply.finish_reason,usage=reply.usage)
            return reply
        except AppError as error:event["error_code"]=error.code;raise
        finally:event["seconds"]=round(time.monotonic()-begin,3);save()
    with ExitStack() as stack:
        cloud=stack.enter_context(patch("langchain_groq.ChatGroq",side_effect=AssertionError("Groq 금지")))
        network=stack.enter_context(patch("requests.sessions.Session.request",side_effect=AssertionError("외부 자료 재수집 금지")))
        stack.enter_context(patch.object(local,"invoke",invoke))
        for case_index, (question, snapshot) in enumerate((cases or [(q,result) for q in questions])[:args.count]):
            result=snapshot
            if args.suite=="periods":history=[]
            print("START",question,flush=True)
            turn={"question":question};record["turns"].append(turn)
            index=len(record["events"]);begin=time.monotonic()
            try:
                reply=answer_question(question,result,history,settings)
                text,refs,follow=reply
                blocks=[asdict(b) for b in getattr(reply,"blocks",())]
                turn.update(status="returned",answer=text,evidence=refs,blocks=blocks,history_size=len(history))
                history.extend([{"role":"user","text":question},{"role":"assistant","text":text,"evidence":refs,"blocks":blocks}])
            except AppError as error:turn.update(status="failed",error_code=error.code,message=error.message)
            turn.update(seconds=round(time.monotonic()-begin,3),llm_calls=len(record["events"])-index)
            record.update(groq_calls=cloud.call_count,external_requests=network.call_count);save()
            print(json.dumps({k:v for k,v in turn.items() if k!="evidence"},ensure_ascii=False),flush=True)
            if turn["status"]=="failed":break
    record["elapsed_seconds"]=round(time.monotonic()-start,3);save()
    if any(turn.get("status")!="returned" for turn in record["turns"]):
        raise SystemExit(2)

if __name__=="__main__":main()
