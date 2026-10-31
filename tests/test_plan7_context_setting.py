"""로컬 문맥 크기 설정(LOCAL_LLM_CONTEXT)을 네트워크 없이 확인한다."""
import unittest
from unittest.mock import patch

from src.config import load_settings
from src.models import AppError
from src.agents.providers.local import estimate_context_budget

BASE = {"AI_PROVIDER": "local", "LOCAL_LLM_MODEL": "fixture", "GROQ_MODEL": "", "GROQ_API_KEY": ""}


def _load(**extra):
    with patch.dict("os.environ", {**BASE, **extra}, clear=True), patch("src.config.load_dotenv"):
        return load_settings()


class LocalContextSettingTest(unittest.TestCase):
    def test_default_keeps_previous_4096(self):
        self.assertEqual(_load().local_context_window, 4096)

    def test_env_value_is_used(self):
        self.assertEqual(_load(LOCAL_LLM_CONTEXT="8192").local_context_window, 8192)

    def test_invalid_value_rejected_for_local(self):
        for value in ("abc", "100", "999999", ""):
            with self.subTest(value=value), self.assertRaises(AppError):
                _load(LOCAL_LLM_CONTEXT=value)

    def test_budget_uses_given_window(self):
        messages = [("user", "가" * 7000)]
        small = estimate_context_budget(messages, 1000, 4096)
        large = estimate_context_budget(messages, 1000, 8192)
        self.assertFalse(small["fits_context"])
        self.assertTrue(large["fits_context"])


if __name__ == "__main__":
    unittest.main()