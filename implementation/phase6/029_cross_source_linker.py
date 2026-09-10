from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

LAW_ID_RE = re.compile(r"(?<![0-9A-Z])[0-9A-Z]{15}(?![0-9A-Z])")
AUTO_PROVIDER_RELATION_KIND = {
    "kokkai-ndl": "mentions",
    "teikoku-ndl": "mentions",
    "ndl-search": "bibliographic-reference",
}


@dataclass(frozen=True)
class LawCatalogEntry:
    law_id: str
    law_num: str | None
    titles: tuple[str, ...]


@dataclass(frozen=True)
class RevisionCatalogEntry:
    law_revision_id: str
    law_id: str
    amendment_law_id: str | None
    amendment_law_num: str | None
    amendment_law_title: str | None


@dataclass(frozen=True)
class EvidenceSignal:
    assertion_basis: str
    signal_kind: str
    matched_value: str
    source_locator: str

@dataclass(frozen=True)
class LinkProposal:
    target_kind: str
    target_id: str
    relation_kind: str
    signals: tuple[EvidenceSignal, ...]


def normalize_exact_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return "".join(value.split())


def _contains_token(text: str, token: str | None) -> bool:
    if not token:
        return False
    normalized = normalize_exact_text(token)
    if len(normalized) < 3:
        return False
    return normalized in normalize_exact_text(text)


def _contains_law_id(text: str, law_id: str | None) -> bool:
    if not law_id:
        return False
    return law_id in LAW_ID_RE.findall(unicodedata.normalize("NFKC", text).upper())


def _add_signal(
    grouped: dict[tuple[str, str, str], list[EvidenceSignal]],
    *,
    target_kind: str,
    target_id: str,
    relation_kind: str,
    signal: EvidenceSignal,
) -> None:
    key = (target_kind, target_id, relation_kind)
    bucket = grouped.setdefault(key, [])
    if signal not in bucket:
        bucket.append(signal)

def build_link_proposals(
    *,
    provider_code: str,
    text_sources: Sequence[tuple[str, str]],
    laws: Iterable[LawCatalogEntry],
    revisions: Iterable[RevisionCatalogEntry],
) -> tuple[LinkProposal, ...]:
    if provider_code not in AUTO_PROVIDER_RELATION_KIND:
        return ()
    relation_kind = AUTO_PROVIDER_RELATION_KIND[provider_code]
    grouped: dict[tuple[str, str, str], list[EvidenceSignal]] = {}

    for locator, text in text_sources:
        if not text:
            continue
        for law in laws:
            if _contains_law_id(text, law.law_id):
                _add_signal(grouped, target_kind="law", target_id=law.law_id,
                    relation_kind=relation_kind,
                    signal=EvidenceSignal("identifier-match", "law-id-exact", law.law_id, locator))
            if _contains_token(text, law.law_num):
                _add_signal(grouped, target_kind="law", target_id=law.law_id,
                    relation_kind=relation_kind,
                    signal=EvidenceSignal("identifier-match", "law-number-exact", law.law_num or "", locator))
            for title in law.titles:
                if _contains_token(text, title):
                    _add_signal(grouped, target_kind="law", target_id=law.law_id,
                        relation_kind=relation_kind,
                        signal=EvidenceSignal("text-match", "law-title-exact", title, locator))

        for revision in revisions:
            matched = []
            if _contains_law_id(text, revision.amendment_law_id):
                matched.append(("identifier-match", "amendment-law-id-exact", revision.amendment_law_id))
            if _contains_token(text, revision.amendment_law_num):
                matched.append(("identifier-match", "amendment-law-number-exact", revision.amendment_law_num))
            if _contains_token(text, revision.amendment_law_title):
                matched.append(("text-match", "amendment-law-title-exact", revision.amendment_law_title))
            for basis, kind, value in matched:
                if value:
                    _add_signal(grouped, target_kind="law_revision", target_id=revision.law_revision_id,
                        relation_kind="amendment-material",
                        signal=EvidenceSignal(basis, kind, value, locator))

    proposals = [
        LinkProposal(target_kind=k[0], target_id=k[1], relation_kind=k[2], signals=tuple(v))
        for k, v in grouped.items()
    ]
    proposals.sort(key=lambda p: (p.target_kind, p.target_id, p.relation_kind))
    return tuple(proposals)


def effective_relation_state(statuses: Sequence[str]) -> str:
    values = set(statuses)
    if not values or not values <= {"candidate", "confirmed", "rejected"}:
        raise ValueError("invalid or empty assertion status set")
    if "confirmed" in values and "rejected" in values:
        return "conflicted"
    if "confirmed" in values:
        return "confirmed"
    if "rejected" in values:
        return "rejected"
    return "candidate"


def citation_ready(effective_state: str) -> bool:
    if effective_state not in {"candidate", "confirmed", "rejected", "conflicted"}:
        raise ValueError("unsupported effective state")
    return effective_state == "confirmed"
