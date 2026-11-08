"""State contract. Field-by-field aligned with `openspec/changes/poc-skeleton/design.md` §4.

[FROZEN] Sub-structures may only grow, never change; new fields must be optional (`NotRequired`);
changing semantics equals changing the contract: three-person sign-off plus a rerun of
`tests/test_contracts.py`.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, NotRequired, TypedDict

# --------------------------------------------------------------------------
# §4.1 Enum constants (use the constants at runtime; never hand-write the strings)
# --------------------------------------------------------------------------

AGENT_IDS = ("agent1", "agent2", "agent3", "agent4")
STAGE_STATUS = ("done", "skipped", "partial", "failed")
FINDING_SOURCES = ("normalization", "business", "regulatory")
FINDING_KINDS = (
    "missing",
    "not_found",
    "invalid_value",
    "inconsistent",
    "policy_violation",
    "regulatory_risk",
    "trail_violation",
)
SEVERITIES = ("critical", "warn", "info")
TRAIL_OPS = (
    "read",
    "llm_call",
    "transform",
    "emit",
    "pass",
    "summarize",
    "rewrite",
    "drop",
)
OVERREACH_OPS = frozenset({"summarize", "rewrite", "drop"})  # overreach signal
FINDING_PREFIX = {"normalization": "N", "business": "B", "regulatory": "R"}
# Attribution agent for the shared stages (parse/extract/normalize).
# StageReport.agent only allows agent1..4, and these three stages are not agents,
# so they are all attributed to SHARED_STAGE_OWNER — that is what makes a replay unambiguous.
SHARED_STAGE_OWNER = "agent1"


# --------------------------------------------------------------------------
# §4.2 Parse output
# --------------------------------------------------------------------------


class ParsedBlock(TypedDict):
    file_id: str
    page: int | None
    bbox: list[float] | None  # [x0, y0, x1, y1]; None for plain text
    text: str  # source text, never rewritten
    kind: Literal["paragraph", "table_cell", "header", "footer"]


class ParsedDoc(TypedDict):
    file_id: str
    filename: str
    mime: str
    # [SEMANTICS] `docx_text` / `image_ocr` added by `document-import` (4 Nov 2026): the form is what
    # tells a reader whether the text was *read* or *recognised*. Existing values are unchanged.
    form: Literal["pdf_text", "pdf_form", "email", "plain_text", "docx_text", "image_ocr"]
    blocks: list[ParsedBlock]
    full_text: str  # blocks concatenated in order, consumed directly by Agent 3
    errors: list[str]  # parse failure reasons; when non-empty this file takes no further part
    sha256: NotRequired[str | None]  # [SEMANTICS] used for the docs reuse check


# --------------------------------------------------------------------------
# §4.3 Provenance and field values
# --------------------------------------------------------------------------


class Source(TypedDict):
    file_id: str
    page: int | None
    bbox: list[float] | None
    span: str  # [SEMANTICS] smallest locatable fragment, without labels like "Applicant:"
    form_label: str | None  # form field name; always None for free text (the POC has no form path)


class FieldValue(TypedDict):
    key: str  # from fields.yaml
    value: str | None  # [SEMANTICS] normalized value; case and spelling as in the source
    status: Literal["extracted", "inferred", "missing"]
    confirmed: bool  # whether a human confirmed it in the review console
    edited_by_user: bool  # whether a human edited the value
    source: Source | None
    normalized_from: str | None  # raw value before normalization, preserved verbatim
    label: str | None  # the field's original label in the source
    doc_type: str | None  # invoice / contract / bl / application_form …
    notes: list[str]  # ambiguity / truncation notes, e.g. "date_ambiguous" ([] when none)


# --------------------------------------------------------------------------
# §4.4 Review conclusions
# --------------------------------------------------------------------------


class Finding(TypedDict):
    id: str  # N-001 / B-001 / R-001 (incremented inside each agent's namespace)
    source: Literal["normalization", "business", "regulatory"]
    kind: Literal[
        "missing",
        "not_found",
        "invalid_value",
        "inconsistent",
        "policy_violation",
        "regulatory_risk",
        "trail_violation",
    ]
    rule_id: str
    severity: Literal["critical", "warn", "info"]
    blocking: bool  # declared by requirements.yaml rules, never derived from severity
    resolved: bool  # always False on creation; only hitl may change it
    resolution: str | None  # always None on creation
    field_keys: list[str]  # [SEMANTICS] empty list when no field is involved, never None
    message: str
    evidence: str | None  # must be a source fragment or a field value, never a vague statement
    citation: str | None  # chunk_id, regulatory only
    suggestion: str | None
    confidence: NotRequired[float]  # down-weighted on conflicting judgements; display/ranking only, never blocking
    needs_review: NotRequired[bool]  # entries a human should glance at, e.g. conflicting double checks


# --------------------------------------------------------------------------
# §4.5 Agent 3 output
# --------------------------------------------------------------------------


class Claim(TypedDict):
    text: str
    chunk_id: str | None  # None = insufficient support
    kind: Literal["applicable_rule", "risk", "condition"]
    support: Literal["supported", "insufficient"]


class ApplicableRule(TypedDict):
    rule_id: str
    title: str
    version: str
    effective_from: str | None
    chunk_id: str


class LegalOpinion(TypedDict):
    input_mode: Literal["enriched", "raw"]  # raw = extract never ran, so downstream must not run conflict_check
    applicable_rules: list[ApplicableRule]
    claims: list[Claim]
    coverage: dict  # {jurisdictions, standards, unavailable,
    #  business_type_uncertain, notes}
    escalate_to_human: bool
    summary: str


# --------------------------------------------------------------------------
# §4.6 Stage reports and operation log
# --------------------------------------------------------------------------


class StageReport(TypedDict):
    stage: str  # "parse" / "agent2.check_rules" / "gate" …
    agent: Literal["agent1", "agent2", "agent3", "agent4"]  # shared stages use SHARED_STAGE_OWNER
    status: Literal["done", "skipped", "partial", "failed"]
    reason: str | None  # required for skipped/failed/partial
    produced: int  # number of items produced in this run
    model_calls: int


# [SEMANTICS] produced=0 and status="done"  = checked, nothing found
#            produced=0 and status!="done" = not checked (downstream must not read this as "no issues")


class TrailEntry(TypedDict):
    id: str  # "agent1.extract#003", incremented per agent to avoid parallel collisions
    agent: Literal["agent1", "agent2", "agent3", "agent4"]
    stage: str
    op: Literal[
        "read", "llm_call", "transform", "emit", "pass", "summarize", "rewrite", "drop"
    ]  # the last three are overreach signals
    before: str | None  # source fragment
    after: str | None  # produced value
    ref: str | None  # "file_id/page/span", or the id of the previous entry
    model: str | None
    prompt_hash: str | None
    detail: dict


# `stages` is append-only; read the last report for a stage (`latest_stage()`).
# A rerun leaves several reports for one stage, and "the second run failed after the user changed a
# field" has to be visible in the replay.


# --------------------------------------------------------------------------
# §4.7 Agent 4 output
# --------------------------------------------------------------------------


class Issue(TypedDict):
    checker: str
    level: Literal["fail", "warn", "info"]
    finding_ids: list[str]
    detail: str
    location: str | None  # field key / chunk_id / trail entry id
    # [SEMANTICS] agent-audit additions (design D3, signed off 2026-11-08). All optional, so an
    # existing producer of `Issue` keeps working unchanged.
    check_id: NotRequired[str]  # which planned unit this row reports
    gate_type: NotRequired[str]  # advisory / human_review / hard_block — severity never implies it
    target_operations: NotRequired[list[str]]  # operations this row gates, when it gates any
    method: NotRequired[str]  # deterministic / semantic


class VerificationReport(TypedDict):
    checks: list[Issue]
    verdict: Literal["pass", "warn", "fail"]
    credibility: dict  # fully recomputable; see app/audit/project.py::credibility
    score: float | None  # display only; MUST NOT feed any verdict or rerun
    # [SEMANTICS] agent-audit addition (design D3, signed off 2026-11-08): the audit report baseline
    # (snapshot digest, schema/bundle/engine versions, counts, coverage, outcome, findings).
    audit: NotRequired[dict]


# --------------------------------------------------------------------------
# §4.8 Input and retrieval
# --------------------------------------------------------------------------


class SourceFile(TypedDict):
    file_id: str
    filename: str
    mime: str
    path: str  # local path or object-storage key
    sha256: str  # docs reuse check and de-duplication


class Chunk(TypedDict):
    chunk_id: str
    doc_id: str  # knowledge-base document id (not a business file_id)
    title: str
    text: str
    score: float
    source_type: Literal["kb", "web"]


# --------------------------------------------------------------------------
# §4.9 Main state and temporary channels
# --------------------------------------------------------------------------


class EditState(TypedDict, total=False):
    run_id: str
    files: list[SourceFile]
    business_type: str | None

    docs: list[ParsedDoc]  # overwrite; produced by parse
    fields: dict[str, FieldValue]  # overwrite
    extra_fields: dict[str, FieldValue]  # overwrite; keys not defined in fields.yaml
    _candidates: list[dict]  # [TEMPORARY CHANNEL] written by extract, cleared by normalize
    findings: Annotated[list[Finding], operator.add]  # reducer
    legal: LegalOpinion | None  # overwrite
    retrieved: list[Chunk]  # overwrite

    trail: Annotated[list[TrailEntry], operator.add]  # append
    stages: Annotated[list[StageReport], operator.add]  # append

    verification: VerificationReport | None  # overwrite
    gate: dict | None
    export: dict | None

    recheck: bool
    recheck_count: int
    repair_count: int
    requested_stages: list[str]


# Only `findings` / `trail` / `stages` carry a reducer. `fields` / `legal` and friends always
# overwrite — adding a reducer casually would pile state up inside the `reset` loop.
#
# `_candidates` has three hard rules: (1) only `extract` writes it and `normalize` MUST clear it
# with `Overwrite([])` (otherwise the checkpointer keeps it forever); (2) the UI preview may read it
# but **must not** treat it as `fields`; (3) it is **not part of the contract**, so no agent
# MUST depend on it for a decision.