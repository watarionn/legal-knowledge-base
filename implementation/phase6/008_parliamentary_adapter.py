from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Sequence

ISSUE_ID_RE = re.compile(r"^[0-9A-Z]{21}$")
SPEECH_ID_RE = re.compile(r"^[0-9A-Z]{21}_[0-9]{3,4}$")
PART_VERSION = "phase6-parliamentary-part-1.0"
PART_OBSERVATION_VERSION = "phase6-parliamentary-part-observation-1.0"
US = "\x1f"


class ParliamentaryAdapterError(RuntimeError):
    pass


class ProviderResponseError(ParliamentaryAdapterError):
    pass


@dataclass(frozen=True)
class ParliamentaryProvider:
    provider_code: str
    source_family: str
    base_url: str
    meeting_endpoint: str
    provider_specific_speech_fields: tuple[str, ...]
    meeting_specific_fields: tuple[str, ...] = ()


PROVIDERS: dict[str, ParliamentaryProvider] = {
    "kokkai-ndl": ParliamentaryProvider(
        provider_code="kokkai-ndl",
        source_family="diet-minutes",
        base_url="https://kokkai.ndl.go.jp/",
        meeting_endpoint="https://kokkai.ndl.go.jp/api/meeting",
        provider_specific_speech_fields=("speakerRole", "createTime", "updateTime"),
        meeting_specific_fields=("closing",),
    ),
    "teikoku-ndl": ParliamentaryProvider(
        provider_code="teikoku-ndl",
        source_family="imperial-diet-minutes",
        base_url="https://teikokugikai-i.ndl.go.jp/",
        meeting_endpoint="https://teikokugikai-i.ndl.go.jp/api/emp/meeting",
        provider_specific_speech_fields=("speakerElection", "officeTerm"),
    ),
}

COMMON_SPEECH_FIELDS = (
    "speechID",
    "speechOrder",
    "speaker",
    "speakerYomi",
    "speakerGroup",
    "speakerPosition",
    "speech",
    "startPage",
    "speechURL",
)
COMMON_MEETING_FIELDS = (
    "issueID",
    "imageKind",
    "searchObject",
    "session",
    "nameOfHouse",
    "nameOfMeeting",
    "issue",
    "date",
    "meetingURL",
    "pdfURL",
)


@dataclass(frozen=True)
class SpeechProjection:
    speech_id: str
    speech_order: int
    speaker: str | None
    speech_text: str | None
    speech_url: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class MeetingProjection:
    provider_code: str
    issue_id: str
    session: int | None
    house: str | None
    meeting_name: str | None
    issue: str | None
    held_on: date | None
    meeting_url: str | None
    pdf_url: str | None
    metadata: Mapping[str, Any]
    speeches: tuple[SpeechProjection, ...]


@dataclass(frozen=True)
class FetchedMeeting:
    provider: ParliamentaryProvider
    request_url: str
    raw_payload: bytes
    payload_sha256: str
    meeting: MeetingProjection
    observed_at: datetime


def _identity(version: str, *parts: str) -> str:
    if any(not isinstance(part, str) or not part for part in parts):
        raise ValueError("identity parts must be non-empty strings")
    return hashlib.sha256(US.join((version, *parts)).encode("utf-8")).hexdigest()


def validate_issue_id(issue_id: str) -> str:
    if not ISSUE_ID_RE.fullmatch(issue_id):
        raise ValueError("issueID must be 21 uppercase alphanumeric characters")
    return issue_id


def validate_speech_id(speech_id: str, issue_id: str | None = None) -> str:
    if not SPEECH_ID_RE.fullmatch(speech_id):
        raise ValueError("speechID must be issueID plus a 3-4 digit speech number")
    if issue_id is not None and not speech_id.startswith(validate_issue_id(issue_id) + "_"):
        raise ValueError("speechID does not belong to issueID")
    return speech_id


def external_part_id(external_document_id: str, speech_id: str) -> str:
    validate_speech_id(speech_id)
    return _identity(PART_VERSION, external_document_id, speech_id)


