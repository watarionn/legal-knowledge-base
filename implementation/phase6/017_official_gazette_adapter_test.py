import importlib.util
import pathlib
import sys
import unittest
from datetime import date
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase6_gazette_adapter_test_target", HERE / "015_official_gazette_adapter.py"
)
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)

ISSUED = date(2026, 8, 10)
PDF_URL = (
    "https://www.kanpo.go.jp/20260810/20260810h01765/pdf/"
    "20260810h01765full00010032.pdf"
)


class FakeResponse:
    def __init__(self, payload: bytes, url: str = PDF_URL, content_length: int | None = None):
        self.payload = payload
        self.url = url
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


class OfficialGazetteAdapterTest(unittest.TestCase):
    def issue(self, kind: str = "regular", number: int = 1765):
        return adapter.GazetteIssueSpec(ISSUED, kind, number)

    def asset(self):
        return adapter.GazettePdfAssetSpec(self.issue(), PDF_URL, 1, 32)

    def test_derived_provider_document_id(self):
        self.assertEqual(
            self.issue().provider_document_id,
            "derived:2026-08-10:regular:1765",
        )

    def test_all_publication_kinds_are_supported(self):
        for kind in adapter.ALLOWED_KINDS:
            self.assertIn(f":{kind}:", self.issue(kind=kind).provider_document_id)
    def test_invalid_issue_number_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.derived_provider_document_id(ISSUED, "regular", 0)

    def test_non_kanpo_host_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.validate_pdf_url(
                PDF_URL.replace("www.kanpo.go.jp", "example.com"), ISSUED
            )

    def test_url_date_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.validate_pdf_url(PDF_URL.replace("20260810", "20260811"), ISSUED)

    def test_url_query_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.validate_pdf_url(PDF_URL + "?download=1", ISSUED)

    def test_asset_identity_changes_with_page_range(self):
        a = self.asset()
        b = adapter.GazettePdfAssetSpec(self.issue(), PDF_URL, 1, 31)
        self.assertNotEqual(a.id, b.id)

    def test_invalid_page_range_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.GazettePdfAssetSpec(self.issue(), PDF_URL, 10, 9)
    def test_signature_structure_is_observation_not_validation(self):
        payload = (
            b"%PDF-1.7 /Type /Sig /ByteRange /ByteRange "
            b"/DocTimeStamp /ETSI.CAdES.detached"
        )
        obs = adapter.inspect_pdf_signature_structure(payload)
        self.assertEqual(obs.signature_field_count, 1)
        self.assertEqual(obs.byte_range_count, 2)
        self.assertEqual(obs.document_timestamp_count, 1)
        self.assertEqual(obs.cades_detached_count, 1)
        self.assertEqual(obs.cryptographic_verification_status, "not-checked")

    def test_non_pdf_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.inspect_pdf_signature_structure(b"not a pdf")

    @mock.patch.object(adapter.urllib.request, "urlopen")
    def test_fetch_explicit_pdf_success(self, urlopen):
        payload = b"%PDF-1.7 /Type /Sig /ByteRange /DocTimeStamp"
        urlopen.return_value = FakeResponse(payload, content_length=len(payload))
        fetched = adapter.fetch_explicit_pdf(self.asset(), max_bytes=1024)
        self.assertEqual(fetched.raw_payload, payload)
        self.assertEqual(fetched.byte_size, len(payload))
        self.assertEqual(len(fetched.payload_sha256), 64)
    @mock.patch.object(adapter.urllib.request, "urlopen")
    def test_fetch_rejects_redirect(self, urlopen):
        payload = b"%PDF-1.7"
        redirected = PDF_URL.replace("h01765", "h99999")
        urlopen.return_value = FakeResponse(payload, url=redirected)
        with self.assertRaises(ValueError):
            adapter.fetch_explicit_pdf(self.asset(), max_bytes=1024)

    @mock.patch.object(adapter.urllib.request, "urlopen")
    def test_fetch_rejects_content_length_over_limit(self, urlopen):
        payload = b"%PDF-1.7"
        urlopen.return_value = FakeResponse(payload, content_length=2048)
        with self.assertRaises(ValueError):
            adapter.fetch_explicit_pdf(self.asset(), max_bytes=1024)


if __name__ == "__main__":
    unittest.main()
