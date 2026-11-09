"""Template resolution and policy combination (design D18/D19).

Two questions, both answered without guessing:

1. **Which template applies?** Published packs whose `document_types` contain the run's document type and
   whose counterparty equals the document's. Exactly one is used; zero or several make the template units
   `unable_to_assess` with a reason code — never a guess and never "pick the first".
2. **Does the combined policy agree with itself?** The base template plus every policy pack is one
   `ResolvedPolicy`. Disagreement is reported as a conflict, and a conflict is never settled by load order.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.parsing.normalize import normalize_ws
from app.rules.bundles import RuleBundle, find_conflicts
from app.rules.templates import TemplatePack

NO_TEMPLATE = "no_applicable_template"
AMBIGUOUS = "ambiguous_template"
POLICY_CONFLICT = "policy_conflict"
MISSING_PACK = "missing_policy_pack"
# Template-driven audit is opt-in per run (`design.md` D18): this code means nobody asked for one.
NOT_REQUESTED = "template_not_requested"


@dataclass(frozen=True)
class Resolution:
    """Outcome of template resolution. `template is None` means "say why", never "use nothing"."""

    template: TemplatePack | None
    reason: str | None
    candidates: tuple[dict, ...] = ()
    resolved_from: dict | None = None
    document_type: str | None = None
    reference_ignored: bool = False


@dataclass(frozen=True)
class PolicyPack:
    pack_id: str
    version: str
    owner: str | None
    valid_from: str | None
    valid_to: str | None
    source: str | None


@dataclass(frozen=True)
class ResolvedPolicy:
    packs: tuple[PolicyPack, ...]
    conflicts: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _fold(text: object) -> str:
    """Whitespace / full-width / case insensitive, reusing the layer's one normalization."""
    return normalize_ws(str(text)).casefold()


def counterparty_value(state: dict, field_id: str) -> str | None:
    """Read the counterparty from `fields` or `extra_fields`, whichever holds the key."""
    for bucket in ("fields", "extra_fields"):
        entry = (state.get(bucket) or {}).get(field_id)
        if entry and entry.get("value"):
            return str(entry["value"])
    return None


def _matches(pack: TemplatePack, state: dict, document_type: str | None) -> bool:
    if document_type is not None and document_type not in pack.document_types:
        return False
    if not pack.counterparty_name:
        return True  # a document-type template applies to any counterparty
    value = counterparty_value(state, pack.counterparty_field)
    return bool(value) and _fold(value) == _fold(pack.counterparty_name)


def resolve_template(
    state: dict,
    templates: list[TemplatePack] | tuple[TemplatePack, ...],
    *,
    reference: dict | None = None,
) -> Resolution:
    """Resolve exactly one published template, or say why that is impossible."""
    document_type = state.get("business_type")
    pool = [pack for pack in templates if pack.published]
    reference_ignored = False
    if reference:
        wanted = reference.get("template_id")
        narrowed = [pack for pack in pool if pack.template_id == wanted]
        if narrowed:
            pool = narrowed
        else:
            # A reference may only narrow. Naming something unpublished or unknown is ignored, and the
            # report says so instead of quietly resolving to whatever else matched.
            reference_ignored = True

    candidates = [pack for pack in pool if _matches(pack, state, document_type)]
    listed = tuple({"template_id": pack.template_id, "version": pack.version} for pack in candidates)

    if len(candidates) == 1:
        pack = candidates[0]
        resolved_from = {
            "document_type": document_type,
            "counterparty_field": pack.counterparty_field if pack.counterparty_name else None,
            "counterparty_value": counterparty_value(state, pack.counterparty_field)
            if pack.counterparty_name
            else None,
        }
        return Resolution(
            template=pack,
            reason=None,
            candidates=listed,
            resolved_from=resolved_from,
            document_type=document_type,
            reference_ignored=reference_ignored,
        )

    return Resolution(
        template=None,
        reason=NO_TEMPLATE if not candidates else AMBIGUOUS,
        candidates=listed,
        resolved_from=None,
        document_type=document_type,
        reference_ignored=reference_ignored,
    )


