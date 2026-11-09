"""Clause and declaration checks over the document's own text (design D17).

`contains_clause` in the DSL acts on a *field's value*; a required or controlled clause is document-level
evidence, so it is checked here against the same normalization the provenance check uses
(`normalized_full_texts()`).

Three kinds stay apart (AUD-08): presence, exact text, and semantic equivalence. The third is **not judged**
in this build — it reports `unable_to_assess` with `semantic_equivalence_not_implemented`, because matching
keywords and calling it "equivalent" is the failure this rule exists to prevent.
"""

from __future__ import annotations

from app.parsing.normalize import normalized_full_texts, normalize_ws
from app.rules.engine import HARD_BLOCK_OPERATIONS
from app.rules.templates import ClauseRequirement, DeclarationRequirement, TemplatePack
from app.rules.types import (
    FAILED,
    FINDING,
    NOT_APPLICABLE,
    PASS,
    UNABLE_TO_ASSESS,
    CheckResult,
    RuleEvaluationError,
    Unit,
)

SEMANTIC_NOT_IMPLEMENTED = "semantic_equivalence_not_implemented"
CLAUSE_NOT_FOUND = "clause_not_found"
CONTROLLED_TEXT_DIFFERS = "controlled_text_differs"
OPTIONAL_CLAUSE_ABSENT = "optional_clause_absent"
DECLARATION_MISSING = "declaration_missing"
NO_DOCUMENT_TEXT = "no_document_text"

_EXCERPT = 80


def check_id(template: TemplatePack, kind: str, item_id: str) -> str:
    """`TEMPLATE:<template_id>:<kind>:<id>` — stable, unique, and parseable back to its source."""
    return f"TEMPLATE:{template.template_id}:{kind}:{item_id}"


def _corpus(state: dict) -> str | None:
    """Every document's normalized text, joined; `None` when there is nothing to search."""
    normalized = normalized_full_texts(state.get("docs") or [])
    if not normalized:
        return None
    return "\n".join(normalized.values())


def _excerpt(text: str) -> str:
    flat = normalize_ws(text)
    return flat if len(flat) <= _EXCERPT else f"{flat[:_EXCERPT]}…"


def _finding(
    template: TemplatePack,
    *,
    rule_id: str,
    title: str,
    severity: str,
    gate_type: str,
    category: str,
    evidence: str | None,
) -> dict:
    return {
        "rule_ref": {"rule_id": rule_id, "version": template.version},
        "title": title,
        "severity": severity,
        "gate_type": gate_type,
        "target_operations": list(HARD_BLOCK_OPERATIONS) if gate_type == "hard_block" else [],
        "category": category,
        "field_id": None,  # document-level: the anchor is the clause id named in the title
        "evidence": evidence,
        "template_id": template.template_id,
    }


def evaluate_clause_unit(
    unit: Unit, clause: ClauseRequirement, template: TemplatePack, state: dict
) -> CheckResult:
    """One clause: present, verbatim, optional, or "needs a model we do not have"."""
    if clause.requirement == "semantic_equivalent":
        # Never `pass`, never a finding: the report says who has to look at it instead.
        return CheckResult(
            unit.check_id,
            UNABLE_TO_ASSESS,
            reason_code=SEMANTIC_NOT_IMPLEMENTED,
            detail={"clause_id": clause.clause_id},
        )

    corpus = _corpus(state)
    if corpus is None:
        return CheckResult(unit.check_id, UNABLE_TO_ASSESS, reason_code=NO_DOCUMENT_TEXT)

    if normalize_ws(clause.text) in corpus:
        return CheckResult(unit.check_id, PASS, detail={"clause_id": clause.clause_id})

    if clause.requirement == "optional":
        return CheckResult(
            unit.check_id,
            NOT_APPLICABLE,
            reason_code=OPTIONAL_CLAUSE_ABSENT,
            detail={"clause_id": clause.clause_id},
        )

    required = clause.requirement == "required"
    title = (
        f"Required clause {clause.clause_id} is missing"
        if required
        else f"Controlled clause {clause.clause_id} does not match its controlled text"
    )
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(
            template,
            rule_id=f"TEMPLATE:{template.template_id}:{clause.clause_id}",
            title=title,
            severity=clause.severity,
            gate_type=clause.gate_type,
            category="template",
            evidence=_excerpt(clause.text),
        ),
        detail={
            "reason": CLAUSE_NOT_FOUND if required else CONTROLLED_TEXT_DIFFERS,
            "clause_id": clause.clause_id,
        },
    )


def evaluate_declaration_unit(
    unit: Unit, declaration: DeclarationRequirement, template: TemplatePack, state: dict
) -> CheckResult:
    """An internal-policy declaration: present or not. Never "the funds are lawful" (AUD-11)."""
    corpus = _corpus(state)
    if corpus is None:
        return CheckResult(unit.check_id, UNABLE_TO_ASSESS, reason_code=NO_DOCUMENT_TEXT)

    if normalize_ws(declaration.text) in corpus:
        return CheckResult(unit.check_id, PASS, detail={"declaration_id": declaration.declaration_id})

    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(
            template,
            rule_id=f"TEMPLATE:{template.template_id}:{declaration.declaration_id}",
            title=f"Declaration {declaration.declaration_id} is missing",
            severity=declaration.severity,
            gate_type=declaration.gate_type,
            category="internal_policy",
            evidence=_excerpt(declaration.text),
        ),
        detail={
            "reason": DECLARATION_MISSING,
            "declaration_id": declaration.declaration_id,
            "waivable": declaration.waivable,
        },
    )


def evaluate_all(units: list[Unit], template: TemplatePack, state: dict) -> list[CheckResult]:
    """Evaluate every clause/declaration unit from the plan, isolating a crashing checker."""
    clauses = {clause.clause_id: clause for clause in template.clauses}
    declarations = {declaration.declaration_id: declaration for declaration in template.declarations}
    results: list[CheckResult] = []
    for unit in units:
        _, _, kind, item_id = unit.check_id.split(":", 3)
        try:
            if kind == "clause" and item_id in clauses:
                results.append(evaluate_clause_unit(unit, clauses[item_id], template, state))
            elif kind == "declaration" and item_id in declarations:
                results.append(
                    evaluate_declaration_unit(unit, declarations[item_id], template, state)
                )
            else:
                results.append(
                    CheckResult(unit.check_id, FAILED, reason_code="unknown_template_unit")
                )
        except RuleEvaluationError as exc:
            results.append(CheckResult(unit.check_id, FAILED, reason_code=str(exc)))
        except Exception as exc:  # a crashing checker must not take the audit down
            results.append(
                CheckResult(
                    unit.check_id, FAILED, reason_code=f"checker_crashed: {type(exc).__name__}"
                )
            )
    return results