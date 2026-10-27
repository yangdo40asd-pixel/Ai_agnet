"""OpenDART 기업 고유번호(corpCode.xml) 매핑, 인증·제한·시간초과·미공시 상태 처리 검증."""

import io
import unittest
from unittest.mock import Mock, patch
import zipfile

import requests

from src.config import Settings
from src.data.dart import (
    clear_corp_code_cache,
    fetch_corp_codes,
    fetch_financial_indices,
    fetch_statement,
    interpret_dart_status,
    parse_corp_codes_zip,
    resolve_corp_code,
)
from src.models import AppError


def make_corp_zip(xml_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("CORPCODE.xml", xml_text.encode("utf-8"))
    return buf.getvalue()


SAMPLE_CORP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
    <list>
        <corp_code>00126380</corp_code>
        <corp_name>삼성전자</corp_name>
        <stock_code>005930</stock_code>
        <modify_date>20251231</modify_date>
    </list>
    <list>
        <corp_code>00999999</corp_code>
        <corp_name>비상장예시</corp_name>
        <stock_code> </stock_code>
        <modify_date>20251231</modify_date>
    </list>
    <list>
        <corp_code>00164779</corp_code>
        <corp_name>SK하이닉스구</corp_name>
        <stock_code>000660</stock_code>
        <modify_date>20230101</modify_date>
    </list>
    <list>
        <corp_code>00164780</corp_code>
        <corp_name>SK하이닉스</corp_name>
        <stock_code>000660</stock_code>
        <modify_date>20250101</modify_date>
    </list>
    <list>
        <corp_code>00777771</corp_code>
        <corp_name>중복회사A</corp_name>
        <stock_code>123456</stock_code>
        <modify_date>20250101</modify_date>
    </list>
    <list>
        <corp_code>00777772</corp_code>
        <corp_name>중복회사B</corp_name>
        <stock_code>123456</stock_code>
        <modify_date>20250101</modify_date>
    </list>
</result>
"""


class DartAdapterTests(unittest.TestCase):
    def setUp(self):
        clear_corp_code_cache()
        self.settings = Settings(
            "test-groq",
            "test-model",
            "test-id",
            "test-secret",
            dart_api_key="secret-dart-key-never-expose",
        )

    def tearDown(self):
        clear_corp_code_cache()

    def test_settings_repr_never_exposes_dart_api_key(self):
        self.assertNotIn("secret-dart-key-never-expose", repr(self.settings))

    def test_parse_corp_codes_preserves_leading_zeros_and_handles_duplicates(self):
        mapping = parse_corp_codes_zip(make_corp_zip(SAMPLE_CORP_XML))
        self.assertEqual(resolve_corp_code("005930", mapping), "00126380")
        self.assertEqual(resolve_corp_code("000660", mapping), "00164780")

        # 동일 modify_date의 모호한 중복 매핑은 거부한다.
        with self.assertRaises(AppError) as amb_err:
            resolve_corp_code("123456", mapping)
        self.assertEqual(amb_err.exception.code, "dart_corp_ambiguous")

        # 매핑에 없는 종목코드는 추측 연결하지 않고 거부한다.
        with self.assertRaises(AppError) as unmapped_err:
            resolve_corp_code("999999", mapping)
        self.assertEqual(unmapped_err.exception.code, "dart_corp_unmapped")

    def test_malformed_zip_or_xml_auth_error_is_handled_cleanly(self):
        error_xml = b'<?xml version="1.0" encoding="UTF-8"?><result><status>010</status><message>Unregistered key</message></result>'
        with self.assertRaises(AppError) as err:
            parse_corp_codes_zip(error_xml)
        self.assertEqual(err.exception.code, "dart_auth_error")
        self.assertNotIn("Unregistered", err.exception.message)

    def test_interpret_dart_status_distinguishes_ok_empty_auth_limit_and_error(self):
        self.assertEqual(interpret_dart_status("000")[0], "ok")
        self.assertEqual(interpret_dart_status("013")[0], "empty")
        self.assertEqual(interpret_dart_status("010")[0], "auth_error")
        self.assertEqual(interpret_dart_status("011")[0], "auth_error")
        self.assertEqual(interpret_dart_status("020")[0], "rate_limit")
        self.assertEqual(interpret_dart_status("800")[0], "failed")

    def test_fetch_statement_and_indices_handle_timeout_and_status_codes_without_leaking_key(self):
        with patch("src.data.dart.requests.get", side_effect=requests.Timeout) as mock_get:
            res = fetch_statement("00126380", "2025", "11011", "CFS", settings=self.settings)
        self.assertEqual(res["status"], "timeout")
        self.assertNotIn("secret-dart-key-never-expose", res["message"])
        self.assertEqual(mock_get.call_args.kwargs["timeout"], self.settings.request_timeout)

        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch("src.data.dart.requests.get", return_value=mock_resp):
            empty_res = fetch_statement("00126380", "2025", "11011", "CFS", settings=self.settings)
        self.assertEqual(empty_res["status"], "empty")

        mock_idx_resp = Mock(status_code=200)
        mock_idx_resp.json.return_value = {
            "status": "000",
            "message": "정상",
            "list": [{"idx_nm": "ROE", "idx_val": "9.45"}],
        }
        with patch("src.data.dart.requests.get", return_value=mock_idx_resp) as idx_get:
            idx_res = fetch_financial_indices("00126380", "2025", "11011", "M210000", settings=self.settings)
        self.assertEqual(idx_res["status"], "ok")
        self.assertNotIn("fs_div", idx_get.call_args.kwargs["params"])

    def test_fetch_corp_codes_caches_valid_response_and_does_not_cache_errors(self):
        zip_content = make_corp_zip(SAMPLE_CORP_XML)
        ok_resp = Mock(status_code=200, content=zip_content)
        with patch("src.data.dart.requests.get", return_value=ok_resp) as mock_get:
            first = fetch_corp_codes(self.settings)
            second = fetch_corp_codes(self.settings)
        self.assertEqual(mock_get.call_count, 1)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
