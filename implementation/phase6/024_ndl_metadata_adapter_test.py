from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("phase6_ndl_metadata_adapter_tested", HERE / "022_ndl_metadata_adapter.py")
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)

IDENTIFIER = "oai:ndlsearch.ndl.go.jp:R100000002-I123456789"
TOKEN = "R100000002-I123456789"

SRU_XML = f'''<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
  <numberOfRecords>1</numberOfRecords>
  <records><record>
    <recordSchema>dcndl_v3</recordSchema><recordPacking>string</recordPacking>
    <recordData>&lt;rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"&gt;&lt;dcndl:BibAdminResource rdf:about="https://ndlsearch.ndl.go.jp/books/{TOKEN}" /&gt;&lt;/rdf:RDF&gt;</recordData>
    <recordPosition>1</recordPosition>
  </record></records>
</searchRetrieveResponse>'''.encode()
OAI_XML = f'''<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <GetRecord><record><header>
  <identifier>{IDENTIFIER}</identifier><datestamp>2026-09-10T09:00:00Z</datestamp>
  <setSpec>iss-ndl-opac</setSpec>
 </header><metadata>
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">
   <rdf:Description rdf:about="https://ndlsearch.ndl.go.jp/books/{TOKEN}#material">
    <dc:title>日本国憲法資料</dc:title><dc:creator>国立国会図書館</dc:creator>
    <dcterms:issued>2026-09-01</dcterms:issued><dc:subject>憲法</dc:subject>
    <dcterms:references rdf:resource="https://example.invalid/reference" />
   </rdf:Description>
  </rdf:RDF>
 </metadata></record></GetRecord>
</OAI-PMH>'''.encode()

DELETED_XML = f'''<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <GetRecord><record><header status="deleted">
  <identifier>{IDENTIFIER}</identifier><datestamp>2026-09-11T09:00:00Z</datestamp>
  <setSpec>iss-ndl-opac</setSpec>
 </header></record></GetRecord>
</OAI-PMH>'''.encode()


class FakeResponse:
    def __init__(self, payload: bytes): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit: int = -1): return self.payload if limit < 0 else self.payload[:limit]


class NdlMetadataAdapterTest(unittest.TestCase):
    def test_identifier_roundtrip(self):
        self.assertEqual(adapter.split_oai_identifier(IDENTIFIER), ("R100000002", "123456789"))
        self.assertEqual(adapter.token_to_oai_identifier(TOKEN), IDENTIFIER)
        self.assertEqual(adapter.canonical_bib_url(IDENTIFIER), f"https://ndlsearch.ndl.go.jp/books/{TOKEN}")

    def test_identifier_rejects_other_domain(self):
        with self.assertRaises(adapter.NdlMetadataError):
            adapter.split_oai_identifier("oai:example.org:R100000002-I1")

    def test_sru_url_is_capped_and_dcndl_v3(self):
        url = adapter.build_sru_url(f'itemno="{TOKEN}"', maximum_records=1)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["recordSchema"], ["dcndl_v3"])
        self.assertEqual(params["maximumRecords"], ["1"])
        with self.assertRaises(adapter.NdlMetadataError):
            adapter.build_sru_url("title=x", maximum_records=11)

    def test_parse_sru_discovers_oai_identifier(self):
        total, records = adapter.parse_sru_response(SRU_XML)
        self.assertEqual(total, 1)
        self.assertEqual(records[0].oai_identifier, IDENTIFIER)
        self.assertEqual(records[0].repository_number, "R100000002")

    def test_parse_oai_projection(self):
        record = adapter.parse_oai_get_record(OAI_XML, expected_identifier=IDENTIFIER)
        self.assertFalse(record.deleted)
        self.assertEqual(record.title, "日本国憲法資料")
        self.assertEqual(record.issued_on.isoformat(), "2026-09-01")
        self.assertEqual(record.set_specs, ("iss-ndl-opac",))
        self.assertEqual(record.projection["subject"], ["憲法"])
        self.assertIsNotNone(record.metadata_xml_sha256)

    def test_deleted_record_becomes_tombstone(self):
        record = adapter.parse_oai_get_record(DELETED_XML, expected_identifier=IDENTIFIER)
        self.assertTrue(record.deleted)
        self.assertIsNone(record.metadata_xml_sha256)
        self.assertTrue(record.projection["oai_deleted"])

    def test_response_identifier_mismatch_is_blocked(self):
        with self.assertRaises(adapter.NdlMetadataError):
            adapter.parse_oai_get_record(OAI_XML, expected_identifier="oai:ndlsearch.ndl.go.jp:R100000002-I999")

    def test_oai_error_is_blocked(self):
        raw = b'''<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="idDoesNotExist">missing</error></OAI-PMH>'''
        with self.assertRaises(adapter.NdlMetadataError):
            adapter.parse_oai_get_record(raw)

    def test_unsupported_metadata_prefix_is_blocked(self):
        with self.assertRaises(adapter.NdlMetadataError):
            adapter.build_oai_get_record_url(IDENTIFIER, metadata_prefix="mods")

    def test_observation_id_is_deterministic(self):
        record = adapter.parse_oai_get_record(OAI_XML)
        a = adapter.metadata_observation_id(record, "a" * 64)
        b = adapter.metadata_observation_id(record, "a" * 64)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_client_serial_throttle(self):
        now = [0.0]
        sleeps = []
        payloads = [SRU_XML, OAI_XML]
        def monotonic(): return now[0]
        def sleeper(seconds):
            sleeps.append(seconds)
            now[0] += seconds
        def opener(request, timeout=30):
            return FakeResponse(payloads.pop(0))
        client = adapter.NdlSearchClient(
            min_interval_seconds=3.0,
            opener=opener,
            monotonic=monotonic,
            sleeper=sleeper,
        )
        total, records, _, _ = client.discover_sru(f'itemno="{TOKEN}"')
        self.assertEqual(total, 1)
        client.get_oai_record(records[0].oai_identifier)
        self.assertEqual(sleeps, [3.0])

    def test_response_size_limit_is_enforced(self):
        def opener(request, timeout=30): return FakeResponse(b"x" * 11)
        client = adapter.NdlSearchClient(max_response_bytes=10, opener=opener)
        with self.assertRaises(adapter.NdlMetadataError):
            client.discover_sru("title=x")


if __name__ == "__main__":
    unittest.main()
