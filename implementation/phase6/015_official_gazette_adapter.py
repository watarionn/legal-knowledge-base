from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping

PROVIDER_CODE = "kanpo-cao"
BASE_URL = "https://www.kanpo.go.jp/"
ASSET_ID_VERSION = "phase6-official-gazette-asset-1.0"
ALLOWED_KINDS = {
    "regular",
    "extra",
    "government-procurement",
    "special-extra",
    "index",
}
US = "\x1f"


def _sha256(*parts: str) -> str:
    if any(not isinstance(part, str) or not part for part in parts):
        raise ValueError("identity parts must be non-empty strings")
    return hashlib.sha256(US.join(parts).encode("utf-8")).hexdigest()
def derived_provider_document_id(
    issued_on: date,
    publication_kind: str,
    issue_number: int,
) -> str:
    if publication_kind not in ALLOWED_KINDS:
        raise ValueError(f"unsupported publication_kind: {publication_kind}")
    if not isinstance(issue_number, int) or issue_number <= 0:
        raise ValueError("issue_number must be a positive integer")
    return f"derived:{issued_on.isoformat()}:{publication_kind}:{issue_number}"


def validate_pdf_url(url: str, issued_on: date) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.kanpo.go.jp":
        raise ValueError("Gazette PDF URL must use https://www.kanpo.go.jp")
    path = urllib.parse.unquote(parsed.path)
    date_token = issued_on.strftime("%Y%m%d")
    if f"/{date_token}/" not in path:
        raise ValueError("Gazette PDF URL date does not match issued_on")
    if not path.lower().endswith(".pdf") or "/pdf/" not in path.lower():
        raise ValueError("Gazette asset URL must point to an explicit PDF")
    if parsed.query or parsed.fragment:
        raise ValueError("Gazette PDF URL must not contain query or fragment")
    return urllib.parse.urlunparse(parsed)
@dataclass(frozen=True)
class GazetteIssueSpec:
    issued_on: date
    publication_kind: str
    issue_number: int

    @property
    def provider_document_id(self) -> str:
        return derived_provider_document_id(
            self.issued_on,
            self.publication_kind,
            self.issue_number,
        )


@dataclass(frozen=True)
class GazettePdfAssetSpec:
    issue: GazetteIssueSpec
    pdf_url: str
    page_start: int
    page_end: int

    def __post_init__(self) -> None:
        if self.page_start <= 0 or self.page_end < self.page_start:
            raise ValueError("invalid Gazette page range")
        validate_pdf_url(self.pdf_url, self.issue.issued_on)

    @property
    def id(self) -> str:
        return _sha256(
            ASSET_ID_VERSION,
            self.issue.provider_document_id,
            str(self.page_start),
            str(self.page_end),
            self.pdf_url,
        )
@dataclass(frozen=True)
class GazetteCertificateObservation:
    signature_field_count: int
    document_timestamp_count: int
    byte_range_count: int
    cades_detached_count: int
    cryptographic_verification_status: str = "not-checked"
    verifier_name: str | None = None
    verifier_version: str | None = None
    details: Mapping[str, object] | None = None


@dataclass(frozen=True)
class FetchedGazetteAsset:
    asset: GazettePdfAssetSpec
    raw_payload: bytes
    payload_sha256: str
    observed_at: datetime
    certificate: GazetteCertificateObservation

    @property
    def byte_size(self) -> int:
        return len(self.raw_payload)


def inspect_pdf_signature_structure(payload: bytes) -> GazetteCertificateObservation:
    if not payload.startswith(b"%PDF-"):
        raise ValueError("Gazette payload is not a PDF")
    return GazetteCertificateObservation(
        signature_field_count=payload.count(b"/Type /Sig"),
        document_timestamp_count=payload.count(b"/DocTimeStamp"),
        byte_range_count=payload.count(b"/ByteRange"),
        cades_detached_count=payload.count(b"/ETSI.CAdES.detached"),
        details={"method": "byte-structure-count-v1"},
    )
def fetch_explicit_pdf(
    asset: GazettePdfAssetSpec,
    *,
    timeout: float = 30.0,
    max_bytes: int = 128 * 1024 * 1024,
    user_agent: str = "legal-knowledge-base-phase6/1.0",
) -> FetchedGazetteAsset:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    url = validate_pdf_url(asset.pdf_url, asset.issue.issued_on)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = validate_pdf_url(response.geturl(), asset.issue.issued_on)
        if final_url != url:
            raise ValueError("Gazette PDF redirects are not accepted")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("Gazette PDF exceeds max_bytes")
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("Gazette PDF exceeds max_bytes")
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    return FetchedGazetteAsset(
        asset=asset,
        raw_payload=payload,
        payload_sha256=payload_sha256,
        observed_at=datetime.now(timezone.utc),
        certificate=inspect_pdf_signature_structure(payload),
    )
