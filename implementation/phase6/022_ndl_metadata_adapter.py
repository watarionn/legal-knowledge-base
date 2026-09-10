from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable
from xml.etree import ElementTree as ET

PROVIDER_CODE = "ndl-search"
BASE_URL = "https://ndlsearch.ndl.go.jp/"
SRU_URL = "https://ndlsearch.ndl.go.jp/api/sru"
OAI_URL = "https://ndlsearch.ndl.go.jp/api/oaipmh"
DEFAULT_METADATA_PREFIX = "dcndl_v3"
SUPPORTED_METADATA_PREFIXES = {"oai_dc", "dcndl", "dcndl_v3"}
OAI_PREFIX = "oai:ndlsearch.ndl.go.jp:"
TOKEN_RE = re.compile(r"^(R[0-9]{9})-I([^\s]+)$")
RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"


class NdlMetadataError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def split_oai_identifier(identifier: str) -> tuple[str, str]:
    if not identifier.startswith(OAI_PREFIX):
        raise NdlMetadataError("unsupported OAI identifier domain")
    token = identifier[len(OAI_PREFIX):]
    match = TOKEN_RE.fullmatch(token)
    if match is None:
        raise NdlMetadataError("invalid NDL Search OAI identifier")
    return match.group(1), match.group(2)


def token_to_oai_identifier(token: str) -> str:
    match = TOKEN_RE.fullmatch(token)
    if match is None:
        raise NdlMetadataError("invalid NDL Search repository/item token")
    return OAI_PREFIX + token


def canonical_bib_url(identifier: str) -> str:
    repository_number, item_number = split_oai_identifier(identifier)
    return f"https://ndlsearch.ndl.go.jp/books/{repository_number}-I{item_number}"


def sru_about_to_oai_identifier(about_url: str) -> str:
    parsed = urllib.parse.urlsplit(about_url)
    if parsed.scheme != "https" or parsed.hostname != "ndlsearch.ndl.go.jp":
        raise NdlMetadataError("SRU record points outside NDL Search")
    if parsed.query or parsed.fragment:
        raise NdlMetadataError("unexpected SRU bibliographic URL suffix")
    prefix = "/books/"
    if not parsed.path.startswith(prefix):
        raise NdlMetadataError("unexpected SRU bibliographic URL path")
    return token_to_oai_identifier(parsed.path[len(prefix):])


@dataclass(frozen=True)
class SruDiscovery:
    record_position: int
    oai_identifier: str
    repository_number: str
    item_number: str
    bibliographic_url: str
    record_xml_sha256: str


@dataclass(frozen=True)
class OaiMetadataRecord:
    oai_identifier: str
    repository_number: str
    item_number: str
    oai_datestamp: str
    set_specs: tuple[str, ...]
    metadata_prefix: str
    deleted: bool
    metadata_xml_sha256: str | None
    projection: dict[str, Any]
    issued_on: date | None
    title: str | None


@dataclass(frozen=True)
class FetchedOaiRecord:
    record: OaiMetadataRecord
    request_url: str
    raw_payload: bytes
    payload_sha256: str
    observed_at: datetime


def build_sru_url(query: str, *, maximum_records: int = 1, start_record: int = 1) -> str:
    query = query.strip()
    if not query or len(query) > 512:
        raise NdlMetadataError("SRU query must contain 1..512 characters")
    if not 1 <= maximum_records <= 10:
        raise NdlMetadataError("Phase 6.4 caps SRU discovery at 10 records")
    if not 1 <= start_record <= 500:
        raise NdlMetadataError("SRU startRecord is outside Phase 6.4 safety range")
    params = {
        "operation": "searchRetrieve",
        "version": "1.2",
        "query": query,
        "startRecord": str(start_record),
        "maximumRecords": str(maximum_records),
        "recordPacking": "string",
        "recordSchema": "dcndl_v3",
    }
    return SRU_URL + "?" + urllib.parse.urlencode(params)


def build_oai_get_record_url(identifier: str, *, metadata_prefix: str = DEFAULT_METADATA_PREFIX) -> str:
    split_oai_identifier(identifier)
    if metadata_prefix not in SUPPORTED_METADATA_PREFIXES:
        raise NdlMetadataError("unsupported OAI metadataPrefix")
    params = {
        "verb": "GetRecord",
        "metadataPrefix": metadata_prefix,
        "identifier": identifier,
    }
    return OAI_URL + "?" + urllib.parse.urlencode(params)


def _parse_xml(raw: bytes) -> ET.Element:
    if not raw.lstrip().startswith(b"<"):
        raise NdlMetadataError("NDL Search response is not XML")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NdlMetadataError("invalid XML from NDL Search") from exc


