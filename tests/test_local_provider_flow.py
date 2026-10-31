"""로컬 공급자 선택 후 실제 화면·수집·캔버스·파일 흐름. 네트워크는 대체한다."""
import unittest
from unittest.mock import patch
import httpx

import test_user_flow as flow
from src.config import Settings
from src.agents.answer_quality import QUALITY_CHECKS


class LocalProviderFlow(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    select_stock = flow.UserFlowTests.select_stock
    open_canvas = flow.UserFlowTests.open_canvas
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def use_local(self, news_mode="standard"):
        settings = Settings("", "", "fixture", "fixture", ai_provider="local", local_model="fixture", news_relevance_mode=news_mode)
        self.stack.enter_context(patch("src.pipeline.load_settings", return_value=settings))
        self.stack.enter_context(patch("src.config.load_settings", return_value=settings))
        self.requests = []
        self.client = self.stack.enter_context(patch("src.agents.providers.local.httpx.Client"))

        def respond(url, *, json, headers):
            import json as json_module
            request = json_module.loads(json["messages"][1]["content"])
            self.requests.append(request)
            if request.get("task") == "chat_grounding_review":
                payload = {"checks": dict.fromkeys(QUALITY_CHECKS, True), "supported": True,
                           "answers_question": True, "reason": "모의 판정",
                           "unit_reviews": [{"id": u["id"], "supported": True, "reason": "모의 판정"}
                                            for u in request["review_units"]]}
                if request.get("review_profile") == "scoped-v1":
                    for reviewed, unit in zip(payload["unit_reviews"], request["review_units"]):
                        reviewed.update(on_topic=True, relevance_evidence_ids=unit["evidence_ids"])
            elif request.get("task") == "news_relevance":
                payload = {"assessments": [{"id": a["id"], "relation": "company" if request["stock_name"] in a["title"] else "unknown",
                           "subject_quote": request["stock_name"] if request["stock_name"] in a["title"] else "",
                           "support_quote": a["title"]} for a in request["articles"]]}
            elif "headlines" in request:
                payload = flow.report_payload(stock_name=request["stock_name"], price=request["price"], per=request["per"])
            else:
                payload = {"stocks": ["예시회사", "회사나", "회사다"]}
            return httpx.Response(200, json={"choices": [{"message": {"content": json_module.dumps(payload, ensure_ascii=False)},
                                                         "finish_reason": "stop"}]})

        self.post = self.client.return_value.__enter__.return_value.post
        self.post.side_effect = respond

    def test_theme_selection_canvas_and_excel_use_local_without_cloud(self):
        self.use_local()
        self.submit_theme()
        self.select_stock("005930")
        result = self.app.session_state["dashboard_result"]
        self.assertEqual(result.target_code, "005930")
        self.assertTrue(result.commentary)
        self.assertFalse(self.app.session_state.filtered_state.get("canvases"))
        self.open_canvas()
        canvas = self.app.session_state["canvases"][0]
        self.assertEqual(canvas["result"].result_id, result.result_id)
        self.app.button(key=f"prepare_export_{canvas['canvas_id']}").click().run()
        self.assert_no_exception()
        canvas = self.app.session_state["canvases"][0]
        self.assertTrue(canvas["export_bytes"].startswith(b"PK"))
        self.assertEqual(canvas["result"].target_code, "005930")
        self.assertEqual(len(self.requests), 3)  # 후보, 기본 설명, 의미 심사
        self.groq.assert_not_called()

    def test_local_server_failure_keeps_candidates_and_does_not_open_canvas(self):
        self.use_local()
        self.submit_theme()
        self.post.side_effect = httpx.ConnectError("fixture unavailable")
        self.select_stock("005930")
        self.assert_no_exception()
        self.assertTrue(self.app.session_state["candidate_result"].candidates)
        self.assertFalse(self.app.session_state.filtered_state.get("canvases"))
        messages = self.app.session_state["chat_messages"]
        self.assertTrue(any("로컬 AI 서버" in (m.get("analysis_error") or "") for m in messages))
        self.assertIsNone(self.app.session_state["dashboard_result"].commentary)
        self.groq.assert_not_called()

    def test_strict_policy_keeps_full_news_in_canvas_and_excel_with_usage_labels(self):
        from io import BytesIO
        import openpyxl
        self.use_local(news_mode="strict")
        self.news_response.json.return_value = {"items": [
            {"title": "예시회사 반도체 생산라인 가동 계획 발표", "originallink": "https://example.com/company",
             "pubDate": "Tue, 13 Oct 2026 09:00:00 +0900"},
            {"title": "다른그룹 지주회사 경영 강화", "originallink": "https://example.org/group",
             "pubDate": "Tue, 13 Oct 2026 09:00:00 +0900"}]}
        self.submit_theme()
        self.select_stock("005930")
        result = self.app.session_state["dashboard_result"]
        self.assertEqual(len(result.news.articles), 2)
        self.assertIsNotNone(result.news.admission)
        self.assertIsNotNone(result.commentary)
        report_request = next(r for r in self.requests if "headlines" in r)
        self.assertEqual([a["id"] for a in report_request["headlines"]], [1])
        before = len(self.requests)
        self.open_canvas()
        self.assertEqual(len(self.requests), before)
        self.assertTrue(any("분석 근거 미채택" in c.value for c in self.app.caption))
        canvas = self.app.session_state["canvases"][0]
        self.app.button(key=f"prepare_export_{canvas['canvas_id']}").click().run()
        self.assert_no_exception()
        workbook = openpyxl.load_workbook(BytesIO(self.app.session_state["canvases"][0]["export_bytes"]), read_only=True)
        rows = list(workbook["관련뉴스"].values)
        self.assertEqual(rows[4][1], "예시회사 반도체 생산라인 가동 계획 발표")
        self.assertEqual(rows[5][1], "다른그룹 지주회사 경영 강화")
        self.assertIn("미채택", rows[5][5])
        workbook.close()
        self.groq.assert_not_called()