def resolve_policy(
    template: TemplatePack, bundles: list[RuleBundle]
) -> ResolvedPolicy:
    """Combine the template with every policy pack and report disagreements (design D19)."""
    packs = tuple(
        PolicyPack(
            pack_id=bundle.bundle_id,
            version=bundle.version,
            owner=bundle.owner,
            valid_from=bundle.valid_from,
            valid_to=bundle.valid_to,
            source=bundle.source,
        )
        for bundle in bundles
    )
    conflicts = list(find_conflicts(bundles))
    reasons: set[str] = set()

    # 3rd class: the template and a pack disagree about how a field is gated. A pack that already gates
    # the field at the template's level (or at several levels) is not a disagreement; a pack that gates it
    # *only* differently is, and load order never decides which one wins.
    for expectation in template.fields:
        for bundle in bundles:
            pack_levels = {
                rule["gate_type"]
                for rule in bundle.rules
                if rule.get("field_id") == expectation.field_id
            }
            if not pack_levels or expectation.gate_type in pack_levels:
                continue
            conflicts.append(
                f"{expectation.field_id} is gated inconsistently: template "
                f"{template.template_id} says {expectation.gate_type}, {bundle.bundle_id} says "
                f"{'/'.join(sorted(pack_levels))}"
            )
            reasons.add(POLICY_CONFLICT)

    # A mandatory pack that is not loaded cannot be evaluated — say that, never "no applicable checks".
    missing = sorted(set(template.policy_packs) - {bundle.bundle_id for bundle in bundles})
    for pack_id in missing:
        conflicts.append(f"mandatory policy pack {pack_id!r} is missing or unpublished")
        reasons.add(MISSING_PACK)

    if conflicts and not reasons:
        reasons.add(POLICY_CONFLICT)
    return ResolvedPolicy(
        packs=packs, conflicts=tuple(conflicts), reason_codes=tuple(sorted(reasons))
    )


def conflicted_fields(template: TemplatePack, policy: ResolvedPolicy) -> set[str]:
    """Fields whose template expectation is unusable because the policy disagrees about them."""
    fields: set[str] = set()
    for conflict in policy.conflicts:
        for expectation in template.fields:
            if conflict.startswith(f"{expectation.field_id} "):
                fields.add(expectation.field_id)
    return fields


def template_baseline(
    resolution: Resolution, policy: ResolvedPolicy | None, template: TemplatePack | None
) -> dict:
    """The `verification.audit.template` block (design D20).

    Includes the failure path on purpose: "no template applied" must be readable from the report itself,
    with the reason and the candidates that were considered.
    """
    baseline: dict = {
        "requested": resolution.reason != NOT_REQUESTED,
        "template_id": None,
        "version": None,
        "content_sha256": None,
        "synthetic": None,
        "counterparty": None,
        "document_types": [],
        "resolved_from": resolution.resolved_from,
        "policy_packs": [],
        "conflicts": list(policy.conflicts) if policy else [],
        "candidate_templates": list(resolution.candidates),
        "reason": resolution.reason,
        "reason_codes": list(policy.reason_codes) if policy else [],
        "document_type": resolution.document_type,
        "reference_ignored": resolution.reference_ignored,
    }
    if template is not None:
        baseline.update(
            {
                "template_id": template.template_id,
                "version": template.version,
                "content_sha256": template.content_sha256,
                "synthetic": template.synthetic,
                "counterparty": template.counterparty_name,
                "document_types": list(template.document_types),
            }
        )
    if policy is not None:
        baseline["policy_packs"] = [
            {
                "pack_id": pack.pack_id,
                "version": pack.version,
                "owner": pack.owner,
                "valid_from": pack.valid_from,
                "valid_to": pack.valid_to,
                "source": pack.source,
            }
            for pack in policy.packs
        ]
    return baseline