def _record_data_xml(record_data: ET.Element) -> bytes:
    children = list(record_data)
    if children:
        return ET.tostring(children[0], encoding="utf-8")
    text = (record_data.text or "").strip()
    if not text:
        raise NdlMetadataError("SRU recordData is empty")
    return text.encode("utf-8")


def parse_sru_response(raw: bytes) -> tuple[int, tuple[SruDiscovery, ...]]:
    root = _parse_xml(raw)
    for elem in root.iter():
        if _local_name(elem.tag) == "diagnostic":
            message = " ".join("".join(elem.itertext()).split())
            raise NdlMetadataError(f"SRU diagnostic: {message}")
    number_elem = next((e for e in root.iter() if _local_name(e.tag) == "numberOfRecords"), None)
    if number_elem is None or not (number_elem.text or "").strip().isdigit():
        raise NdlMetadataError("SRU response lacks numberOfRecords")
    number_of_records = int((number_elem.text or "0").strip())
    discoveries: list[SruDiscovery] = []
    for record in (e for e in root.iter() if _local_name(e.tag) == "record"):
        position_elem = next((e for e in record if _local_name(e.tag) == "recordPosition"), None)
        data_elem = next((e for e in record if _local_name(e.tag) == "recordData"), None)
        if position_elem is None or data_elem is None:
            continue
        record_xml = _record_data_xml(data_elem)
        record_root = _parse_xml(record_xml)
        about = None
        for elem in record_root.iter():
            if _local_name(elem.tag) == "BibAdminResource" and elem.attrib.get(RDF_ABOUT):
                about = elem.attrib[RDF_ABOUT]
                break
        if about is None:
            raise NdlMetadataError("SRU record lacks BibAdminResource rdf:about")
        identifier = sru_about_to_oai_identifier(about)
        repository_number, item_number = split_oai_identifier(identifier)
        discoveries.append(SruDiscovery(
            record_position=int((position_elem.text or "0").strip()),
            oai_identifier=identifier,
            repository_number=repository_number,
            item_number=item_number,
            bibliographic_url=about,
            record_xml_sha256=sha256_bytes(record_xml),
        ))
    return number_of_records, tuple(discoveries)


_PROJECTION_FIELDS = {
    "title", "alternative", "creator", "publisher", "issued", "date",
    "subject", "identifier", "language", "type", "description",
    "publicationName", "volume", "issue", "pageRange", "rights", "accessRights",
}


def _metadata_projection(metadata_root: ET.Element) -> dict[str, Any]:
    values: dict[str, list[str]] = {}
    resource_links: list[str] = []
    for elem in metadata_root.iter():
        local = _local_name(elem.tag)
        text = " ".join((elem.text or "").split())
        if local in _PROJECTION_FIELDS and text:
            bucket = values.setdefault(local, [])
            if text not in bucket:
                bucket.append(text)
        resource = elem.attrib.get(RDF_RESOURCE)
        if resource and resource not in resource_links:
            resource_links.append(resource)
    projection: dict[str, Any] = {key: value for key, value in sorted(values.items())}
    if resource_links:
        projection["resource_links"] = resource_links
    return projection


def _issued_on(projection: dict[str, Any]) -> date | None:
    for key in ("issued", "date"):
        for value in projection.get(key, []):
            match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
            if match:
                try:
                    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                except ValueError:
                    continue
    return None


def _first(projection: dict[str, Any], key: str) -> str | None:
    values = projection.get(key, [])
    return values[0] if values else None


