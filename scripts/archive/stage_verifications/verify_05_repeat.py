import sys, json, time
sys.path.insert(0, "."); sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")
from dataclasses import replace
from src.config import load_settings
import src.agents.chat as chat
from src.models import AppError
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals

settings = load_settings()
base = sample_result()
result = replace(base, annual_summaries=annuals(), commentary=replace(base.commentary, stock_comment=""))
rows = []
for q in ["PER이 낮으니 사도 돼?", "삼성전자 어때?"]:
    for i in range(4):
        t0 = time.perf_counter()
        try:
            a = chat.answer_question(q, result, [], settings, limited_on_failure=True)
            text = a.text if hasattr(a, "text") else a[0]
            refs = a.evidence if hasattr(a, "evidence") else a[1]
            origin = sorted({e.get("answer_origin", "llm") for e in refs})
            dup = "배은" in text or "PER 15.20" in text
            rows.append((q, i, "OK", origin, dup, round(time.perf_counter()-t0, 1), text))
        except AppError as e:
            rows.append((q, i, "ERR:" + e.code, [], False, round(time.perf_counter()-t0, 1), ""))
for r in rows:
    print(r[0], r[1], r[2], r[3], "malformed" if r[4] else "clean", r[5], "s")
    if r[6]: print("   ", r[6][:260].replace("\n", " "))
json.dump([list(r) for r in rows], open("docs/검수/계획8_05_반복안정성_2026-10-30.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
