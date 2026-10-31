import sys, os, json, time
sys.path.insert(0, "."); sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")
from dataclasses import replace
from src.config import load_settings
from src.agents.chat import answer_question
from src.models import AppError
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals

settings = load_settings()
print("provider:", settings.ai_provider)
base = sample_result()
result = replace(base, annual_summaries=annuals(), commentary=replace(base.commentary, stock_comment=""))

QUESTIONS = [
    ("overview", "이 종목 어때?"),
    ("cause", "영업이익이 왜 그렇게 변했어?"),
    ("outlook", "내년 전망은 어때?"),
    ("news", "최근 뉴스 이슈 알려줘"),
    ("news_one", "뉴스 한 문장으로 요약해줘"),
    ("three_lines", "실적을 세 줄로 요약해줘"),
    ("simple", "실적을 초보자도 알기 쉽게 설명해줘"),
    ("detailed", "실적을 자세히 분석해줘"),
    ("per_eval", "PER이 낮으니 사도 돼?"),
    ("price_news_causal", "주가가 오른 건 뉴스 때문이야?"),
]
out = []
for tag, q in QUESTIONS:
    t0 = time.perf_counter()
    rec = {"tag": tag, "question": q}
    try:
        ans = answer_question(q, result, [], settings)
        text = ans.text if hasattr(ans, "text") else ans[0]
        refs = ans.evidence if hasattr(ans, "evidence") else ans[1]
        origin = sorted({e.get("answer_origin", "llm") for e in refs}) if refs else ["none"]
        rec.update(status="OK", text=text, evidence=[e.get("id") for e in refs], origin=origin)
    except AppError as e:
        rec.update(status="APPERROR", code=e.code, message=e.message)
    except Exception as e:
        rec.update(status="EXC", message=repr(e))
    rec["sec"] = round(time.perf_counter() - t0, 1)
    out.append(rec)
    print(f"\n[{tag}] {rec['status']} {rec['sec']}s origin={rec.get('origin')} {rec.get('code','')}")
    print(rec.get("text") or rec.get("message"))
os.makedirs("docs/검수", exist_ok=True)
json.dump(out, open("docs/검수/계획8_05_실모델_보강검수_2026-10-30.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
