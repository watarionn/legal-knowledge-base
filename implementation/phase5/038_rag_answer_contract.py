#!/usr/bin/env python3
"""Phase 5.3d RAG answer / citation contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any, Protocol, Sequence

CONTRACT_VERSION = "phase5-rag-answer-contract-1.0"


@dataclass(frozen=True)
class SourceNodeEvidence:
    document_order: int
    node_id_hex: str
    xml_path: str
    tag_name: str | None
    structural_num: str | None
    display_label: str | None
    text_original: str | None


@dataclass(frozen=True)
class EvidenceBundle:
    evidence_id: str
    retrieval_rank: int
    chunk_id: str
    law_id: str
    law_revision_id: str
    document_pk: int
    source_xml_sha256: str
    source_nodes: tuple[SourceNodeEvidence, ...]


@dataclass(frozen=True)
class AnswerClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class AnswerDraft:
    answer_text: str
    claims: tuple[AnswerClaim, ...]


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str
    model_version: str

    def validate(self) -> None:
        for name in ("provider", "model", "model_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")


@dataclass(frozen=True)
class RagAnswerEnvelope:
    status: str
    answer_text: str
    claims: tuple[AnswerClaim, ...]
    evidence: tuple[EvidenceBundle, ...]
    warnings: tuple[str, ...]
    provider: ProviderMetadata | None
    contract_version: str = CONTRACT_VERSION
    citation_ready: bool = False
    semantic_entailment_verified: bool = False
    generated_answer_is_source_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "contract_version": self.contract_version,
            "answer_text": self.answer_text,
            "claims": [asdict(claim) for claim in self.claims],
            "evidence": [asdict(item) for item in self.evidence],
            "warnings": list(self.warnings),
            "provider": asdict(self.provider) if self.provider else None,
            "citation_truth": "phase3-phase4",
            "citation_ready": self.citation_ready,
            "semantic_entailment_verified": self.semantic_entailment_verified,
            "generated_answer_is_source_truth": self.generated_answer_is_source_truth,
        }


class AnswerProvider(Protocol):
    metadata: ProviderMetadata

    def generate(
        self, question: str, evidence: Sequence[EvidenceBundle]
    ) -> AnswerDraft: ...


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence_id(
    law_revision_id: str,
    source_xml_sha256: str,
    chunk_id: str,
    node_ids: Sequence[str],
) -> str:
    payload = "\x1f".join((
        CONTRACT_VERSION,
        law_revision_id,
        source_xml_sha256.lower(),
        chunk_id,
        *node_ids,
    ))
    return _sha256_text(payload)


def _assert_retrieval_ready(result: Any) -> None:
    if result.status != "ok":
        raise ValueError(f"retrieval result is not answerable: {result.status}")
    resolution = result.resolution
    if resolution.status != "resolved":
        raise ValueError("temporal resolution must be resolved")
    if resolution.content_status != "available":
        raise ValueError("resolved revision content must be available")
    if not result.contexts:
        raise ValueError("retrieval result contains no contexts")


def _fetch_source_nodes(conn: Any, context: Any) -> tuple[SourceNodeEvidence, ...]:
    orders = tuple(int(value) for value in context.source_document_orders)
    if not orders:
        raise AssertionError("context contains no source_document_orders")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n.document_order, encode(n.node_id, 'hex'),
                   legal_kb.provision_node_xml_path(n.document_pk, n.document_order),
                   n.tag_name, n.structural_num, n.display_label, n.text_original,
                   d.law_revision_id, d.source_xml_sha256
            FROM legal_kb.provision_node n
            JOIN legal_kb.law_document d ON d.document_pk=n.document_pk
            WHERE n.document_pk=%s AND n.document_order = ANY(%s)
            """,
            (context.document_pk, list(orders)),
        )
        rows = cur.fetchall()
    by_order = {int(row[0]): row for row in rows}
    if set(by_order) != set(orders):
        raise AssertionError("source node provenance is incomplete")
    output: list[SourceNodeEvidence] = []
    for order in orders:
        row = by_order[order]
        if row[7] != context.law_revision_id:
            raise AssertionError("source node leaked across law_revision_id")
        if str(row[8]).lower() != context.source_xml_sha256.lower():
            raise AssertionError("source node SHA differs from retrieval context")
        if not row[2]:
            raise AssertionError("source node XML path is missing")
        output.append(SourceNodeEvidence(
            document_order=order,
            node_id_hex=str(row[1]),
            xml_path=str(row[2]),
            tag_name=row[3],
            structural_num=row[4],
            display_label=row[5],
            text_original=row[6],
        ))
    return tuple(output)