def text_sha256(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def part_observation_id(
    external_part_id_value: str,
    snapshot_id: str,
    speech_text_sha256: str | None,
) -> str:
    return _identity(
        PART_OBSERVATION_VERSION,
        external_part_id_value,
        snapshot_id,
        speech_text_sha256 or "none",
    )


def build_meeting_url(provider: ParliamentaryProvider, issue_id: str) -> str:
    query = urllib.parse.urlencode(
        {"issueID": validate_issue_id(issue_id), "maximumRecords": 1, "recordPacking": "json"}
    )
    return f"{provider.meeting_endpoint}?{query}"


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _preserve_metadata(record: Mapping[str, Any], known_fields: Sequence[str]) -> dict[str, Any]:
    known = set(known_fields)
    return {key: value for key, value in record.items() if key not in known}


def parse_meeting_response(
    provider: ParliamentaryProvider,
    requested_issue_id: str,
    raw_payload: bytes,
) -> MeetingProjection:
    requested_issue_id = validate_issue_id(requested_issue_id)
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderResponseError("provider response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderResponseError("provider response root must be an object")
    if "message" in payload and "meetingRecord" not in payload:
        raise ProviderResponseError(f"provider error: {payload.get('message')}")
    records = payload.get("meetingRecord")
    if not isinstance(records, list) or len(records) != 1:
        raise ProviderResponseError("meeting endpoint must return exactly one meetingRecord")
    record = records[0]
    if not isinstance(record, dict):
        raise ProviderResponseError("meetingRecord must be an object")
    issue_id = validate_issue_id(str(record.get("issueID", "")))
    if issue_id != requested_issue_id:
        raise ProviderResponseError("returned issueID does not match requested issueID")

    speeches_raw = record.get("speechRecord") or []
    if not isinstance(speeches_raw, list):
        raise ProviderResponseError("speechRecord must be an array")
    speeches: list[SpeechProjection] = []
    for speech_record in speeches_raw:
        if not isinstance(speech_record, dict):
            raise ProviderResponseError("speechRecord item must be an object")
        speech_id = validate_speech_id(str(speech_record.get("speechID", "")), issue_id)
        try:
            speech_order = int(speech_record.get("speechOrder"))
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError("speechOrder must be an integer") from exc
        if speech_order < 0:
            raise ProviderResponseError("speechOrder must be non-negative")
        speech_text = speech_record.get("speech")
        if speech_text is not None and not isinstance(speech_text, str):
            raise ProviderResponseError("speech must be text or null")
        metadata = dict(speech_record)
        metadata.pop("speech", None)
        speeches.append(
            SpeechProjection(
                speech_id=speech_id,
                speech_order=speech_order,
                speaker=speech_record.get("speaker"),
                speech_text=speech_text,
                speech_url=speech_record.get("speechURL"),
                metadata=metadata,
            )
        )

    meeting_metadata = dict(record)
    meeting_metadata.pop("speechRecord", None)
    return MeetingProjection(
        provider_code=provider.provider_code,
        issue_id=issue_id,
        session=_optional_int(record.get("session")),
        house=record.get("nameOfHouse"),
        meeting_name=record.get("nameOfMeeting"),
        issue=None if record.get("issue") is None else str(record.get("issue")),
        held_on=_optional_date(record.get("date")),
        meeting_url=record.get("meetingURL"),
        pdf_url=record.get("pdfURL"),
        metadata=meeting_metadata,
        speeches=tuple(speeches),
    )


class ParliamentaryApiClient:
    def __init__(
        self,
        *,
        min_interval_seconds: float = 3.0,
        user_agent: str = "legal-knowledge-base/phase6.2",
        timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        self.min_interval_seconds = min_interval_seconds
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self.sleep = sleep
        self.opener = opener
        self._last_completed_at: float | None = None

    def _throttle(self) -> None:
        if self._last_completed_at is None:
            return
        remaining = self.min_interval_seconds - (self.clock() - self._last_completed_at)
        if remaining > 0:
            self.sleep(remaining)

    def fetch_meeting(self, provider_code: str, issue_id: str) -> FetchedMeeting:
        try:
            provider = PROVIDERS[provider_code]
        except KeyError as exc:
            raise ValueError(f"unsupported provider: {provider_code}") from exc
        self._throttle()
        request_url = build_meeting_url(provider, issue_id)
        request = urllib.request.Request(request_url, headers={"User-Agent": self.user_agent})
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                raw_payload = response.read()
        finally:
            self._last_completed_at = self.clock()
        meeting = parse_meeting_response(provider, issue_id, raw_payload)
        return FetchedMeeting(
            provider=provider,
            request_url=request_url,
            raw_payload=raw_payload,
            payload_sha256=hashlib.sha256(raw_payload).hexdigest(),
            meeting=meeting,
            observed_at=datetime.now(timezone.utc),
        )
