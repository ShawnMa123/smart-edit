"""`agent3` node: retrieval -> answer -> cite check -> coverage / escalation -> findings.

Hard boundaries (docs/agent3-regulatory-handoff.md §3):
- writes only `legal`, `retrieved`, `source="regulatory"` findings, `stages`, `trail`;
- never writes `business_type` (raw inference stays inside `legal.coverage`);
- an empty retrieval is "not covered", never "no issue";
- a missing index is a `failed` stage, never a completed search.
"""

from __future__ import annotations

import re

from app.findings import materialize_findings
from app.regulatory.answer import Answerer, resolve_answerer
from app.regulatory.cite_check import cite_check
from app.regulatory.query import build_query, infer_business_type
from app.regulatory.retriever import (
    DEFAULT_TOP_K,
    KnowledgeBaseEmpty,
    RetrievalError,
    RetrievalInvalidResponse,
    RetrievalNotConfigured,
    RetrievalUnavailable,
    Retriever,
    resolve_retriever,
    to_chunks,
)
from app.stages import resolve_input_mode, stage_report
from app.trail import record, record_many

AGENT = "agent3"
STAGE = "agent3"

# Deliberately synthetic: the demo must never look like a real sanctions list.
_MOCK_SANCTIONS = ("SANCTIONED DEMO LTD", "DEMO SANCTIONED BANK")
_MOCK_SANCTION_COUNTRIES = ("XX", "ZZ")
_MOCK_LABEL = "演示名单（非真实名单，仅演示）"
_DISCLAIMER = "本结果不构成法律意见，也不替代正式制裁与出口管制筛查。"


def _field(fields: dict, key: str) -> str | None:
    raw = fields.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _full_text(state: dict) -> str:
    return "\n".join(str(doc.get("full_text") or "") for doc in state.get("docs") or [])


def _mode(state: dict) -> str:
    # One implementation lives in `app/stages.py` so "enriched" can never be inferred from
    # `legal is None` (a failed legal call also leaves it None).
    return resolve_input_mode(state)


def _mock_hits(state: dict) -> list[str]:
    fields = state.get("fields") or {}
    values = [
        _field(fields, key)
        for key in ("applicant", "beneficiary", "counterparty", "applicant_country", "beneficiary_country")
    ]
    parts = [value for value in values if value]
    # Raw mode has no reliable field table: the body itself is the input, so it must be screened
    # too. Missing a name because it only appears in the text is the unsafe direction.
    body = _full_text(state)
    if body:
        parts.append(body)
    text = "\n".join(parts)
    hits: list[str] = []
    lowered = text.casefold()
    for name in _MOCK_SANCTIONS:
        if name.casefold() in lowered:
            hits.append(name)
    for code in _MOCK_SANCTION_COUNTRIES:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", text):
            hits.append(code)
    return hits


def _draft(
    *,
    rule_id: str,
    severity: str,
    message: str,
    evidence: str | None,
    citation: str | None = None,
) -> dict:
    return {
        "source": "regulatory",
        "kind": "regulatory_risk",
        "rule_id": rule_id,
        "severity": severity,
        "blocking": False,
        "resolved": False,
        "resolution": None,
        "field_keys": [],
        "message": message,
        "evidence": evidence,
        "citation": citation,
        "suggestion": "人工复核；本结果不构成法律意见，也不替代正式制裁与出口管制筛查",
    }


def _empty_legal(
    *,
    mode: str,
    summary: str,
    corpus: dict | None = None,
    business_type_uncertain: bool = False,
) -> dict:
    return {
        "input_mode": mode,
        "applicable_rules": [],
        "claims": [],
        "coverage": {
            "jurisdictions": [],
            "standards": [],
            "unavailable": True,
            "business_type_uncertain": business_type_uncertain,
            "notes": [],
            "corpus": corpus
            or {"version": None, "documents": None, "jurisdictions": [], "built_at": None},
        },
        "escalate_to_human": True,
        "summary": summary,
    }