def build_evidence_bundles(conn: Any, retrieval_result: Any) -> tuple[EvidenceBundle, ...]:
    _assert_retrieval_ready(retrieval_result)
    resolution = retrieval_result.resolution
    bundles: list[EvidenceBundle] = []
    for context in retrieval_result.contexts:
        if context.law_id != resolution.law_id:
            raise AssertionError("context law_id differs from temporal selection")
        if context.law_revision_id != resolution.selected_revision_id:
            raise AssertionError("context revision differs from temporal selection")
        if context.document_pk != resolution.selected_document_pk:
            raise AssertionError("context document differs from temporal selection")
        if context.source_xml_sha256.lower() != resolution.source_xml_sha256.lower():
            raise AssertionError("context source SHA differs from temporal selection")
        nodes = _fetch_source_nodes(conn, context)
        evidence_id = _evidence_id(
            context.law_revision_id,
            context.source_xml_sha256,
            context.chunk_id,
            [node.node_id_hex for node in nodes],
        )
        bundles.append(EvidenceBundle(
            evidence_id=evidence_id,
            retrieval_rank=context.retrieval_rank,
            chunk_id=context.chunk_id,
            law_id=context.law_id,
            law_revision_id=context.law_revision_id,
            document_pk=context.document_pk,
            source_xml_sha256=context.source_xml_sha256.lower(),
            source_nodes=nodes,
        ))
    return tuple(bundles)


def validate_answer_draft(
    draft: AnswerDraft,
    evidence: Sequence[EvidenceBundle],
) -> tuple[str, ...]:
    errors: list[str] = []
    if not draft.answer_text.strip():
        errors.append("ANSWER_TEXT_EMPTY")
    if not draft.claims:
        errors.append("NO_CLAIMS")
    evidence_ids = {item.evidence_id for item in evidence}
    seen_claim_ids: set[str] = set()
    for claim in draft.claims:
        if not claim.claim_id.strip():
            errors.append("CLAIM_ID_EMPTY")
        elif claim.claim_id in seen_claim_ids:
            errors.append(f"DUPLICATE_CLAIM_ID:{claim.claim_id}")
        seen_claim_ids.add(claim.claim_id)
        if not claim.text.strip():
            errors.append(f"CLAIM_TEXT_EMPTY:{claim.claim_id}")
        if not claim.evidence_ids:
            errors.append(f"CLAIM_WITHOUT_EVIDENCE:{claim.claim_id}")
            continue
        if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
            errors.append(f"DUPLICATE_EVIDENCE_REFERENCE:{claim.claim_id}")
        for evidence_id in claim.evidence_ids:
            if evidence_id not in evidence_ids:
                errors.append(f"UNKNOWN_EVIDENCE_ID:{claim.claim_id}:{evidence_id}")
    return tuple(errors)


def finalize_answer(
    draft: AnswerDraft,
    evidence: Sequence[EvidenceBundle],
    *,
    provider: ProviderMetadata | None = None,
) -> RagAnswerEnvelope:
    if provider is not None:
        provider.validate()
    errors = validate_answer_draft(draft, evidence)
    if errors:
        return RagAnswerEnvelope(
            status="blocked",
            answer_text=draft.answer_text,
            claims=draft.claims,
            evidence=tuple(evidence),
            warnings=errors,
            provider=provider,
            citation_ready=False,
        )
    return RagAnswerEnvelope(
        status="citation-ready",
        answer_text=draft.answer_text,
        claims=draft.claims,
        evidence=tuple(evidence),
        warnings=("SEMANTIC_ENTAILMENT_NOT_MACHINE_VERIFIED",),
        provider=provider,
        citation_ready=True,
    )


class DeterministicTestAnswerProvider:
    """CI-only provider used to validate the answer contract boundary."""

    metadata = ProviderMetadata(
        provider="deterministic-test",
        model="evidence-first-node",
        model_version="1",
    )

    def generate(
        self, question: str, evidence: Sequence[EvidenceBundle]
    ) -> AnswerDraft:
        if not question.strip():
            raise ValueError("question must not be blank")
        if not evidence:
            raise ValueError("evidence must not be empty")
        first = evidence[0]
        source_text = next(
            (node.text_original.strip() for node in first.source_nodes
             if node.text_original and node.text_original.strip()),
            "根拠原文は構造参照のみです。",
        )
        claim_text = source_text[:240]
        return AnswerDraft(
            answer_text=claim_text,
            claims=(AnswerClaim(
                claim_id="claim-1",
                text=claim_text,
                evidence_ids=(first.evidence_id,),
            ),),
        )


def generate_and_finalize(
    provider: AnswerProvider,
    question: str,
    evidence: Sequence[EvidenceBundle],
) -> RagAnswerEnvelope:
    provider.metadata.validate()
    draft = provider.generate(question, evidence)
    return finalize_answer(draft, evidence, provider=provider.metadata)
