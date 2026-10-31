"""기업 사업 자료의 소유권·절 경계·호출 제한·부분 성공을 검수한다."""
from dataclasses import replace
import io
import json
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from src.config import Settings
from src.data import business_sources as sources
from src.data.business_sections import extract_business_sections, MAX_XML_BYTES
from src.models import AppError, StockCandidate, now_kst

STOCK = StockCandidate("가상제조", "000001", "KOSPI", "000001.KS")
SECOND = StockCandidate("가상장비", "000002", "KOSDAQ", "000002.KQ")
SETTINGS = Settings("fixture", "fixture", "", "", dart_api_key="secret-not-for-output")
RECEIPT = "20261029000001"


def archive(xml):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("report.xml", xml.encode("utf-8"))
    return stream.getvalue()


def report_xml(name="가상제조"):
    return f'''<DOCUMENT><COMPANY-NAME>{name}</COMPANY-NAME><SECTION-1>
    <TITLE>II. 사업의 내용</TITLE>
    <SECTION-2><TITLE>1. 사업의 개요</TITLE><P>메모리와 장비를 생산합니다.</P>
    <SECTION-3><TITLE>다른 제품</TITLE><P>다른 제품의 속성입니다.</P></SECTION-3></SECTION-2>
    <SECTION-2><TITLE>2. 주요 제품 및 서비스</TITLE><P>검사용 소켓은 반도체 검사에 사용합니다.</P></SECTION-2>
    <SECTION-2><TITLE>3. 재무에 관한 사항</TITLE><P>이 문장은 사업 절 근거가 아닙니다.</P></SECTION-2>
    </SECTION-1></DOCUMENT>'''


def extract(data):
    return extract_business_sections(data, STOCK, document_id=RECEIPT,
        document_title="반기보고서 (2026.06)", published_at="20260814", retrieved_at=now_kst())


class BusinessSectionsTests(unittest.TestCase):
    def test_sections_keep_separate_provenance_and_dates(self):
        values = extract(archive(report_xml()))
        self.assertEqual(len(values), 2)
        self.assertNotIn("검사용", values[0].text)
        self.assertNotIn("다른 제품의 속성", values[0].text)
        self.assertNotIn("재무에 관한", " ".join(v.text for v in values))
        self.assertEqual(values[1].reporting_period, "2026.06")
        self.assertEqual(values[1].published_at, "20260814")
        self.assertEqual(len(values[1].content_hash), 64)
        self.assertEqual(values[1].stock_code, STOCK.code)
        self.assertIn(RECEIPT, values[1].source_url)

    def test_unrelated_report_does_not_fall_back_to_whole_document(self):
        self.assertEqual(extract(archive('<DOCUMENT><P>반도체 자료입니다.</P></DOCUMENT>')), ())

    def test_wrong_cover_company_is_rejected(self):
        with self.assertRaises(AppError) as caught:
            extract(archive(report_xml("다른회사")))
        self.assertEqual(caught.exception.code, "business_document_company")

    def test_verified_corp_identifier_handles_legal_name_without_company_alias_exception(self):
        xml = report_xml('가상제조주식회사').replace('<COMPANY-NAME>', '<COMPANY-NAME AREGCIK="00100001">')
        kwargs = dict(document_id=RECEIPT, document_title='사업보고서 (2025.12)',
                      published_at='20260330', retrieved_at=now_kst())
        values = extract_business_sections(archive(xml), STOCK, corp_code='00100001', **kwargs)
        self.assertEqual(values[0].corp_code, '00100001')
        with self.assertRaises(AppError):
            extract_business_sections(archive(xml), STOCK, corp_code='99999999', **kwargs)

    def test_literal_less_than_in_table_preserves_comparison_without_html_recovery(self):
        xml = report_xml().replace('검사용 소켓은 반도체 검사에 사용합니다.', '< 5% hydrogen, R&D')
        self.assertIn('< 5% hydrogen, R&D', extract(archive(xml))[1].text)
        with self.assertRaises(AppError):
            extract(archive(report_xml().replace('</SECTION-1>', '</BROKEN>')))

    def test_korean_literal_label_is_preserved_but_tags_are_not_repaired(self):
        xml = '<?xml version="1.0" encoding="utf-8"?>' + report_xml().replace(
            '메모리와 장비를 생산합니다.', '<보수지급금액 5억원 이상인 이사ㆍ감사의 개인별 보수현황> 메모리와 장비를 생산합니다.')
        self.assertIn('<보수지급금액 5억원 이상인 이사ㆍ감사의 개인별 보수현황>', extract(archive(xml))[0].text)

    def test_unrelated_chapter_xml_error_does_not_replace_or_corrupt_business_chapter(self):
        xml = report_xml().replace('</DOCUMENT>', '<SECTION-1><TITLE>이사회</TITLE><P><테마> 안내입니다.</P></SECTION-1></DOCUMENT>')
        values = extract(archive(xml))
        self.assertEqual(len(values), 2)
        self.assertNotIn('안내입니다', ' '.join(v.text for v in values))
        broken_business = xml.replace('메모리와 장비를 생산합니다.', '<테마> 메모리와 장비를 생산합니다.')
        with self.assertRaises(AppError):
            extract(archive(broken_business))

    def test_ascii_and_korean_literal_headings_are_preserved_without_repairing_invalid_p_tag(self):
        xml = '<?xml version="1.0" encoding="utf-8"?>' + report_xml().replace(
            '메모리와 장비를 생산합니다.', '< TV 시장경쟁환경 현황 > 메모리와 장비를 생산합니다.')
        self.assertIn('< TV 시장경쟁환경 현황 >', extract(archive(xml))[0].text)
        with self.assertRaises(AppError):
            extract(archive(xml.replace('메모리와 장비를 생산합니다.', '<P BROKEN>메모리와 장비를 생산합니다.')))

    def test_invalid_archive_entities_and_expanded_size_are_rejected(self):
        bad = [b"not a zip", archive('<!DOCTYPE DOCUMENT [<!ENTITY e "x">]><DOCUMENT>&e;</DOCUMENT>'),
               archive("<DOCUMENT>" + "x" * MAX_XML_BYTES + "</DOCUMENT>")]
        for data in bad:
            with self.subTest(size=len(data)), self.assertRaises(AppError):
                extract(data)


