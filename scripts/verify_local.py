"""외부 네트워크를 차단하고 unittest/AppTest 검사를 실행한다. 서버를 실행하지 않는다."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

if __name__ == "__main__":
    with ExitStack() as stack:
        for target in ("socket.socket.connect", "requests.sessions.Session.request", "curl_cffi.requests.Session.request"):
            stack.enter_context(patch(target, side_effect=AssertionError("로컬 검사 중 실제 네트워크 요청 금지")))
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=sys.argv[1] if len(sys.argv) > 1 else "test*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())
