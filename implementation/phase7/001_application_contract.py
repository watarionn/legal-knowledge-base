from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re
from typing import Any, Iterable, Mapping

LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
MAX_QUESTION_CHARS = 4000
_ALLOWED_QUERY_FIELDS = frozenset({"question", "as_of_date", "law_id"})


class RequestValidationError(ValueError):
    pass


@dataclass(frozen=True)
class QueryRequest:
    question: str
    requested_as_of_date: date | None
    effective_as_of_date: date
    as_of_date_source: str
    law_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "requested_as_of_date": (
                self.requested_as_of_date.isoformat()
                if self.requested_as_of_date is not None else None
            ),
            "effective_as_of_date": self.effective_as_of_date.isoformat(),
            "as_of_date_source": self.as_of_date_source,
            "law_id": self.law_id,
        }


@dataclass(frozen=True)
class LawCandidate:
    law_id: str
    law_num: str | None
    law_title: str | None
    abbrev: str | None
    matched_text: str | None
    match_kind: str
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LawResolution:
    status: str
    method: str
    selected_law_id: str | None
    selected_law_title: str | None
    candidates: tuple[LawCandidate, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "method": self.method,
            "selected_law_id": self.selected_law_id,
            "selected_law_title": self.selected_law_title,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
        }


def parse_query_payload(
    payload: Any,
    *,
    default_date: date | None = None,
) -> QueryRequest:
    if not isinstance(payload, dict):
        raise RequestValidationError("request body must be a JSON object")
    unknown = sorted(set(payload) - _ALLOWED_QUERY_FIELDS)
    if unknown:
        raise RequestValidationError(f"unknown request fields: {', '.join(unknown)}")

    question = payload.get("question")
    if not isinstance(question, str):
        raise RequestValidationError("question must be a string")
    question = question.strip()
    if not question:
        raise RequestValidationError("question must not be blank")
    if len(question) > MAX_QUESTION_CHARS:
        raise RequestValidationError(
            f"question must be at most {MAX_QUESTION_CHARS} characters"
        )

    raw_date = payload.get("as_of_date")
    requested_date: date | None = None
    if raw_date not in (None, ""):
        if not isinstance(raw_date, str):
            raise RequestValidationError("as_of_date must be an ISO date string")
        try:
            requested_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise RequestValidationError("as_of_date must be YYYY-MM-DD") from exc

    law_id = payload.get("law_id")
    if law_id in (None, ""):
        law_id = None
    elif not isinstance(law_id, str) or not LAW_ID_RE.fullmatch(law_id):
        raise RequestValidationError("law_id must be a 15-character e-Gov law ID")

    effective_date = requested_date or default_date or date.today()
    return QueryRequest(
        question=question,
        requested_as_of_date=requested_date,
        effective_as_of_date=effective_date,
        as_of_date_source="request" if requested_date is not None else "server-date-default",
        law_id=law_id,
    )


def explicit_law_resolution(row: Mapping[str, Any] | None) -> LawResolution:
    if row is None:
        return LawResolution(
            status="law-not-found",
            method="explicit-law-id",
            selected_law_id=None,
            selected_law_title=None,
            candidates=(),
            warnings=("EXPLICIT_LAW_ID_NOT_FOUND",),
        )
    candidate = LawCandidate(
        law_id=str(row["law_id"]),
        law_num=row.get("law_num"),
        law_title=row.get("law_title"),
        abbrev=row.get("abbrev"),
        matched_text=str(row["law_id"]),
        match_kind="explicit-law-id",
    )
    return LawResolution(
        status="resolved",
        method="explicit-law-id",
        selected_law_id=candidate.law_id,
        selected_law_title=candidate.law_title,
        candidates=(candidate,),
    )


def _best_phrase_candidate(question: str, row: Mapping[str, Any]) -> LawCandidate | None:
    options: list[tuple[int, int, str, str]] = []
    for kind, field, priority in (
        ("law-number", "law_num", 3),
        ("law-title", "law_title", 2),
        ("abbrev", "abbrev", 1),
    ):
        value = row.get(field)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value in question:
            options.append((priority, len(value), kind, value))
    if not options:
        return None
    priority, _, kind, matched = max(options)
    return LawCandidate(
        law_id=str(row["law_id"]),
        law_num=row.get("law_num"),
        law_title=row.get("law_title"),
        abbrev=row.get("abbrev"),
        matched_text=matched,
        match_kind=kind,
        score=float(priority),
    )


def resolve_law_phrases(
    question: str,
    rows: Iterable[Mapping[str, Any]],
) -> LawResolution:
    grouped: dict[str, LawCandidate] = {}
    for row in rows:
        candidate = _best_phrase_candidate(question, row)
        if candidate is None:
            continue
        previous = grouped.get(candidate.law_id)
        if previous is None:
            grouped[candidate.law_id] = candidate
            continue
        old_key = (previous.score or 0.0, len(previous.matched_text or ""))
        new_key = (candidate.score or 0.0, len(candidate.matched_text or ""))
        if new_key > old_key:
            grouped[candidate.law_id] = candidate

    candidates = tuple(
        sorted(
            grouped.values(),
            key=lambda item: (-(item.score or 0.0), -len(item.matched_text or ""), item.law_id),
        )
    )
    if not candidates:
        return LawResolution(
            status="law-not-found",
            method="phrase",
            selected_law_id=None,
            selected_law_title=None,
            candidates=(),
        )
    if len(candidates) == 1:
        only = candidates[0]
        return LawResolution(
            status="resolved",
            method=only.match_kind,
            selected_law_id=only.law_id,
            selected_law_title=only.law_title,
            candidates=candidates,
        )

    top = candidates[0]
    top_text = top.matched_text or ""
    same_top = [
        item for item in candidates
        if (item.score or 0.0, len(item.matched_text or ""))
        == (top.score or 0.0, len(top_text))
    ]
    others_are_nested = all(
        item.matched_text is not None
        and item.matched_text != top_text
        and item.matched_text in top_text
        for item in candidates[1:]
    )
    if len(same_top) == 1 and others_are_nested:
        return LawResolution(
            status="resolved",
            method=f"{top.match_kind}-longest-nested",
            selected_law_id=top.law_id,
            selected_law_title=top.law_title,
            candidates=candidates,
            warnings=("NESTED_LAW_PHRASES_COLLAPSED_TO_LONGEST",),
        )

    return LawResolution(
        status="law-candidates",
        method="phrase-ambiguous",
        selected_law_id=None,
        selected_law_title=None,
        candidates=candidates,
        warnings=("MULTIPLE_LAW_PHRASES",),
    )


def suggestion_resolution(rows: Iterable[Mapping[str, Any]]) -> LawResolution:
    candidates = []
    for row in rows:
        score = float(row.get("score") or 0.0)
        candidates.append(LawCandidate(
            law_id=str(row["law_id"]),
            law_num=row.get("law_num"),
            law_title=row.get("law_title"),
            abbrev=row.get("abbrev"),
            matched_text=None,
            match_kind="trigram-suggestion",
            score=score,
        ))
    candidates.sort(key=lambda item: (-(item.score or 0.0), item.law_id))
    if not candidates:
        return LawResolution(
            status="law-not-found",
            method="trigram-suggestion",
            selected_law_id=None,
            selected_law_title=None,
            candidates=(),
            warnings=("NO_LAW_CANDIDATE",),
        )
    return LawResolution(
        status="law-candidates",
        method="trigram-suggestion",
        selected_law_id=None,
        selected_law_title=None,
        candidates=tuple(candidates),
        warnings=("LAW_SELECTION_REQUIRED",),
    )
