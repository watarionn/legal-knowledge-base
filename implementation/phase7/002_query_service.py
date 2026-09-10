from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from datetime import date
import importlib.util
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from typing import Any, Mapping
import uuid

HERE = Path(__file__).resolve().parent
PHASE5_DIR = HERE.parent / "phase5"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DATE_TEXT_RE = re.compile(r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{4}年\d{1,2}月(?:\d{1,2}日)?)")
_ARTICLE_RE = re.compile(r"第([0-9０-９]+)条")
_SPLIT_RE = re.compile(
    r"(?:について|に関係する|に関する|を教えてください|を教えて|教えてください|教えて|"
    r"とは|では|から|まで|より|で|は|が|を|に|の|と)"
)
_STOP_SEGMENTS = frozenset({
    "規定", "内容", "法律", "法令", "時点", "場合", "場面", "ください",
    "確認", "確認する", "確認したい", "知りたい", "調べる", "調べたい", "見たい",
})


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = _load("legal_kb_phase7_contract", HERE / "001_application_contract.py")


class Phase7ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class QueryServiceConfig:
    chunking_config_sha256: str | None = None
    suggestion_limit: int = 5
    suggestion_min_score: float = 0.12
    max_evidence: int = 8

    @classmethod
    def from_environment(cls) -> "QueryServiceConfig":
        value = os.environ.get("LEGAL_KB_CHUNKING_CONFIG_SHA256") or None
        return cls(chunking_config_sha256=value)

    def validate(self) -> None:
        if self.chunking_config_sha256 is not None and not _SHA256_RE.fullmatch(
            self.chunking_config_sha256
        ):
            raise Phase7ConfigurationError(
                "LEGAL_KB_CHUNKING_CONFIG_SHA256 must be a SHA-256 hex string"
            )
        if self.suggestion_limit <= 0 or self.suggestion_limit > 20:
            raise Phase7ConfigurationError("suggestion_limit must be in 1..20")
        if not (0.0 <= self.suggestion_min_score <= 1.0):
            raise Phase7ConfigurationError("suggestion_min_score must be in 0..1")
        if self.max_evidence <= 0:
            raise Phase7ConfigurationError("max_evidence must be positive")


def _selected_candidate(law_resolution: Any) -> Any | None:
    selected_id = law_resolution.selected_law_id
    if selected_id is None:
        return None
    return next(
        (item for item in law_resolution.candidates if item.law_id == selected_id),
        None,
    )


def _ascii_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def structural_filter_from_question(question: str) -> dict[str, str | None]:
    match = _ARTICLE_RE.search(question)
    if match is None:
        return {"tag_name": None, "structural_num": None, "display_label": None}
    return {
        "tag_name": "Article",
        "structural_num": _ascii_digits(match.group(1)),
        "display_label": None,
    }


def plan_retrieval_text(question: str, law_resolution: Any) -> str:
    text = question.strip()
    candidate = _selected_candidate(law_resolution)
    if candidate is not None and candidate.matched_text:
        text = text.replace(candidate.matched_text, " ")
    text = _DATE_TEXT_RE.sub(" ", text)
    text = re.sub(r"(?:現在|現行|時点)", " ", text)
    text = re.sub(r"[、。！？!?：:；;（）()\[\]【】「」『』\s]+", " ", text).strip()
    segments = []
    for part in _SPLIT_RE.split(text):
        value = part.strip()
        value = re.sub(r"^(?:第[0-9０-９]+条)$", "", value).strip()
        if len(value) >= 2 and value not in _STOP_SEGMENTS:
            segments.append(value)
    if segments:
        return max(segments, key=lambda item: (len(item), item))
    fallback = text.strip()
    return fallback if fallback else question.strip()


def evidence_to_api(bundle: Any) -> dict[str, Any]:
    nodes = [asdict(node) for node in bundle.source_nodes]
    texts = [
        node["text_original"].strip()
        for node in nodes
        if isinstance(node.get("text_original"), str) and node["text_original"].strip()
    ]
    quote_full = "\n".join(texts)
    quote = quote_full[:1000]
    if len(quote_full) > 1000:
        quote += "…"
    paths = [node["xml_path"] for node in nodes if node.get("xml_path")]
    if not paths:
        display_path = None
    elif len(paths) == 1 or paths[0] == paths[-1]:
        display_path = paths[0]
    else:
        display_path = f"{paths[0]} … {paths[-1]}"
    return {
        "evidence_id": bundle.evidence_id,
        "retrieval_rank": bundle.retrieval_rank,
        "chunk_id": bundle.chunk_id,
        "law_id": bundle.law_id,
        "law_revision_id": bundle.law_revision_id,
        "document_pk": bundle.document_pk,
        "source_xml_sha256": bundle.source_xml_sha256,
        "source_xml_sha256_short": bundle.source_xml_sha256[:12],
        "display_path": display_path,
        "quote": quote,
        "source_nodes": nodes,
        "citation_truth": "phase3-phase4",
    }