def _failed(
    state: dict,
    *,
    reason: str,
    mode: str,
    queries: list[str] | None = None,
    filters: dict | None = None,
    corpus: dict | None = None,
) -> dict:
    summary = f"法规建议未覆盖：法规检索失败（{reason}），需人工复核。"
    legal = _empty_legal(
        mode=mode,
        summary=summary,
        corpus=corpus,
        business_type_uncertain=mode == "raw"
        and not (state.get("business_type") or infer_business_type(state)),
    )
    legal["coverage"]["notes"] = [reason]
    drafts = [
        _draft(
            rule_id="REG-RETRIEVAL",
            severity="warn",
            message=f"法规检索失败：{reason}",
            evidence=summary,
        )
    ]
    receipt = record(
        state,
        agent=AGENT,
        stage=STAGE,
        op="pass",
        after=f"failed:{reason}",
        detail={"reason": reason, "queries": queries or [], "filters": filters or {}},
    )
    after_receipt = {**state, "trail": [*(state.get("trail") or []), *receipt["trail"]]}
    materialized = materialize_findings(after_receipt, drafts, agent=AGENT, stage=STAGE)
    receipts = record_many(
        after_receipt, agent=AGENT, stage=STAGE, entries=materialized["trail"]
    )
    return {
        "legal": legal,
        "retrieved": [],
        "findings": materialized["findings"],
        "stages": [
            stage_report(
                STAGE,
                status="failed",
                reason=reason,
                produced=len(materialized["findings"]),
                model_calls=0,
                agent=AGENT,
            )
        ],
        "trail": [*receipt["trail"], *receipts["trail"]],
    }


def _retrieval_reason(exc: Exception) -> str:
    if isinstance(exc, RetrievalNotConfigured):
        return "retrieval_not_configured"
    if isinstance(exc, KnowledgeBaseEmpty):
        return "knowledge_base_empty"
    if isinstance(exc, RetrievalInvalidResponse):
        return f"retrieval_invalid_response: {exc}"
    if isinstance(exc, RetrievalUnavailable):
        return f"retrieval_unavailable: {exc}"
    if isinstance(exc, RetrievalError):
        return f"retrieval_error: {exc}"
    return f"retrieval_error: {type(exc).__name__}: {exc}"


def _structural_drafts(
    *,
    legal: dict,
    filters: dict,
    corpus: dict,
    mock_hits: list[str],
    body: str = "",
) -> list[dict]:
    coverage = legal["coverage"]
    summary = legal["summary"]
    # Evidence must point at the source, never at generated prose. The body fragment is the only
    # traceable evidence in raw mode; the summary is a fallback for runs with no document text.
    evidence = (body.strip()[:200] or summary)
    drafts: list[dict] = []

    if coverage.get("unavailable"):
        drafts.append(
            _draft(
                rule_id="REG-COVERAGE",
                severity="warn",
                message="法规建议未覆盖：本次检索未返回可引用条文，需人工复核",
                evidence=evidence,
            )
        )
    if coverage.get("business_type_uncertain"):
        drafts.append(
            _draft(
                rule_id="REG-BUSINESS-TYPE",
                severity="warn",
                message="业务类型无法确定，规则适用范围未确认",
                evidence=evidence,
            )
        )
    if not filters.get("as_of"):
        drafts.append(
            _draft(
                rule_id="REG-TRANSACTION-DATE",
                severity="warn",
                message="未能确定交易日期，按当前有效版本适用",
                evidence=evidence,
            )
        )
    supported = {str(value) for value in (corpus.get("jurisdictions") or [])}
    uncovered = [str(value) for value in filters.get("jurisdictions") or [] if str(value) not in supported]
    for jurisdiction in uncovered:
        drafts.append(
            _draft(
                rule_id="REG-JURISDICTION",
                severity="warn",
                message=f"本次语料不覆盖 {jurisdiction} 法域，相关规则未检索",
                evidence=evidence,
            )
        )
    for hit in mock_hits:
        drafts.append(
            _draft(
                rule_id="REG-MOCK-SANCTIONS",
                severity="critical",
                message=f"交易对手/国别疑似命中{_MOCK_LABEL}：{hit}，需人工复核",
                evidence=hit,
            )
        )
    # A supported risk/condition claim is a finding with a citation; an `applicable_rule` claim is
    # evidence for the table, not a separate finding (handoff §6.7).
    for claim in legal.get("claims") or []:
        if claim.get("support") != "supported" or claim.get("kind") not in {"risk", "condition"}:
            continue
        text = str(claim.get("text") or "").strip()
        citation = claim.get("chunk_id")
        if not text or not citation:
            continue
        drafts.append(
            _draft(
                rule_id=f"REG-{str(claim.get('kind')).upper()}",
                severity="warn",
                message=text[:400],
                evidence=text,
                citation=str(citation),
            )
        )
    return drafts


