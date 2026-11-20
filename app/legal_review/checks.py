"""Deterministic document checks: required elements, date consistency, risk markers.

These run before any model call and never depend on one. They are the part of a scan that can say
"this element is missing" or "the expiry date is before the issue date" with a real anchor and no
hallucination risk. Everything semantic (is this clause legally risky?) is the composer's job.

Rules are data: a closed catalogue of regex/date checks, no scripts, no eval.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date

from app.legal_review.contracts import CheckResult, DocumentAnchor, Finding, RuleRef
from app.legal_review.document import Clause, ClausePlan, quote_for

RULE_VERSION = "1"
ELEMENT_CATEGORY = "element"
CONSISTENCY_CATEGORY = "consistency"
CLAUSE_CATEGORY = "clause"
_BLOCK_OPERATIONS = ("start_approval",)
_I = re.IGNORECASE


@dataclass(frozen=True)
class ElementSpec:
    key: str
    label: str
    patterns: tuple[str, ...]
    severity: str
    gate_type: str
    suggestion: str
    operations: tuple[str, ...] = _BLOCK_OPERATIONS


# Presence is checked over the whole draft: an element is document-level evidence, not clause-level.
ELEMENTS: tuple[ElementSpec, ...] = (
    ElementSpec(
        key="amount",
        label="Guarantee / contract amount",
        patterns=(
            r"\b(?:USD|EUR|GBP|CNY|RMB|HKD|JPY|SGD|AUD|CHF)\s?[\d][\d,，.]*",
            r"(?:金额|amount|sum\s+of|guarantee\s+amount|contract\s+value)[^\n]{0,40}?\d",
            r"\d[\d,，.]*\s?(?:美元|欧元|人民币|港元|日元|英镑|元)",
        ),
        severity="Critical",
        gate_type="hard_block",
        suggestion="Add the amount with its currency, e.g. “USD 250,000.00”.",
    ),
    ElementSpec(
        key="currency",
        label="Currency",
        patterns=(
            r"\b(?:USD|EUR|GBP|CNY|RMB|HKD|JPY|SGD|AUD|CHF)\b",
            r"美元|欧元|人民币|港元|港币|日元|英镑",
        ),
        severity="Critical",
        gate_type="hard_block",
        suggestion="State the currency explicitly next to the amount.",
    ),
    ElementSpec(
        key="expiry",
        label="Expiry / validity date",
        patterns=(
            r"(?:失效日(?:期)?|到期日(?:期)?|有效期|截止日(?:期)?|届满)",
            r"(?:expiry|expiration|expiring|valid\s+until|valid\s+through|maturity\s+date)",
        ),
        severity="Critical",
        gate_type="hard_block",
        suggestion="Add an expiry date and, if applicable, the claim period before it.",
    ),
    ElementSpec(
        key="governing_rules",
        label="Governing rules (URDG / UCP / ISP)",
        patterns=(
            r"\b(?:URDG|UCP|ISP|ISBP|URC|URR)\s?\d{2,4}\b",
            r"(?:适用规则|governing\s+rules?|subject\s+to)",
        ),
        severity="Critical",
        gate_type="hard_block",
        suggestion="Name the governing rules and version, e.g. “subject to URDG 758”.",
    ),
    ElementSpec(
        key="applicant",
        label="Applicant / ordering party",
        patterns=(
            r"(?:申请人|委托方|开证申请人)",
            r"\b(?:applicant|principal|ordered\s+by|orderer)\b",
        ),
        severity="Critical",
        gate_type="human_review",
        suggestion="Add the applicant’s full legal name.",
    ),
    ElementSpec(
        key="beneficiary",
        label="Beneficiary",
        patterns=(r"(?:受益人)", r"\b(?:beneficiary|in\s+favou?r\s+of)\b"),
        severity="Critical",
        gate_type="human_review",
        suggestion="Add the beneficiary’s full legal name.",
    ),
    ElementSpec(
        key="issue_date",
        label="Issue date",
        patterns=(
            r"(?:开立日(?:期)?|签发日(?:期)?|出具日(?:期)?)",
            r"\b(?:issue\s+date|date\s+of\s+issue|issued\s+on)\b",
        ),
        severity="Warning",
        gate_type="human_review",
        suggestion="Add the issue date so expiry and claim windows can be checked.",
    ),
    ElementSpec(
        key="jurisdiction",
        label="Jurisdiction / governing law",
        patterns=(
            r"(?:管辖|适用法律|法律适用|争议解决|仲裁)",
            r"\b(?:jurisdiction|governing\s+law|arbitration|forum)\b",
        ),
        severity="Warning",
        gate_type="human_review",
        suggestion="State the governing law and the forum for disputes.",
    ),
    ElementSpec(
        key="claim_documents",
        label="Claim documents",
        patterns=(
            r"(?:索赔|付款要求|索赔单据|提交单据|所需单据)",
            r"\b(?:claim\s+documents?|documents\s+required|demand\s+for\s+payment|"
            r"supporting\s+statement)\b",
        ),
        severity="Warning",
        gate_type="human_review",
        suggestion="List the documents a claim must be accompanied by.",
    ),
)

# A non-guarantee draft (e.g. an export contract) must not be judged against guarantee elements:
# "missing claim documents" on a sale contract is noise, and noise hides the real red flags.
_BY_KEY = {spec.key: spec for spec in ELEMENTS}
CONTRACT_ELEMENTS: tuple[ElementSpec, ...] = (
    _BY_KEY["amount"],
    _BY_KEY["currency"],
    ElementSpec(
        key="parties",
        label="Parties (seller / buyer / supplier)",
        patterns=(
            r"(?:卖方|买方|供应商|采购方|出售方|购买方)",
            r"\b(?:sellers?|buyers?|suppliers?|purchasers?|vendors?|part(?:y|ies)\s+to)\b",
        ),
        severity="Critical",
        gate_type="human_review",
        suggestion="Name the seller and the buyer in full, with their jurisdictions.",
    ),
    _BY_KEY["jurisdiction"],
)

_GUARANTEE_TYPE_RE = re.compile(r"保函|guarantee|standby|见索即付", _I)
_LC_TYPE_RE = re.compile(r"信用证|letter\s+of\s+credit|\bUCP\s?\d{3}\b|\bISP\s?98\b", _I)
_CONTRACT_TYPE_RE = re.compile(r"合同|协议|agreement|contract", _I)


def detect_document_type(text: str) -> str:
    """A deliberately small heuristic: it only decides which element catalogue applies."""
    body = text or ""
    if _LC_TYPE_RE.search(body):
        return "lc"
    if _GUARANTEE_TYPE_RE.search(body):
        return "guarantee"
    if _CONTRACT_TYPE_RE.search(body):
        return "contract"
    return "unknown"


@dataclass(frozen=True)
class MarkerSpec:
    key: str
    label: str
    pattern: str
    suggestion: str


# Lexical risk markers. They are **not** legal conclusions: each one opens a human-review finding
# that says "this wording is worth checking", with the exact sentence it matched.
MARKERS: tuple[MarkerSpec, ...] = (
    MarkerSpec(
        key="automatic_extension",
        label="Automatic extension",
        pattern=r"自动展期|自动延期|automatically\s+extend(?:ed|s|ing)?",
        suggestion="Confirm the extension mechanism, notice period and the beneficiary’s consent.",
    ),
    MarkerSpec(
        key="unconditional_payment",
        label="Unconditional payment wording",
        pattern=r"无条件(?:付款|支付|赔付)|unconditional(?:ly)?\s+(?:pay|payment|undertaking)",
        suggestion="Confirm this is intended and that the applicable rules allow it.",
    ),
    MarkerSpec(
        key="sole_discretion",
        label="Sole-discretion wording",
        pattern=(
            r"单方(?:决定|修改|变更|解除)|sole\s+discretion|"
            r"at\s+(?:our|its)\s+(?:sole\s+)?discretion"
        ),
        suggestion="Check whether a unilateral right is acceptable to both parties.",
    ),
    MarkerSpec(
        key="final_interpretation",
        label="Final-interpretation wording",
        pattern=r"最终解释权|final\s+(?:interpretation|say)",
        suggestion="Replace with an agreed dispute-resolution clause.",
    ),
    MarkerSpec(
        key="waiver_of_defences",
        label="Waiver of defences",
        pattern=(
            r"不可撤销地?放弃|waive[sd]?\s+(?:all\s+)?(?:defen[cs]es?|rights?\s+of\s+set-?off)"
        ),
        suggestion="Confirm the waiver is intended and enforceable in the chosen jurisdiction.",
    ),
)

PLACEHOLDER_RE = re.compile(r"\{\{[^}\n]{1,80}\}\}|<<[^>\n]{1,80}>>|\bTBD\b|待填|待定", _I)

_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(20\d{2})/(\d{1,2})/(\d{1,2})\b"), "ymd"),
    (re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"), "ymd"),
    (
        re.compile(
            r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+(20\d{2})\b",
            _I,
        ),
        "dmy_name",
    ),
)
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_ISSUE_LABEL = re.compile(
    r"(?:开立日(?:期)?|签发日(?:期)?|出具日(?:期)?|\bissue\s+date\b|\bdate\s+of\s+issue\b)",
    _I,
)
_EXPIRY_LABEL = re.compile(
    r"(?:失效日(?:期)?|到期日(?:期)?|有效期|截止日(?:期)?|\bexpiry\b|\bexpiration\b|"
    r"\bvalid\s+until\b|\bvalid\s+through\b)",
    _I,
)
# How far after a label we look for its date. Beyond this, the date belongs to another sentence.
_LABEL_WINDOW = 120


def _first_match(text: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    for pattern in patterns:
        found = re.search(pattern, text, _I)
        if found:
            return found
    return None


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(match: re.Match[str], kind: str) -> date | None:
    try:
        if kind == "ymd":
            year, month, day = (int(part) for part in match.groups()[:3])
        else:
            day = int(match.group(1))
            month = _MONTHS.get(match.group(2).lower().rstrip("."))
            year = int(match.group(3))
            if month is None:
                return None
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _date_after_label(text: str, label: re.Pattern[str]) -> tuple[int, int, date] | None:
    """The first unambiguous date within `_LABEL_WINDOW` characters of a label."""
    for labelled in label.finditer(text):
        window = text[labelled.end() : labelled.end() + _LABEL_WINDOW]
        for pattern, kind in _DATE_PATTERNS:
            found = pattern.search(window)
            if not found:
                continue
            parsed = _parse_date(found, kind)
            if parsed is None:
                continue
            start = labelled.end() + found.start()
            return start, labelled.end() + found.end(), parsed
    return None


def anchor_for(
    plan: ClausePlan, clause: Clause | None, start_cp: int, end_cp: int
) -> DocumentAnchor | None:
    """An anchor whose quote is a real substring of the draft, or `None` when it has no block."""
    block = plan.block_at(start_cp)
    if block is None:
        return None
    return DocumentAnchor(
        clause_id=clause.clause_id if clause is not None else "document",
        block_index=int(block.node_id[1:]),
        start_cp=start_cp,
        end_cp=end_cp,
        quote=quote_for(plan, start_cp, end_cp),
    )


def make_finding(
    *,
    check_id: str,
    title: str,
    explanation: str,
    severity: str,
    gate_type: str,
    category: str,
    operations: tuple[str, ...] | list[str],
    rule_id: str,
    suggestion: str | None = None,
    document_anchors: list[DocumentAnchor] | None = None,
    evidence_ids: list[str] | None = None,
    anchors: list[dict] | None = None,
    basis: str = "rule",
    support_level: str = "not_applicable",
    applicability: dict | None = None,
) -> Finding:
    return Finding(
        finding_id=f"lf_{uuid.uuid4().hex[:12]}",
        check_id=check_id,
        method="deterministic" if basis == "rule" else "legal",
        category=category,
        severity=severity,
        gate_type=gate_type,
        target_operations=list(operations),
        title=title,
        explanation=explanation,
        anchors=list(anchors or []),
        document_anchors=list(document_anchors or []),
        suggestion=suggestion,
        basis=basis,
        rule_refs=[RuleRef(rule_id=rule_id, version=RULE_VERSION)],
        evidence_ids=list(evidence_ids or []),
        applicability=applicability
        or {"jurisdictions": [], "assessment_date": date.today().isoformat(), "limitations": []},
        support_level=support_level,
    )


def rule_id_for(key: str) -> str:
    return f"LEGAL-{key.upper().replace('_', '-')}"


def evaluate_elements(
    plan: ClausePlan, *, document_type: str | None = None
) -> list[tuple[CheckResult, Finding | None]]:
    """One unit per element of the applicable catalogue. Missing is a finding, present is a pass."""
    resolved = document_type or detect_document_type(plan.text)
    catalogue = ELEMENTS if resolved in ("guarantee", "lc") else CONTRACT_ELEMENTS
    results: list[tuple[CheckResult, Finding | None]] = []
    for spec in catalogue:
        check_id = f"LEGAL:element:{spec.key}"
        reference = RuleRef(rule_id=rule_id_for(spec.key), version=RULE_VERSION)
        if _first_match(plan.text, spec.patterns) is not None:
            results.append(
                (
                    CheckResult(
                        check_id=check_id,
                        method="deterministic",
                        scope_key="document",
                        status="pass",
                        rule_refs=[reference],
                        reason_codes=["element_present"],
                    ),
                    None,
                )
            )
            continue
        finding = make_finding(
            check_id=check_id,
            title=f"Missing {spec.label.lower()}",
            explanation=(
                f"The draft does not mention {spec.label.lower()}. This is a completeness check on "
                "the text itself; it does not claim the missing element is legally required."
            ),
            severity=spec.severity,
            gate_type=spec.gate_type,
            category=ELEMENT_CATEGORY,
            operations=spec.operations,
            rule_id=reference.rule_id,
            suggestion=spec.suggestion,
            applicability={
                "jurisdictions": [],
                "assessment_date": date.today().isoformat(),
                "limitations": ["A missing element has no text anchor"],
            },
        )
        results.append(
            (
                CheckResult(
                    check_id=check_id,
                    method="deterministic",
                    scope_key="document",
                    status="finding",
                    rule_refs=[reference],
                    reason_codes=["element_missing"],
                    finding_ids=[finding.finding_id],
                ),
                finding,
            )
        )
    return results


def evaluate_consistency(
    plan: ClausePlan, *, applicable_on: str | None = None
) -> list[tuple[CheckResult, Finding | None]]:
    """Date ordering and expiry. Unparsed dates are `needs_input`, never a pass."""
    issue = _date_after_label(plan.text, _ISSUE_LABEL)
    expiry = _date_after_label(plan.text, _EXPIRY_LABEL)
    as_of = _as_date(applicable_on)
    results: list[tuple[CheckResult, Finding | None]] = []

    ordered_id = "LEGAL:consistency:dates_ordered"
    ordered_ref = RuleRef(rule_id="LEGAL-DATES-ORDERED", version=RULE_VERSION)
    if issue is None or expiry is None:
        missing = [
            name
            for name, value in (("issue_date", issue), ("expiry_date", expiry))
            if value is None
        ]
        results.append(
            (
                CheckResult(
                    check_id=ordered_id,
                    method="deterministic",
                    scope_key="document",
                    status="needs_input",
                    rule_refs=[ordered_ref],
                    reason_codes=["date_unparsed"],
                    missing_facts=missing,
                ),
                None,
            )
        )
    elif expiry[2] <= issue[2]:
        anchor = anchor_for(plan, None, expiry[0], expiry[1])
        finding = make_finding(
            check_id=ordered_id,
            title="Expiry date is not after the issue date",
            explanation=(
                f"The issue date is {issue[2].isoformat()} and the expiry date is "
                f"{expiry[2].isoformat()}. An undertaking cannot expire before it is issued."
            ),
            severity="Critical",
            gate_type="hard_block",
            category=CONSISTENCY_CATEGORY,
            operations=_BLOCK_OPERATIONS,
            rule_id=ordered_ref.rule_id,
            suggestion="Correct the issue/expiry dates so expiry is strictly after issue.",
            document_anchors=[anchor] if anchor else [],
        )
        results.append(
            (
                CheckResult(
                    check_id=ordered_id,
                    method="deterministic",
                    scope_key="document",
                    status="finding",
                    rule_refs=[ordered_ref],
                    reason_codes=["dates_out_of_order"],
                    finding_ids=[finding.finding_id],
                ),
                finding,
            )
        )
    else:
        results.append(
            (
                CheckResult(
                    check_id=ordered_id,
                    method="deterministic",
                    scope_key="document",
                    status="pass",
                    rule_refs=[ordered_ref],
                    reason_codes=["dates_ordered"],
                ),
                None,
            )
        )

    expiry_id = "LEGAL:consistency:not_expired"
    expiry_ref = RuleRef(rule_id="LEGAL-NOT-EXPIRED", version=RULE_VERSION)
    if as_of is None:
        results.append(
            (
                CheckResult(
                    check_id=expiry_id,
                    method="deterministic",
                    scope_key="document",
                    status="not_applicable",
                    rule_refs=[expiry_ref],
                    reason_codes=["no_assessment_date"],
                ),
                None,
            )
        )
    elif expiry is None:
        results.append(
            (
                CheckResult(
                    check_id=expiry_id,
                    method="deterministic",
                    scope_key="document",
                    status="needs_input",
                    rule_refs=[expiry_ref],
                    reason_codes=["date_unparsed"],
                    missing_facts=["expiry_date"],
                ),
                None,
            )
        )
    elif expiry[2] < as_of:
        anchor = anchor_for(plan, None, expiry[0], expiry[1])
        finding = make_finding(
            check_id=expiry_id,
            title="The undertaking has already expired",
            explanation=(
                f"The expiry date {expiry[2].isoformat()} is before the assessment date "
                f"{as_of.isoformat()}."
            ),
            severity="Critical",
            gate_type="hard_block",
            category=CONSISTENCY_CATEGORY,
            operations=_BLOCK_OPERATIONS,
            rule_id=expiry_ref.rule_id,
            suggestion="Extend the expiry date or confirm the undertaking is no longer used.",
            document_anchors=[anchor] if anchor else [],
        )
        results.append(
            (
                CheckResult(
                    check_id=expiry_id,
                    method="deterministic",
                    scope_key="document",
                    status="finding",
                    rule_refs=[expiry_ref],
                    reason_codes=["expired_before_assessment"],
                    finding_ids=[finding.finding_id],
                ),
                finding,
            )
        )
    else:
        results.append(
            (
                CheckResult(
                    check_id=expiry_id,
                    method="deterministic",
                    scope_key="document",
                    status="pass",
                    rule_refs=[expiry_ref],
                    reason_codes=["not_expired"],
                ),
                None,
            )
        )
    return results


def clause_marker_keys(text: str) -> list[str]:
    """Which lexical markers a clause carries — also handed to the composer as known rules."""
    return [spec.key for spec in MARKERS if re.search(spec.pattern, text, _I)]


def evaluate_clause_markers(
    plan: ClausePlan, clause: Clause
) -> tuple[CheckResult, list[Finding]]:
    """Lexical risk markers + unresolved placeholders for one clause. No model involved."""
    check_id = f"LEGAL:clause:{clause.clause_id}:presence"
    if not clause.text.strip():
        return (
            CheckResult(
                check_id=check_id,
                method="deterministic",
                scope_key=clause.clause_id,
                clause_id=clause.clause_id,
                status="not_applicable",
                reason_codes=["empty_clause"],
            ),
            [],
        )

    findings: list[Finding] = []
    reasons: list[str] = []
    for spec in MARKERS:
        match = re.search(spec.pattern, clause.text, _I)
        if match is None:
            continue
        start = clause.start_cp + match.start()
        end = clause.start_cp + match.end()
        anchor = anchor_for(plan, clause, start, end)
        findings.append(
            make_finding(
                check_id=check_id,
                title=spec.label,
                explanation=(
                    "The draft contains wording that needs a human check: "
                    f"“{match.group(0)}”. This is a lexical marker, not a legal conclusion."
                ),
                severity="Warning",
                gate_type="human_review",
                category=CLAUSE_CATEGORY,
                operations=(),
                rule_id=rule_id_for(f"marker_{spec.key}"),
                suggestion=spec.suggestion,
                document_anchors=[anchor] if anchor else [],
            )
        )
        reasons.append(f"marker:{spec.key}")

    placeholder = PLACEHOLDER_RE.search(clause.text)
    if placeholder is not None:
        start = clause.start_cp + placeholder.start()
        end = clause.start_cp + placeholder.end()
        anchor = anchor_for(plan, clause, start, end)
        findings.append(
            make_finding(
                check_id=check_id,
                title="Unresolved placeholder",
                explanation=(
                    f"The clause still contains “{placeholder.group(0)}”. A placeholder in a "
                    "submitted version is a data defect, not a drafting style."
                ),
                severity="Warning",
                gate_type="advisory",
                category=CLAUSE_CATEGORY,
                operations=(),
                rule_id="LEGAL-PLACEHOLDER",
                suggestion="Fill or remove the placeholder before submitting.",
                document_anchors=[anchor] if anchor else [],
            )
        )
        reasons.append("placeholder")

    return (
        CheckResult(
            check_id=check_id,
            method="deterministic",
            scope_key=clause.clause_id,
            clause_id=clause.clause_id,
            status="finding" if findings else "pass",
            reason_codes=reasons or ["no_marker"],
            finding_ids=[finding.finding_id for finding in findings],
        ),
        findings,
    )


__all__ = [
    "CLAUSE_CATEGORY",
    "CONSISTENCY_CATEGORY",
    "ELEMENTS",
    "ELEMENT_CATEGORY",
    "MARKERS",
    "PLACEHOLDER_RE",
    "RULE_VERSION",
    "ElementSpec",
    "MarkerSpec",
    "anchor_for",
    "clause_marker_keys",
    "evaluate_clause_markers",
    "evaluate_consistency",
    "evaluate_elements",
    "make_finding",
    "rule_id_for",
]