def parse_oai_get_record(
    raw: bytes,
    *,
    metadata_prefix: str = DEFAULT_METADATA_PREFIX,
    expected_identifier: str | None = None,
) -> OaiMetadataRecord:
    if metadata_prefix not in SUPPORTED_METADATA_PREFIXES:
        raise NdlMetadataError("unsupported OAI metadataPrefix")
    root = _parse_xml(raw)
    error_elem = next((e for e in root.iter() if _local_name(e.tag) == "error"), None)
    if error_elem is not None:
        code = error_elem.attrib.get("code", "unknown")
        text = " ".join("".join(error_elem.itertext()).split())
        raise NdlMetadataError(f"OAI-PMH error {code}: {text}")
    record = next((e for e in root.iter() if _local_name(e.tag) == "record"), None)
    if record is None:
        raise NdlMetadataError("OAI GetRecord response lacks record")
    header = next((e for e in record if _local_name(e.tag) == "header"), None)
    if header is None:
        raise NdlMetadataError("OAI record lacks header")
    status = header.attrib.get("status")
    if status not in (None, "deleted"):
        raise NdlMetadataError("unsupported OAI header status")
    deleted = status == "deleted"
    identifier_elem = next((e for e in header if _local_name(e.tag) == "identifier"), None)
    datestamp_elem = next((e for e in header if _local_name(e.tag) == "datestamp"), None)
    identifier = "" if identifier_elem is None else (identifier_elem.text or "").strip()
    datestamp = "" if datestamp_elem is None else (datestamp_elem.text or "").strip()
    repository_number, item_number = split_oai_identifier(identifier)
    if expected_identifier is not None and identifier != expected_identifier:
        raise NdlMetadataError("OAI response identifier mismatch")
    if not datestamp:
        raise NdlMetadataError("OAI record lacks datestamp")
    set_specs = tuple(
        (e.text or "").strip()
        for e in header
        if _local_name(e.tag) == "setSpec" and (e.text or "").strip()
    )
    metadata_container = next((e for e in record if _local_name(e.tag) == "metadata"), None)
    if deleted:
        if metadata_container is not None and list(metadata_container):
            raise NdlMetadataError("deleted OAI record unexpectedly contains metadata")
        metadata_sha = None
        projection: dict[str, Any] = {"oai_deleted": True}
    else:
        if metadata_container is None or len(metadata_container) != 1:
            raise NdlMetadataError("OAI record must contain exactly one metadata root")
        metadata_root = list(metadata_container)[0]
        metadata_xml = ET.tostring(metadata_root, encoding="utf-8")
        metadata_sha = sha256_bytes(metadata_xml)
        projection = _metadata_projection(metadata_root)
        projection["oai_deleted"] = False
    projection["oai_datestamp"] = datestamp
    projection["set_specs"] = list(set_specs)
    projection["metadata_prefix"] = metadata_prefix
    return OaiMetadataRecord(
        oai_identifier=identifier,
        repository_number=repository_number,
        item_number=item_number,
        oai_datestamp=datestamp,
        set_specs=set_specs,
        metadata_prefix=metadata_prefix,
        deleted=deleted,
        metadata_xml_sha256=metadata_sha,
        projection=projection,
        issued_on=_issued_on(projection),
        title=_first(projection, "title"),
    )


def metadata_observation_id(record: OaiMetadataRecord, snapshot_id: str) -> str:
    value = "\x1f".join((
        "phase6-ndl-metadata-observation-1.0",
        record.oai_identifier,
        snapshot_id,
        record.oai_datestamp,
        record.metadata_prefix,
        "deleted" if record.deleted else (record.metadata_xml_sha256 or "missing"),
    ))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class NdlSearchClient:
    def __init__(
        self,
        *,
        min_interval_seconds: float = 3.0,
        max_response_bytes: int = 10 * 1024 * 1024,
        opener: Callable[..., Any] = urllib.request.urlopen,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval_seconds < 0:
            raise NdlMetadataError("min_interval_seconds must be non-negative")
        if max_response_bytes <= 0:
            raise NdlMetadataError("max_response_bytes must be positive")
        self.min_interval_seconds = min_interval_seconds
        self.max_response_bytes = max_response_bytes
        self._opener = opener
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleeper(remaining)
        self._last_request_at = self._monotonic()

    def _get(self, url: str) -> tuple[bytes, datetime]:
        self._throttle()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "legal-knowledge-base-phase6.4/1.0"},
        )
        with self._opener(request, timeout=60) as response:
            raw = response.read(self.max_response_bytes + 1)
        if len(raw) > self.max_response_bytes:
            raise NdlMetadataError("NDL Search response exceeds configured size limit")
        return raw, datetime.now(timezone.utc)

    def discover_sru(
        self,
        query: str,
        *,
        maximum_records: int = 1,
        start_record: int = 1,
    ) -> tuple[int, tuple[SruDiscovery, ...], str, bytes]:
        url = build_sru_url(query, maximum_records=maximum_records, start_record=start_record)
        raw, _ = self._get(url)
        total, records = parse_sru_response(raw)
        return total, records, url, raw

    def get_oai_record(
        self,
        identifier: str,
        *,
        metadata_prefix: str = DEFAULT_METADATA_PREFIX,
    ) -> FetchedOaiRecord:
        url = build_oai_get_record_url(identifier, metadata_prefix=metadata_prefix)
        raw, observed_at = self._get(url)
        record = parse_oai_get_record(
            raw,
            metadata_prefix=metadata_prefix,
            expected_identifier=identifier,
        )
        return FetchedOaiRecord(
            record=record,
            request_url=url,
            raw_payload=raw,
            payload_sha256=sha256_bytes(raw),
            observed_at=observed_at,
        )
