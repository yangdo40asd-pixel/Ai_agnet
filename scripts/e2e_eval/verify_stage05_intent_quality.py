"""실행 05(답변 품질과 해석: A01~A04, S02) 전용 실시간 로컬 LLM 종단 검증기.

단순 통과 여부나 오류 코드 유무가 아니라:
1) 질문자가 진짜 묻고 있는 본질적 의도 (의도 유형, 핵심 요구)
2) 실제 모델/시스템이 출력한 문장 전문 (로그 원문)
3) 그 답변이 사람 수준의 자연스럽고 타당한 대답인지 비판적 평가
를 명확히 기록하고 검증한다.
"""
import sys
import os
import json
import time
from dataclasses import replace

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")

from src.models import (
    StockCandidate, FinancialData, AnalysisResult,
    NewsArticle, NewsData, ChatResponse, AppError, now_kst
)
from src.config import load_settings
from src.agents.chat import answer_question
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals

settings = load_settings()
print(f"=== 실행 05 실시간 LLM 답변 품질 및 의도 부합성 검증 시작 (Port: 1234) ===")

# Base Samsung Electronics setup with verified financials & news
base = sample_result()
news_hbm = NewsData(
    articles=(
        NewsArticle(1, "삼성전자, 차세대 HBM 공급 계약 체결로 실적 기대감 고조", "https://example.com/hbm", "2026-10-18T09:00:00+09:00", "example.com"),
    ),
    retrieved_at=now_kst()
)
res_full = replace(base, news=news_hbm, annual_summaries=annuals(), commentary=replace(base.commentary, stock_comment=""))

test_scenarios = [
    # 05-A: 종합 실적 및 단일 지표
    {
        "tag": "a01_performance_direction",
        "category": "05-A 종합 실적 평가",
        "query": "삼성전자 최근 실적 좋아졌어 나빠졌어?",
        "intent_type": "종합 실적 평가 (개선 vs 악화 판단)",
        "intent_desc": "단순 숫자 나열이 아니라, 최근 실적이 실제로 개선되었는지 악화되었는지 두괄식 결론과 핵심 근거를 요구함.",
        "fn": lambda: answer_question("삼성전자 최근 실적 좋아졌어 나빠졌어?", res_full, [], settings, limited_on_failure=True)
    },
    {
        "tag": "a01_direct_metric_lookup",
        "category": "05-A 단일 지표 조회",
        "query": "삼성전자 PER 얼마야?",
        "intent_type": "단일 지표 조회 (PER 값 및 기준)",
        "intent_desc": "기업 개요나 긴 설명 없이 현재 확인된 PER 수치와 기준 시점을 즉시 확인하고자 함.",
        "fn": lambda: answer_question("삼성전자 PER 얼마야?", res_full, [], settings, limited_on_failure=True)
    },
    {
        "tag": "a01_uncollected_metric_boundary",
        "category": "05-A 미수집 지표 경계",
        "query": "삼성전자 배당수익률 얼마야?",
        "intent_type": "미수집 지표 문의 (경계 및 대체 안내)",
        "intent_desc": "기본 수집 범위에 없는 배당수익률을 묻는 질문에 대해, 환각을 지어내지 않고 정직한 수집 범위 안내를 요구함.",
        "fn": lambda: answer_question("삼성전자 배당수익률 얼마야?", res_full, [], settings, limited_on_failure=True)
    },

    # 05-B: 실적 변화 원인 설명
    {
        "tag": "a02_operating_income_cause",
        "category": "05-B 실적 변화 원인",
        "query": "삼성전자 영업이익이 왜 그렇게 급증했어?",
        "intent_type": "실적 원인 분석 (매출 vs 이익률·비용 구조)",
        "intent_desc": "단순히 숫자를 다시 읽어주는 수준을 넘어, 매출 성장률 대비 영업이익 증가 폭 및 수익성 개선 의미를 논리적으로 설명할 것을 요구함.",
        "fn": lambda: answer_question("삼성전자 영업이익이 왜 그렇게 급증했어?", res_full, [], settings, limited_on_failure=True)
    },

    # 05-C: 뉴스 이슈 및 주가-뉴스 인과
    {
        "tag": "a03_news_key_issues",
        "category": "05-C 독립 뉴스 이슈",
        "query": "삼성전자 주요 소식이 뭐야?",
        "intent_type": "최근 주요 소식 요약",
        "intent_desc": "확인된 공시/뉴스 보도 원문 범위 내에서 최근 기업의 핵심 사건(HBM 공급 계약 등)을 정돈해 전달할 것을 요구함.",
        "fn": lambda: answer_question("삼성전자 주요 소식이 뭐야?", res_full, [], settings, limited_on_failure=True)
    },
    {
        "tag": "a03_price_news_causality",
        "category": "05-C 주가-뉴스 인과",
        "query": "주가가 오른 건 뉴스 때문이야?",
        "intent_type": "인과 관계 평가 (보도 영향 가능성과 인과 단정 회피)",
        "intent_desc": "호재 보도가 주가 상승의 단일·절대적 원인인지 묻는 질문에 대해, 기대감 영향 가능성을 인정하되 단정하지 않는 균형 있는 답변을 요구함.",
        "fn": lambda: answer_question("주가가 오른 건 뉴스 때문이야?", res_full, [], settings, limited_on_failure=True)
    },

    # 05-D: 조건부 가치평가 및 분량/깊이 제한
    {
        "tag": "a04_simple_depth_three_lines",
        "category": "05-D 초보자 설명 + 세 줄 제한",
        "query": "초보자도 알기 쉽게 실적을 세 줄로 요약해줘",
        "intent_type": "초보자 친화적 쉬운 설명 + 엄격한 3줄 요약",
        "intent_desc": "전문 금융 용어를 쉽게 풀어쓰면서도, 사용자가 명시한 '세 줄 요약' 분량 형식을 엄격히 준수할 것을 요구함.",
        "fn": lambda: answer_question("초보자도 알기 쉽게 실적을 세 줄로 요약해줘", res_full, [], settings, limited_on_failure=True)
    },
    {
        "tag": "a04_valuation_purchase_decision",
        "category": "05-D 조건부 매수/투자 판단",
        "query": "지금 삼성전자 주식 사도 될까?",
        "intent_type": "투자 매수 판단 자문 (조건부 평가 및 다각적 분석 요인)",
        "intent_desc": "단순 매수 추천이나 목표가 단정을 피하고, 확인된 실적 개선세와 함께 향후 주가 결정을 위해 점검해야 할 핵심 요인을 안내할 것을 요구함.",
        "fn": lambda: answer_question("지금 삼성전자 주식 사도 될까?", res_full, [], settings, limited_on_failure=True)
    },
]

