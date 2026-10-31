"""실제 Port 8501 (Streamlit WebSocket) 및 Port 1234 (llama-server HTTP) 실시간 로그 검수 스크립트."""
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
import websocket
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

# 콘솔 인코딩 utf-8 설정
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LLM_LOG = ROOT / ".local_llm" / "resume16384.stderr.log"


def check_health():
    # 1. Port 1234 Health
    req_1234 = urllib.request.urlopen("http://127.0.0.1:1234/health", timeout=3)
    status_1234 = req_1234.getcode()
    body_1234 = json.loads(req_1234.read().decode())

    # 2. Port 8501 Health
    req_8501 = urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=3)
    status_8501 = req_8501.getcode()
    body_8501 = req_8501.read().decode()

    print(f"[HTTP Health] Port 1234: HTTP {status_1234} {body_1234} | Port 8501: HTTP {status_8501} {body_8501}")
    return status_1234 == 200 and status_8501 == 200


def get_llm_log_size():
    if LLM_LOG.exists():
        return LLM_LOG.stat().st_size
    return 0


def read_llm_log_delta(offset):
    if not LLM_LOG.exists():
        return "", offset
    with open(LLM_LOG, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        new_text = f.read()
        return new_text, f.tell()


def run_real_http_stream():
    assert check_health(), "서버 상태가 정상(200)이 아닙니다."

    log_offset = get_llm_log_size()
    print(f"[LLM Log] 시작 로그 오프셋: {log_offset} bytes")

    ws = websocket.create_connection(
        "ws://127.0.0.1:8501/_stcore/stream",
        subprotocols=["streamlit"],
        origin="http://127.0.0.1:8501",
        timeout=10,
    )

    try:
        widgets = {}
        # 1. 초기 세션 렌더링
        req = BackMsg()
        req.rerun_script.query_string = ""
        ws.send_binary(req.SerializeToString())

        initial_exceptions = []
        finished = False
        t0 = time.time()
        while not finished and time.time() - t0 < 30:
            try:
                data = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not isinstance(data, bytes):
                continue
            msg = ForwardMsg()
            msg.ParseFromString(data)
            if msg.WhichOneof("type") == "delta" and msg.delta.HasField("new_element"):
                el = msg.delta.new_element
                if el.HasField("text_input") and el.text_input.id.endswith("-composer_text"):
                    widgets["composer_text"] = el.text_input.id
                if el.HasField("button") and el.button.id.endswith("-composer_submit"):
                    widgets["composer_submit"] = el.button.id
                if el.HasField("exception"):
                    initial_exceptions.append((el.exception.type, el.exception.message))
            elif msg.WhichOneof("type") == "script_finished":
                finished = True

        print(f"[WS 8501] 초기 세션 완료: finished={finished}, widgets={list(widgets.keys())}, exceptions={initial_exceptions}")
        assert finished and not initial_exceptions, f"초기 세션 실행 실패: {initial_exceptions}"
        assert "composer_text" in widgets and "composer_submit" in widgets, "입력 위젯 미발견"

        # 2. 질문 제출 (반도체 탐색 질의)
        question = "반도체 관련 종목을 찾아줘"
        print(f"\n[WS 8501 -> Server] 질문 전송: '{question}'")
        req = BackMsg()
        req.rerun_script.query_string = ""
        field = req.rerun_script.widget_states.widgets.add()
        field.id = widgets["composer_text"]
        field.string_value = question
        submit = req.rerun_script.widget_states.widgets.add()
        submit.id = widgets["composer_submit"]
        submit.trigger_value = True
        ws.send_binary(req.SerializeToString())

        # 3. 실시간 스트림 수신 및 LLM 로그 관찰
        query_exceptions = []
        markdown_blocks = []
        buttons_rendered = []
        finished = False
        t_start = time.time()
        deadline = t_start + 180  # LLM 처리 및 브라우저 스트림 대기
        last_log_poll = time.time()

        while not finished and time.time() < deadline:
            try:
                data = ws.recv()
            except websocket.WebSocketTimeoutException:
                pass
            else:
                if isinstance(data, bytes):
                    msg = ForwardMsg()
                    msg.ParseFromString(data)
                    if msg.WhichOneof("type") == "delta" and msg.delta.HasField("new_element"):
                        el = msg.delta.new_element
                        if el.HasField("markdown"):
                            md_body = el.markdown.body
                            markdown_blocks.append(md_body)
                            first_line = md_body.strip().split("\n")[0][:60]
                            print(f"[WS 8501 Delta] Markdown: {first_line}...")
                        elif el.HasField("button"):
                            buttons_rendered.append(el.button.label)
                            print(f"[WS 8501 Delta] Button: {el.button.label}")
                        elif el.HasField("exception"):
                            query_exceptions.append((el.exception.type, el.exception.message))
                            print(f"[WS 8501 Delta] EXCEPTION: {el.exception.type} - {el.exception.message}")
                    elif msg.WhichOneof("type") == "script_finished":
                        finished = True
                        print(f"[WS 8501] script_finished 수신! (소요시간: {time.time() - t_start:.2f}s)")

            # 주기적으로 Port 1234 LLM 로그 폴링
            if time.time() - last_log_poll >= 3.0:
                new_logs, log_offset = read_llm_log_delta(log_offset)
                if new_logs:
                    for line in new_logs.strip().split("\n"):
                        if "slot" in line or "timing" in line or "launch" in line:
                            print(f"  [LLM 1234 HTTP] {line}")
                last_log_poll = time.time()

        # 잔여 LLM 로그 수집
        new_logs, log_offset = read_llm_log_delta(log_offset)
        if new_logs:
            for line in new_logs.strip().split("\n"):
                if "slot" in line or "timing" in line or "launch" in line:
                    print(f"  [LLM 1234 HTTP] {line}")

        print(f"\n[WS 8501] 최종 검수 결과:")
        print(f"- 완료 여부: {finished}")
        print(f"- 발생 예외: {query_exceptions} (총 {len(query_exceptions)}건)")
        print(f"- 렌더링된 마크다운 블록: {len(markdown_blocks)}개")
        print(f"- 렌더링된 버튼: {buttons_rendered}")

        has_cards_or_cand = any("삼성전자" in m for m in markdown_blocks)
        print(f"- 후보/카드 내용 포함 여부: {has_cards_or_cand}")

        result_summary = {
            "finished": finished,
            "exceptions": query_exceptions,
            "markdown_count": len(markdown_blocks),
            "buttons": buttons_rendered,
            "has_content": has_cards_or_cand,
            "elapsed_sec": round(time.time() - t_start, 2),
        }
        out_path = ROOT / "docs" / "검수" / "계획8_02CD_실서버HTTP_로그_2026-10-30.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[기록 완료] {out_path}")

    finally:
        ws.close()


if __name__ == "__main__":
    run_real_http_stream()
