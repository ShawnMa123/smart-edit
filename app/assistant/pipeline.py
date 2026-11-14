"""Deterministic composer + code reviewer (design D8). The fixture only replaces the generator."""

from __future__ import annotations

from typing import Any

from app.assistant.domain.query import QueryPlan
from app.assistant.domain.evidence import claim_supported
from app.assistant.ports import Composition, EvidenceBundle, EvidenceCandidate
from app.assistant.schemas import Answer, Citation, Claim
from app.knowledge.text import normalize, supports_entities

TRADE_LIMITATION = "仅解释已发布来源，不构成法律意见，也不代表交易合法或可开立。"
SYNTHETIC_LIMITATION = "知识来源为合成演示语料（fixture-backed），不是真实法规原文。"
DOCUMENT_LIMITATION = "本回答只解释当前文档快照，不代表已提交、已批准或已审查。"
TRADE_LIMITATION_EN = (
    "This answer only explains published sources; it is not legal advice and does not mean the "
    "transaction is lawful or can be issued."
)
SYNTHETIC_LIMITATION_EN = (
    "The knowledge source is a synthetic demo corpus (fixture-backed), not official legal text."
)
DOCUMENT_LIMITATION_EN = (
    "This answer only explains the current document snapshot; it does not mean the document was "
    "submitted, approved or reviewed."
)


def _english(plan: QueryPlan) -> bool:
    return plan.language == "en"


def _limitation(plan: QueryPlan, zh: str, en: str) -> str:
    return en if _english(plan) else zh


def _citation(candidate: EvidenceCandidate, bundle: EvidenceBundle) -> Citation:
    return Citation(**bundle.citation(candidate))


def _handoff_answer(plan: QueryPlan) -> Answer:
    target = plan.handoff_target or "automation"
    limitation = _limitation(
        plan,
        f"该请求需要转交 {target} 处理；知识助手不会修改正文、发起审批或执行操作。",
        f"This request must be handed off to {target}; the knowledge assistant does not edit the "
        "document, start approvals or perform actions.",
    )
    return Answer(
        outcome="needs_handoff",
        language=plan.language,
        support_level="not_applicable",
        limitations=[limitation],
        handoff_target=target,  # type: ignore[arg-type]
    )


class FixtureComposer:
    """A deterministic answer generator for the A slice; C swaps in an approved model gateway."""

    def compose(self, plan: QueryPlan, bundle: EvidenceBundle, context: dict[str, Any]) -> Composition:
        conflicts = list(context.get("conflicts") or [])
        if plan.handoff_target:
            return Composition(_handoff_answer(plan), {})
        if plan.needs_clarification:
            return Composition(
                Answer(
                    outcome="needs_clarification",
                    language=plan.language,
                    support_level="not_applicable",
                    limitations=[
                        _limitation(
                            plan,
                            "缺少必要信息，暂不能给出有证据的回答。",
                            "Required information is missing, so no evidence-backed answer can be given yet.",
                        )
                    ],
                    clarification_questions=plan.clarification_questions[:3],
                ),
                {},
            )
        if plan.intent == "out_of_scope":
            return Composition(
                Answer(
                    outcome="unable_to_assess",
                    language=plan.language,
                    support_level="insufficient",
                    limitations=[
                        _limitation(
                            plan,
                            "该问题不在知识助手的产品 FAQ、规则解释或文档问答范围内。",
                            "This question is outside the assistant's product FAQ, rule-explanation or document Q&A scope.",
                        )
                    ],
                ),
                {},
            )
        if conflicts:
            explanation = (
                "The published sources conflict, so the assistant cannot choose one automatically."
                if _english(plan)
                else "检索到的已发布来源相互冲突，不能自动选择其一："
                + "；".join(conflict["explanation"] for conflict in conflicts)
            )
            return Composition(
                Answer(
                    outcome="unable_to_assess",
                    language=plan.language,
                    support_level="insufficient",
                    limitations=[explanation],
                ),
                {},
            )
        if not bundle.candidates:
            return Composition(
                Answer(
                    outcome="insufficient_evidence",
                    language=plan.language,
                    support_level="insufficient",
                    limitations=[
                        _limitation(
                            plan,
                            "没有找到足以支持回答的已发布证据；请补充规则版本、法域或选择相关文档片段。",
                            "No published evidence was strong enough to support an answer; add the rule "
                            "version/jurisdiction or select the relevant document passage.",
                        )
                    ],
                ),
                {},
            )

        selected = bundle.candidates[:3]
        claims: list[Claim] = []
        limitations: list[str] = []
        for index, candidate in enumerate(selected, start=1):
            if plan.intent == "document_explanation":
                text = (
                    f'The selected text says: "{candidate.excerpt[:400]}".'
                    if _english(plan)
                    else f"所选文本为：“{candidate.excerpt[:400]}”。"
                )
                kind = "interpretation"
            else:
                text = (
                    f"According to {candidate.title} ({candidate.source_version}): "
                    f"{candidate.excerpt[:500]}"
                    if _english(plan)
                    else f"根据《{candidate.title}》（{candidate.source_version}）：{candidate.excerpt[:500]}"
                )
                kind = "fact"
            claims.append(
                Claim(id=f"claim_{index}", text=text, kind=kind, citation_ids=[candidate.citation_id])
            )

        if any(candidate.synthetic for candidate in selected):
            limitations.append(
                SYNTHETIC_LIMITATION_EN if _english(plan) else SYNTHETIC_LIMITATION
            )
        if plan.intent == "trade_rule_explanation":
            limitations.append(TRADE_LIMITATION_EN if _english(plan) else TRADE_LIMITATION)
        if plan.intent == "document_explanation":
            limitations.append(DOCUMENT_LIMITATION_EN if _english(plan) else DOCUMENT_LIMITATION)

        strong = bool(selected) and selected[0].score >= 2.0 and len(claims) >= 1
        answer = Answer(
            outcome="answered",
            language=plan.language,
            support_level="strong" if strong else "qualified",
            claims=claims,
            citations=[_citation(candidate, bundle) for candidate in selected],
            limitations=limitations,
        )
        return Composition(answer, {candidate.citation_id: candidate for candidate in selected})