class BusinessCollectionTests(unittest.TestCase):
    def setUp(self):
        sources._cache.clear()

    def test_list_rejects_foreign_company_nonregular_and_bad_receipt(self):
        row = dict(corp_code="00100001", rcept_no=RECEIPT, rcept_dt="20260814", report_nm="반기보고서 (2026.06)")
        values, status = sources.select_reports({"status": "000", "list": [row,
            dict(row, corp_code="99999999"), dict(row, report_nm="단일판매계약"),
            dict(row, rcept_no="bad")]}, "00100001")
        self.assertEqual(values, (row,))
        self.assertEqual(status, "ok")

    def test_dart_status_not_silently_relabelled_empty(self):
        for code, expected in (("010", "auth_error"), ("020", "rate_limit"), ("013", "empty")):
            self.assertEqual(sources.select_reports({"status": code}, "00100001"), ((), expected))

    def test_source_success_is_cached_but_partial_failure_is_not(self):
        mapping = {"000001": {"corp_code": "00100001"}, "000002": {"corp_code": "00100002"}}
        values = extract(archive(report_xml()))
        with patch.object(sources, "fetch_corp_codes", return_value=mapping), patch.object(
                sources, "_collect_one", side_effect=[(values, "ok"), AppError("business_source_http", "조회 실패"), ((), "empty")]) as fetch:
            first = sources.collect_business_sources((STOCK, SECOND), SETTINGS)
            second = sources.collect_business_sources((STOCK, SECOND), SETTINGS)
        self.assertEqual(first.sources, values)
        self.assertEqual(dict(first.statuses)[SECOND.code], "business_source_http")
        self.assertEqual(second.sources, values)
        self.assertEqual(dict(second.statuses)[SECOND.code], "empty")
        self.assertEqual(fetch.call_count, 3)

    def test_no_key_or_nonselectable_stock_does_not_call_api(self):
        with patch.object(sources, "fetch_corp_codes") as fetch:
            values = sources.collect_business_sources((STOCK,), replace(SETTINGS, dart_api_key=""))
            self.assertEqual(values.statuses, ((STOCK.code, "not_configured"),))
            self.assertEqual(sources.collect_business_sources((StockCandidate("가상회사"),), SETTINGS).sources, ())
        fetch.assert_not_called()

    def test_provider_limit_stops_remaining_company_http_requests(self):
        with patch.object(sources, 'fetch_corp_codes', return_value={'000001': {'corp_code': '00100001'}}), patch.object(
                sources, '_collect_one', return_value=((), 'rate_limit')) as fetch:
            values = sources.collect_business_sources((STOCK, SECOND), SETTINGS)
        self.assertEqual(values.statuses, ((STOCK.code, 'rate_limit'), (SECOND.code, 'rate_limit')))
        self.assertEqual(fetch.call_count, 1)

    def test_more_than_batch_limit_is_explicitly_rejected(self):
        stocks = tuple(replace(STOCK, code=f"{i:06d}") for i in range(7))
        with self.assertRaises(AppError):
            sources.collect_business_sources(stocks, SETTINGS)

    def test_streaming_size_and_redirect_rejection_hide_secret(self):
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [b"123", b"456"]
        with patch.object(sources.requests, "get") as fetch:
            fetch.return_value.__enter__.return_value = response
            with self.assertRaises(AppError):
                sources._fetch("/list.json", {"crtfc_key": SETTINGS.dart_api_key}, SETTINGS, limit=5)
            self.assertFalse(fetch.call_args.kwargs["allow_redirects"])
            response.status_code = 302
            with self.assertRaises(AppError) as caught:
                sources._fetch("/list.json", {}, SETTINGS, limit=100)
            self.assertNotIn(SETTINGS.dart_api_key, str(caught.exception))

    def test_list_window_includes_reports_outside_90_days(self):
        payload = {"status": "000", "list": [dict(corp_code="00100001", rcept_no=RECEIPT,
                rcept_dt="20260814", report_nm="반기보고서 (2026.06)")]}
        with patch.object(sources, "_fetch", side_effect=[json.dumps(payload).encode(), archive(report_xml())]) as fetch:
            values, status = sources._collect_one(STOCK, "00100001", SETTINGS)
        self.assertEqual(status, "ok")
        self.assertEqual(len(values), 2)
        params = fetch.call_args_list[0].args[1]
        self.assertEqual(params["pblntf_ty"], "A")
        self.assertEqual(params["last_reprt_at"], "N")
        self.assertNotIn(SETTINGS.dart_api_key, repr(values))

    def test_document_rate_limit_xml_is_not_retried_as_another_report(self):
        row = dict(corp_code='00100001', rcept_no=RECEIPT, rcept_dt='20260814', report_nm='반기보고서 (2026.06)')
        payload = {'status': '000', 'list': [row, dict(row, rcept_no='20260515000001', rcept_dt='20260515')]}
        with patch.object(sources, '_fetch', side_effect=[json.dumps(payload).encode(),
                          b'<result><status>020</status></result>']) as fetch:
            values, status = sources._collect_one(STOCK, '00100001', SETTINGS)
        self.assertEqual((values, status), ((), 'rate_limit'))
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