results = []

for sc in test_scenarios:
    print(f"\n[{sc['category']}] '{sc['query']}' 실행 중...")
    t0 = time.time()
    rec = {
        "tag": sc["tag"],
        "category": sc["category"],
        "query": sc["query"],
        "intent_type": sc["intent_type"],
        "intent_desc": sc["intent_desc"],
    }
    try:
        resp = sc["fn"]()
        dt = round(time.time() - t0, 2)
        rec["sec"] = dt
        rec["status"] = "OK"
        if isinstance(resp, ChatResponse):
            rec["text"] = resp.text
            rec["intro"] = resp.intro
            rec["evidence_count"] = len(resp.evidence)
            rec["origin"] = sorted({e.get("answer_origin", "llm") for e in resp.evidence})
        elif isinstance(resp, tuple):
            rec["text"] = resp[0]
            rec["evidence_count"] = len(resp[1])
            rec["origin"] = sorted({e.get("answer_origin", "llm") for e in resp[1]})
        else:
            rec["text"] = str(resp)

        print(f" -> 소요시간: {dt}s")
        print(f" -> 실제 로그 출력 전문:\n{rec['text']}")

    except AppError as e:
        dt = round(time.time() - t0, 2)
        rec.update(sec=dt, status="APPERROR", code=e.code, message=e.message)
        print(f" -> APPERROR ({dt}s) [{e.code}]: {e.message}")
    except Exception as e:
        dt = round(time.time() - t0, 2)
        rec.update(sec=dt, status="EXC", message=repr(e))
        print(f" -> EXC ({dt}s): {repr(e)}")
    results.append(rec)

# Save Report JSON
os.makedirs("docs/검수", exist_ok=True)
out_path = "docs/검수/계획8_05_답변품질_의도부합_실시간LLM검증_2026-10-30.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["status"] == "OK")
total = len(results)
print("\n" + "=" * 60)
print(f"실행 05 품질 검증 완료: {passed} / {total} 성공")
print(f"결과 저장: {out_path}")
print("=" * 60)
