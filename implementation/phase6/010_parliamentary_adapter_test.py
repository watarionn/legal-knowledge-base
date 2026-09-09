import importlib.util
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase6_parliamentary_adapter_tested", HERE / "008_parliamentary_adapter.py"
)
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)

DIET_ISSUE = "100105254X00119470520"
IMPERIAL_ISSUE = "009213242X03119470330"


def meeting_payload(*, imperial: bool = False, unknown: bool = False) -> bytes:
    issue_id = IMPERIAL_ISSUE if imperial else DIET_ISSUE
    speech = {
        "speechID": issue_id + "_000",
        "speechOrder": 0,
        "speaker": "Speaker",
        "speakerYomi": "speaker",
        "speakerGroup": "Group",
        "speakerPosition": "Position",
        "speech": "Sample speech text",
        "startPage": 1,
        "speechURL": "https://example.invalid/speech",
    }
    if imperial:
        speech.update({"speakerElection": "Election", "officeTerm": "Term"})
    else:
        speech.update({
            "speakerRole": "Role",
            "createTime": "2020-01-01T00:00:00+09:00",
            "updateTime": "2020-01-02T00:00:00+09:00",
        })
    if unknown:
        speech["futureSpeechField"] = "preserved"
    meeting = {
        "issueID": issue_id,
        "imageKind": "meeting",
        "searchObject": "body",
        "session": 92 if imperial else 1,
        "nameOfHouse": "House",
        "nameOfMeeting": "Meeting",
        "issue": "1",
        "date": "1947-05-20" if not imperial else "1947-03-30",
        "speechRecord": [speech],
        "meetingURL": "https://example.invalid/meeting",
        "pdfURL": "https://example.invalid/pdf",
    }
    if not imperial:
        meeting["closing"] = None
    if unknown:
        meeting["futureMeetingField"] = "preserved"
    return json.dumps({"numberOfRecords": 1, "meetingRecord": [meeting]}).encode("utf-8")


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class ParliamentaryAdapterTest(unittest.TestCase):
    def test_issue_id_validation(self):
        self.assertEqual(adapter.validate_issue_id(DIET_ISSUE), DIET_ISSUE)
        with self.assertRaises(ValueError):
            adapter.validate_issue_id("bad")

    def test_speech_id_validation_and_parent(self):
        speech_id = DIET_ISSUE + "_000"
        self.assertEqual(adapter.validate_speech_id(speech_id, DIET_ISSUE), speech_id)
        with self.assertRaises(ValueError):
            adapter.validate_speech_id(speech_id, IMPERIAL_ISSUE)

    def test_build_meeting_url_is_provider_specific(self):
        diet_url = adapter.build_meeting_url(adapter.PROVIDERS["kokkai-ndl"], DIET_ISSUE)
        imperial_url = adapter.build_meeting_url(
            adapter.PROVIDERS["teikoku-ndl"], IMPERIAL_ISSUE
        )
        self.assertIn("kokkai.ndl.go.jp/api/meeting?", diet_url)
        self.assertIn("teikokugikai-i.ndl.go.jp/api/emp/meeting?", imperial_url)
        self.assertIn("recordPacking=json", diet_url)
        self.assertIn("maximumRecords=1", diet_url)

    def test_parse_diet_projection(self):
        result = adapter.parse_meeting_response(
            adapter.PROVIDERS["kokkai-ndl"], DIET_ISSUE, meeting_payload()
        )
        self.assertEqual(result.issue_id, DIET_ISSUE)
        self.assertEqual(result.session, 1)
        self.assertEqual(len(result.speeches), 1)
        self.assertEqual(result.speeches[0].metadata["speakerRole"], "Role")

    def test_parse_imperial_projection(self):
        result = adapter.parse_meeting_response(
            adapter.PROVIDERS["teikoku-ndl"], IMPERIAL_ISSUE, meeting_payload(imperial=True)
        )
        speech = result.speeches[0]
        self.assertEqual(speech.metadata["speakerElection"], "Election")
        self.assertEqual(speech.metadata["officeTerm"], "Term")

    def test_unknown_fields_are_preserved(self):
        result = adapter.parse_meeting_response(
            adapter.PROVIDERS["kokkai-ndl"], DIET_ISSUE, meeting_payload(unknown=True)
        )
        self.assertEqual(result.metadata["futureMeetingField"], "preserved")
        self.assertEqual(result.speeches[0].metadata["futureSpeechField"], "preserved")

    def test_response_issue_mismatch_is_rejected(self):
        with self.assertRaises(adapter.ProviderResponseError):
            adapter.parse_meeting_response(
                adapter.PROVIDERS["kokkai-ndl"], IMPERIAL_ISSUE, meeting_payload()
            )

    def test_provider_error_is_rejected(self):
        payload = json.dumps({"message": "error", "details": ["bad query"]}).encode()
        with self.assertRaises(adapter.ProviderResponseError):
            adapter.parse_meeting_response(adapter.PROVIDERS["kokkai-ndl"], DIET_ISSUE, payload)

    def test_part_identity_is_deterministic(self):
        speech_id = DIET_ISSUE + "_000"
        first = adapter.external_part_id("a" * 64, speech_id)
        second = adapter.external_part_id("a" * 64, speech_id)
        self.assertEqual(first, second)
        self.assertNotEqual(first, adapter.external_part_id("b" * 64, speech_id))

    def test_text_and_observation_hashes_change_with_text(self):
        first_sha = adapter.text_sha256("alpha")
        second_sha = adapter.text_sha256("beta")
        self.assertNotEqual(first_sha, second_sha)
        first = adapter.part_observation_id("a" * 64, "b" * 64, first_sha)
        second = adapter.part_observation_id("a" * 64, "b" * 64, second_sha)
        self.assertNotEqual(first, second)

    def test_client_serial_throttle(self):
        now = [0.0]
        sleeps = []

        def clock():
            return now[0]

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        def opener(request, timeout):
            return FakeResponse(meeting_payload())

        client = adapter.ParliamentaryApiClient(
            min_interval_seconds=3.0, clock=clock, sleep=sleep, opener=opener
        )
        client.fetch_meeting("kokkai-ndl", DIET_ISSUE)
        client.fetch_meeting("kokkai-ndl", DIET_ISSUE)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 3.0)

    def test_speech_order_must_be_non_negative(self):
        payload = json.loads(meeting_payload())
        payload["meetingRecord"][0]["speechRecord"][0]["speechOrder"] = -1
        with self.assertRaises(adapter.ProviderResponseError):
            adapter.parse_meeting_response(
                adapter.PROVIDERS["kokkai-ndl"],
                DIET_ISSUE,
                json.dumps(payload).encode(),
            )


if __name__ == "__main__":
    unittest.main()
