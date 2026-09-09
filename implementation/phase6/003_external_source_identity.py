from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

IDENTITY_VERSION = "phase6-external-document-1.0"
SNAPSHOT_VERSION = "phase6-external-snapshot-1.0"
RELATION_VERSION = "phase6-source-relation-1.0"
ASSERTION_VERSION = "phase6-relation-assertion-1.0"
US = "\x1f"


def _sha256_identity(version: str, *parts: str) -> str:
    values = [version, *parts]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("identity parts must be non-empty strings")
    return hashlib.sha256(US.join(values).encode("utf-8")).hexdigest()


def normalize_sha256(value: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        raise ValueError("sha256 must be 64 hexadecimal characters")
    return normalized


def external_document_id(provider_code: str, provider_document_id: str) -> str:
    return _sha256_identity(IDENTITY_VERSION, provider_code, provider_document_id)


def snapshot_id(external_document_id_value: str, payload_sha256: str) -> str:
    return _sha256_identity(
        SNAPSHOT_VERSION,
        external_document_id_value,
        normalize_sha256(payload_sha256),
    )


def target_identifier(
    *,
    target_kind: str,
    law_id: str | None = None,
    law_revision_id: str | None = None,
    document_pk: int | None = None,
    document_order: int | None = None,
) -> str:
    if target_kind == "law" and law_id and not any(
        value is not None for value in (law_revision_id, document_pk, document_order)
    ):
        return law_id
    if target_kind == "law_revision" and law_revision_id and not any(
        value is not None for value in (law_id, document_pk, document_order)
    ):
        return law_revision_id
    if (
        target_kind == "provision_node"
        and document_pk is not None
        and document_order is not None
        and law_id is None
        and law_revision_id is None
        and document_pk > 0
        and document_order > 0
    ):
        return f"{document_pk}:{document_order}"
    raise ValueError("target fields do not match target_kind")


def source_relation_id(
    external_document_id_value: str,
    target_kind: str,
    target_id: str,
    relation_kind: str,
) -> str:
    return _sha256_identity(
        RELATION_VERSION,
        external_document_id_value,
        target_kind,
        target_id,
        relation_kind,
    )


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relation_assertion_id(
    source_relation_id_value: str,
    assertion_basis: str,
    observed_evidence: Mapping[str, Any],
) -> str:
    return _sha256_identity(
        ASSERTION_VERSION,
        source_relation_id_value,
        assertion_basis,
        canonical_json_sha256(observed_evidence),
    )


def default_assertion_status(assertion_basis: str) -> str:
    if assertion_basis in {"provider-explicit", "manual"}:
        return "confirmed"
    if assertion_basis in {"identifier-match", "metadata-match", "text-match", "derived"}:
        return "candidate"
    raise ValueError(f"unsupported assertion_basis: {assertion_basis}")


@dataclass(frozen=True)
class ExternalDocumentIdentity:
    provider_code: str
    provider_document_id: str

    @property
    def id(self) -> str:
        return external_document_id(self.provider_code, self.provider_document_id)