def _fetch_explicit_law(conn: Any, law_id: str) -> Mapping[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.law_id, l.law_num, latest.law_title, latest.abbrev
            FROM legal_kb.law l
            LEFT JOIN LATERAL (
                SELECT lr.law_title, lr.abbrev
                FROM legal_kb.law_revision lr
                WHERE lr.law_id = l.law_id
                ORDER BY (lr.current_revision_status = 'current') DESC,
                         lr.revision_sequence DESC NULLS LAST,
                         lr.updated DESC NULLS LAST,
                         lr.law_revision_id DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE l.law_id = %s
            """,
            (law_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        names = [column.name for column in cur.description]
    return dict(zip(names, row))


def _fetch_phrase_rows(conn: Any, question: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT lr.law_id, l.law_num, lr.law_title, lr.abbrev
            FROM legal_kb.law_revision lr
            JOIN legal_kb.law l ON l.law_id = lr.law_id
            WHERE (lr.law_title IS NOT NULL AND btrim(lr.law_title) <> ''
                   AND strpos(%s, lr.law_title) > 0)
               OR (lr.abbrev IS NOT NULL AND btrim(lr.abbrev) <> ''
                   AND strpos(%s, lr.abbrev) > 0)
               OR (l.law_num IS NOT NULL AND btrim(l.law_num) <> ''
                   AND strpos(%s, l.law_num) > 0)
            """,
            (question, question, question),
        )
        names = [column.name for column in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _fetch_law_suggestions(
    conn: Any,
    question: str,
    *,
    limit: int,
    min_score: float,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH scored AS (
                SELECT lr.law_id, l.law_num, lr.law_title, lr.abbrev,
                       greatest(
                           similarity(%s, coalesce(lr.law_title, '')),
                           similarity(%s, coalesce(lr.abbrev, '')),
                           similarity(%s, coalesce(l.law_num, ''))
                       )::real AS score,
                       lr.revision_sequence,
                       lr.updated,
                       lr.law_revision_id
                FROM legal_kb.law_revision lr
                JOIN legal_kb.law l ON l.law_id = lr.law_id
            ), ranked AS (
                SELECT *, row_number() OVER (
                    PARTITION BY law_id
                    ORDER BY score DESC,
                             revision_sequence DESC NULLS LAST,
                             updated DESC NULLS LAST,
                             law_revision_id DESC
                ) AS rn
                FROM scored
            )
            SELECT law_id, law_num, law_title, abbrev, score
            FROM ranked
            WHERE rn = 1 AND score >= %s
            ORDER BY score DESC, law_id
            LIMIT %s
            """,
            (question, question, question, min_score, limit),
        )
        names = [column.name for column in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _discover_chunking_config(conn: Any, configured: str | None) -> str:
    if configured is not None:
        return configured.lower()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT chunking_config_sha256
            FROM legal_kb.retrieval_chunk
            ORDER BY chunking_config_sha256
            LIMIT 2
            """
        )
        rows = cur.fetchall()
    if not rows:
        raise Phase7ConfigurationError("no retrieval_chunk configuration is available")
    if len(rows) != 1:
        configs = ", ".join(str(row[0])[:12] for row in rows[:5])
        raise Phase7ConfigurationError(
            "multiple retrieval chunk configurations exist; set "
            f"LEGAL_KB_CHUNKING_CONFIG_SHA256 explicitly ({configs})"
        )
    return str(rows[0][0]).lower()


@lru_cache(maxsize=1)
def _load_phase5_modules() -> tuple[Any, Any]:
    hybrid = _load("legal_kb_phase5_hybrid_for_phase7", PHASE5_DIR / "034_hybrid_retrieval.py")
    rag = _load("legal_kb_phase5_rag_for_phase7", PHASE5_DIR / "038_rag_answer_contract.py")
    return hybrid, rag


def _base_response(query_id: str, request: Any, law_resolution: Any) -> dict[str, Any]:
    return {
        "api_version": "1",
        "query_id": query_id,
        "question": request.question,
        "requested_as_of_date": (
            request.requested_as_of_date.isoformat()
            if request.requested_as_of_date is not None else None
        ),
        "effective_as_of_date": request.effective_as_of_date.isoformat(),
        "as_of_date_source": request.as_of_date_source,
        "status": None,
        "law_resolution": law_resolution.to_dict(),
        "temporal_resolution": None,
        "retrieval": None,
        "answer": None,
        "evidence": [],
        "timing_ms": {},
        "warnings": [],
    }


class QueryService:
    def __init__(self, config: QueryServiceConfig | None = None):
        self.config = config or QueryServiceConfig.from_environment()
        self.config.validate()

    def resolve_law(self, conn: Any, request: Any) -> Any:
        if request.law_id is not None:
            return CONTRACT.explicit_law_resolution(_fetch_explicit_law(conn, request.law_id))
        resolution = CONTRACT.resolve_law_phrases(
            request.question,
            _fetch_phrase_rows(conn, request.question),
        )
        if resolution.status != "law-not-found":
            return resolution
        return CONTRACT.suggestion_resolution(
            _fetch_law_suggestions(
                conn,
                request.question,
                limit=self.config.suggestion_limit,
                min_score=self.config.suggestion_min_score,
            )
        )

    def query(
        self,
        conn: Any,
        payload: Any,
        *,
        default_date: date | None = None,
        answer_provider: Any | None = None,
    ) -> dict[str, Any]:
        total_started = perf_counter()
        request = CONTRACT.parse_query_payload(payload, default_date=default_date)
        query_id = uuid.uuid4().hex

        stage_started = perf_counter()
        law_resolution = self.resolve_law(conn, request)
        law_ms = round((perf_counter() - stage_started) * 1000, 3)
        response = _base_response(query_id, request, law_resolution)
        response["timing_ms"]["law_resolution"] = law_ms

        if law_resolution.status != "resolved":
            response["status"] = law_resolution.status
            response["answer"] = {
                "status": "not-run",
                "answer_text": "",
                "claims": [],
                "provider": None,
                "citation_ready": False,
            }
            response["timing_ms"]["total"] = round((perf_counter() - total_started) * 1000, 3)
            return response

        retrieval_query_text = plan_retrieval_text(request.question, law_resolution)
        structural_data = structural_filter_from_question(request.question)
        chunking_config = _discover_chunking_config(
            conn, self.config.chunking_config_sha256
        )
        hybrid, rag = _load_phase5_modules()
        retrieval_config = hybrid.RetrievalConfig(
            lexical_weight=1.0,
            structural_weight=0.75,
            vector_weight=0.0,
            max_contexts=self.config.max_evidence,
            chunking_config_sha256=chunking_config,
            embedding_profile_id=None,
        )
        structural_filter = hybrid.StructuralFilter(**structural_data)

        stage_started = perf_counter()
        retrieval_result = hybrid.hybrid_retrieve(
            conn,
            law_resolution.selected_law_id,
            request.effective_as_of_date,
            retrieval_query_text,
            config=retrieval_config,
            structural_filter=structural_filter,
        )
        retrieval_ms = round((perf_counter() - stage_started) * 1000, 3)
        response["temporal_resolution"] = retrieval_result.resolution.to_dict()
        response["retrieval"] = {
            "status": retrieval_result.status,
            "retrieval_version": retrieval_result.retrieval_version,
            "retrieval_config_sha256": retrieval_result.retrieval_config_sha256,
            "chunking_config_sha256": chunking_config,
            "query_text": retrieval_query_text,
            "structural_filter": structural_data,
            "channel_counts": dict(retrieval_result.channel_counts),
            "warnings": list(retrieval_result.warnings),
        }
        response["timing_ms"]["temporal_and_retrieval"] = retrieval_ms

        if retrieval_result.status == "blocked-temporal":
            response["status"] = "blocked-temporal"
        elif retrieval_result.status == "blocked-content":
            response["status"] = "blocked-content"
        elif retrieval_result.status == "no-hits":
            response["status"] = "no-hits"
        else:
            response["status"] = "evidence-only"

        if retrieval_result.status != "ok":
            response["answer"] = {
                "status": "not-run",
                "answer_text": "",
                "claims": [],
                "provider": None,
                "citation_ready": False,
            }
            response["warnings"].extend(retrieval_result.warnings)
            response["timing_ms"]["total"] = round((perf_counter() - total_started) * 1000, 3)
            return response

        stage_started = perf_counter()
        evidence_bundles = rag.build_evidence_bundles(conn, retrieval_result)
        evidence_ms = round((perf_counter() - stage_started) * 1000, 3)
        response["evidence"] = [evidence_to_api(item) for item in evidence_bundles]
        response["timing_ms"]["evidence"] = evidence_ms

        if answer_provider is None:
            response["answer"] = {
                "status": "provider-not-configured",
                "answer_text": "",
                "claims": [],
                "provider": None,
                "citation_ready": False,
                "semantic_entailment_verified": False,
                "generated_answer_is_source_truth": False,
            }
            response["status"] = "evidence-only"
        else:
            stage_started = perf_counter()
            try:
                answer_envelope = rag.generate_and_finalize(
                    answer_provider, request.question, evidence_bundles
                )
                response["answer"] = answer_envelope.to_dict()
                response["status"] = (
                    "answered" if answer_envelope.citation_ready else "answer-failed"
                )
            except Exception:
                response["answer"] = {
                    "status": "provider-error",
                    "answer_text": "",
                    "claims": [],
                    "provider": None,
                    "citation_ready": False,
                    "semantic_entailment_verified": False,
                    "generated_answer_is_source_truth": False,
                }
                response["status"] = "answer-failed"
                response["warnings"].append("ANSWER_PROVIDER_FAILED")
            response["timing_ms"]["answer"] = round(
                (perf_counter() - stage_started) * 1000, 3
            )

        response["timing_ms"]["total"] = round((perf_counter() - total_started) * 1000, 3)
        return response