def review_answer(
    answer: Answer, bundle: EvidenceBundle, snapshot: dict[str, Any] | None
) -> tuple[Answer, list[dict[str, Any]]]:
    """Independent code review: citations must exist, excerpts must match, entities must be supported."""
    issues: list[dict[str, Any]] = []
    kept: list[Claim] = []
    by_id = bundle.by_id()
    for claim in answer.claims:
        problem: str | None = None
        for citation_id in claim.citation_ids:
            candidate = by_id.get(citation_id)
            if candidate is None:
                problem = "citation_not_in_bundle"
                break
            if not candidate.excerpt.strip():
                problem = "empty_excerpt"
                break
            source_text = normalize(candidate.source_text)
            if normalize(candidate.excerpt) not in source_text:
                problem = "excerpt_not_in_source"
                break
            if not supports_entities(claim.text, candidate.source_text):
                problem = "entity_not_supported"
                break
            if candidate.source_type == "document_snapshot":
                if not snapshot:
                    problem = "snapshot_missing"
                    break
                start = candidate.start_offset or 0
                end = candidate.end_offset or 0
                if snapshot.get("text", "")[start:end] != candidate.excerpt:
                    problem = "anchor_mismatch"
                    break
            if not claim_supported(claim.text, candidate):
                problem = "claim_not_supported"
                break
        if problem:
            issues.append(
                {
                    "code": problem,
                    "claim_id": claim.id,
                    "explanation": "The claim is not supported by evidence"
                    if answer.language == "en"
                    else "该 Claim 未被证据支持",
                }
            )
            continue
        kept.append(claim)

    used_citations = {cid for claim in kept for cid in claim.citation_ids}
    answer = answer.model_copy(
        update={
            "claims": kept,
            "citations": [citation for citation in answer.citations if citation.id in used_citations],
        }
    )
    if issues:
        answer.limitations = [
            *answer.limitations,
            "Some claims were removed because their citations or evidence were insufficient."
            if answer.language == "en"
            else "部分结论因引用/证据支持不足已被移除。",
        ]
    if answer.outcome == "answered" and not kept:
        answer = answer.model_copy(
            update={
                "outcome": "insufficient_evidence",
                "support_level": "insufficient",
                "claims": [],
                "citations": [],
                "limitations": [
                    *answer.limitations,
                    "No publishable conclusion was supported by evidence."
                    if answer.language == "en"
                    else "没有可发布的、被证据支持的结论。",
                ],
            }
        )
    elif kept and issues:
        answer = answer.model_copy(update={"support_level": "qualified"})
    return answer, issues