def regulatory_node(
    state: dict,
    *,
    retriever: Retriever | None = None,
    answerer: Answerer | None = None,
) -> dict:
    docs = state.get("docs") or []
    mode = _mode(state)

    if not docs:
        return {
            "stages": [
                stage_report(
                    STAGE,
                    status="failed",
                    reason="missing docs",
                    model_calls=0,
                    agent=AGENT,
                )
            ],
            **record(
                state,
                agent=AGENT,
                stage=STAGE,
                op="pass",
                detail={"reason": "no docs, nothing retrieved"},
            ),
        }

    queries, filters = build_query(state, mode)
    retriever = retriever or resolve_retriever()
    if retriever is None:
        return _failed(
            state, reason="retrieval_not_configured", mode=mode, queries=queries, filters=filters
        )

    try:
        payload = retriever.retrieve(queries, filters, top_k=DEFAULT_TOP_K)
        corpus = payload["corpus"]
        retrieved = to_chunks(payload.get("chunks") or [])
    except Exception as exc:  # a broken service must become a stage report, not a lost run
        return _failed(
            state,
            reason=_retrieval_reason(exc),
            mode=mode,
            queries=queries,
            filters=filters,
        )

    answerer = answerer or resolve_answerer()
    result = answerer.answer(state=state, mode=mode, retrieved=retrieved, corpus=corpus)
    legal = result.legal
    claims, cite_trail = cite_check(legal.get("claims") or [], retrieved)
    legal["claims"] = claims

    coverage = legal["coverage"]
    notes = list(coverage.get("notes") or [])
    uncovered = [
        str(value)
        for value in filters.get("jurisdictions") or []
        if str(value) not in {str(item) for item in (corpus.get("jurisdictions") or [])}
    ]
    for jurisdiction in uncovered:
        notes.append(f"无 {jurisdiction} 法域语料")
    if not filters.get("as_of"):
        notes.append("未能确定交易日期，按当前有效版本适用")
    if not retrieved:
        notes.append("覆盖不可推断：本次检索没有可引用条文")
    if retrieved and not claims:
        notes.append("检索命中但未产出可引用 claim，需人工复核")
    if any(claim.get("support") == "insufficient" for claim in claims):
        notes.append("存在依据不足的 claim，需人工复核")
    # Deduplicate while preserving order.
    coverage["notes"] = list(dict.fromkeys(notes))

    mock_hits = _mock_hits(state)
    escalate = bool(
        coverage.get("unavailable")
        or coverage.get("business_type_uncertain")
        or not filters.get("as_of")
        or uncovered
        or mock_hits
        or (retrieved and not claims)
        or any(claim.get("support") == "insufficient" for claim in claims)
    )
    legal["escalate_to_human"] = escalate
    if _DISCLAIMER not in str(legal.get("summary") or ""):
        legal["summary"] = f"{str(legal.get('summary') or '').strip()} {_DISCLAIMER}".strip()

    drafts = _structural_drafts(
        legal=legal,
        filters=filters,
        corpus=corpus,
        mock_hits=mock_hits,
        body=_full_text(state),
    )

    receipt = record(
        state,
        agent=AGENT,
        stage=STAGE,
        op="read",
        after=f"{len(retrieved)} chunk(s)",
        detail={
            "queries": queries,
            "filters": filters,
            "top_k": DEFAULT_TOP_K,
            "input_mode": mode,
            "inferred_business_type": infer_business_type(state),
            "corpus": {
                "version": corpus.get("version"),
                "documents": corpus.get("documents"),
                "jurisdictions": list(corpus.get("jurisdictions") or []),
            },
            "retriever": type(retriever).__name__,
        },
    )
    after_receipt = {**state, "trail": [*(state.get("trail") or []), *receipt["trail"]]}
    materialized = materialize_findings(after_receipt, drafts, agent=AGENT, stage=STAGE)
    receipts = record_many(
        after_receipt,
        agent=AGENT,
        stage=STAGE,
        entries=[*materialized["trail"], *result.trail_entries, *cite_trail],
    )

    if retrieved and claims and all(claim.get("support") == "insufficient" for claim in claims):
        status = "partial"
        reason = "all claims lack sufficient support after cite_check"
    else:
        status = "done"
        reason = None

    return {
        "legal": legal,
        "retrieved": retrieved,
        "findings": materialized["findings"],
        "stages": [
            stage_report(
                STAGE,
                status=status,
                reason=reason,
                produced=len(claims) + len(materialized["findings"]),
                model_calls=result.model_calls,
                agent=AGENT,
            )
        ],
        "trail": [*receipt["trail"], *receipts["trail"]],
    }


__all__ = ["regulatory_node"]
