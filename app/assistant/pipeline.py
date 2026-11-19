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
MODEL_REFUSED_FALLBACK = (
    "模型未在给定证据上作答；以下结论直接摘录自已发布/法规证据原文，未作推断。"
)
MODEL_REFUSED_FALLBACK_EN = (
    "The model declined to answer from the provided evidence; the claims below quote the evidence "
    "verbatim and add no inference."
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

        selected = list(bundle.candidates[:3])
        # When approved web evidence exists, keep one slot for it: otherwise the assistant would
        # silently answer from the local corpus while the UI says web search ran.
        web_first = next(
            (candidate for candidate in bundle.candidates if candidate.source_type == "approved_web"),
            None,
        )
        if (
            web_first is not None
            and selected
            and all(candidate.source_type != "approved_web" for candidate in selected)
        ):
            selected = [*selected[:2], web_first]
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


class EvidenceComposer:
    """Deterministic fallback for "evidence exists but the model still refused".

    It quotes each evidence excerpt verbatim (no version echo, so the reviewer's entity check
    passes) and cites the quoted item. The service labels the answer as an excerpt fallback so the
    reader knows the model did not compose it (`knowledge-rag-first-fallback`).
    """

    def compose(
        self, plan: QueryPlan, bundle: EvidenceBundle, context: dict[str, Any]
    ) -> Composition:
        selected = list(bundle.candidates[:3])
        claims = [
            Claim(
                id=f"claim_{index}",
                text=candidate.excerpt[:400],
                kind="fact",
                citation_ids=[candidate.citation_id],
            )
            for index, candidate in enumerate(selected, start=1)
        ]
        limitations = [
            MODEL_REFUSED_FALLBACK_EN if _english(plan) else MODEL_REFUSED_FALLBACK
        ]
        if plan.intent == "trade_rule_explanation":
            limitations.append(TRADE_LIMITATION_EN if _english(plan) else TRADE_LIMITATION)
        answer = Answer(
            outcome="answered",
            language=plan.language,
            support_level="qualified",
            claims=claims,
            citations=[Citation(**bundle.citation(candidate)) for candidate in selected],
            limitations=limitations,
        )
        return Composition(
            answer, {candidate.citation_id: candidate for candidate in selected}
        )


WEB_ONLY_LIMITATION_ZH = "联网结果为未核验的第三方内容；执行前请以已发布来源为准。"
WEB_ONLY_LIMITATION_EN = (
    "Web results are unverified third-party content; rely on published sources before acting."
)
RULE_SOURCE_LIMITATION_ZH = (
    "规则版本、生效日与适用范围必须由本地已发布语料支撑，联网结果不足以支持该结论。"
)
RULE_SOURCE_LIMITATION_EN = (
    "Rule version, effective date and applicability require a published local source; web results "
    "cannot support that conclusion."
)
WEB_INCOMPLETE_ZH = "联网检索未完成，本回答不包含实时网页结果。"
WEB_INCOMPLETE_EN = "Web search did not complete; this answer does not include live web results."
WEB_BLOCKED_ZH = "出站判定未通过，本次未执行联网检索。"
WEB_BLOCKED_EN = "Web search was not run because outbound screening blocked the question."
WEB_SKIPPED_ZH = "本次请求未执行联网检索。"
WEB_SKIPPED_EN = "Web search was skipped for this request."

GENERAL_WEB_LIMITATION_ZH = (
    "该回答来自通用联网检索，属未核验第三方内容，不是已发布来源，也不构成法律意见。"
)
GENERAL_WEB_LIMITATION_EN = (
    "This answer comes from general web search: unverified third-party content, not a published "
    "source and not legal advice."
)
WEB_TOOL_NOT_OPEN_ZH = "当前模型账号未开通联网搜索插件，本次未使用实时网页结果。"
WEB_TOOL_NOT_OPEN_EN = (
    "Web search is not enabled for this account, so no live results were used. Activate the "
    "web_search plugin in the Volcengine console first."
)
GENERAL_WEB_NO_SOURCE_ZH = "本次联网结果没有生成可引用来源，因此没有可发布的结论。"
GENERAL_WEB_NO_SOURCE_EN = (
    "No web result produced a usable source link, so no citation was produced."
)
GENERAL_WEB_FALLBACK_ZH = (
    "已发布语料未能回答该问题；以下内容来自通用联网检索（未核验第三方内容），不构成规则依据。"
)
GENERAL_WEB_FALLBACK_EN = (
    "The published corpus could not answer this question; the answer below comes from general web "
    "search (unverified third-party content) and is not a rule source."
)
WEB_EMPTY_ZH = "联网搜索未返回可用结果；以上回答基于内部来源。"
WEB_EMPTY_EN = (
    "The web search returned no usable result; this answer relies on internal sources."
)
NO_EVIDENCE_ANYWHERE_ZH = "知识库检索与联网搜索都没有找到可用证据。"
NO_EVIDENCE_ANYWHERE_EN = (
    "Neither the knowledge base nor the web search returned usable evidence."
)


def review_general_answer(answer: Answer, known_ids: set[str]) -> tuple[Answer, int]:
    """Minimal review for general-web answers: only citation identity, never full-text containment.

    A claim that cites both approved and dropped sources keeps the approved references; it is dropped
    only when nothing citable remains.
    """
    kept: list[Claim] = []
    dropped = 0
    for claim in answer.claims:
        remaining = [citation_id for citation_id in claim.citation_ids if citation_id in known_ids]
        if remaining:
            kept.append(claim.model_copy(update={"citation_ids": remaining}))
        else:
            dropped += 1
    used = {citation_id for claim in kept for citation_id in claim.citation_ids}
    citations = [citation for citation in answer.citations if citation.id in used]
    return answer.model_copy(update={"claims": kept, "citations": citations}), dropped


def apply_general_web_policy(
    answer: Answer, *, has_url_citation: bool, language: str
) -> Answer:
    """General web answers are capped and always carry the unverified limitation.

    The gate is "does at least one citation carry a resolvable link", not "is the domain approved":
    the unverified label is what carries trust on this channel (`general-web-citations`).
    """
    english = language == "en"
    limitations = [
        *answer.limitations,
        GENERAL_WEB_LIMITATION_EN if english else GENERAL_WEB_LIMITATION_ZH,
    ]
    if not has_url_citation or (answer.outcome == "answered" and not answer.claims):
        return answer.model_copy(
            update={
                "outcome": "insufficient_evidence",
                "support_level": "insufficient",
                "claims": [],
                "citations": [],
                "limitations": [
                    *limitations,
                    GENERAL_WEB_NO_SOURCE_EN if english else GENERAL_WEB_NO_SOURCE_ZH,
                ],
            }
        )
    support = "qualified" if answer.support_level in ("strong", "qualified") else answer.support_level
    return answer.model_copy(update={"support_level": support, "limitations": limitations})


def apply_layer_policy(answer: Answer, plan: Any, bundle: EvidenceBundle) -> Answer:
    """Cap evidence strength when web evidence participates (knowledge-retrieval-layers D8).

    Web content may inform an answer but never becomes a published rule source: `strong` is capped
    at `qualified`, and a rule question answered only by web evidence is refused rather than
    presented as an authority.
    """
    web_ids = {
        candidate.citation_id
        for candidate in bundle.candidates
        if candidate.source_type == "approved_web"
    }
    used = {citation_id for claim in answer.claims for citation_id in claim.citation_ids}
    if not web_ids or not (used & web_ids):
        return answer

    english = getattr(plan, "language", "en") == "en"
    limitation = WEB_ONLY_LIMITATION_EN if english else WEB_ONLY_LIMITATION_ZH
    limitations = [*answer.limitations, limitation]

    local_published = any(
        candidate.source_type != "approved_web" for candidate in bundle.candidates
    )
    if getattr(plan, "intent", "") == "trade_rule_explanation" and not local_published:
        return answer.model_copy(
            update={
                "outcome": "unable_to_assess",
                "support_level": "insufficient",
                "claims": [],
                "citations": [],
                "limitations": [
                    *limitations,
                    RULE_SOURCE_LIMITATION_EN if english else RULE_SOURCE_LIMITATION_ZH,
                ],
            }
        )

    support = "qualified" if answer.support_level == "strong" else answer.support_level
    return answer.model_copy(update={"support_level": support, "limitations": limitations})


def reconcile_answer(answer: Answer) -> Answer:
    """Make the model's answer structurally publishable without publishing unsupported claims.

    Real providers sometimes return an outcome that contradicts the payload (`answered` without
    claims, `insufficient_evidence` with claims, clarification questions on another outcome). We
    never invent content: claims that contradict the outcome are dropped, and missing prerequisites
    downgrade the outcome instead of failing the whole run.
    """
    english = answer.language == "en"
    updates: dict[str, Any] = {}
    outcome = answer.outcome

    if outcome == "answered":
        if not answer.claims:
            outcome = "insufficient_evidence"
            updates["support_level"] = "insufficient"
            updates["limitations"] = [
                *answer.limitations,
                "The model produced no claim supported by the retrieved evidence."
                if english
                else "模型没有给出可被检索证据支持的结论。",
            ]
        elif answer.support_level not in ("strong", "qualified"):
            updates["support_level"] = "qualified"
        if answer.handoff_target is not None:
            updates["handoff_target"] = None
    else:
        if answer.claims:
            updates["claims"] = []
            updates["citations"] = []
        if outcome == "needs_clarification":
            if not answer.clarification_questions:
                outcome = "unable_to_assess"
            else:
                updates["clarification_questions"] = answer.clarification_questions[:3]
                updates["support_level"] = "not_applicable"
        elif answer.clarification_questions:
            updates["clarification_questions"] = []
        if outcome == "needs_handoff" and answer.handoff_target is None:
            outcome = "unable_to_assess"
        if outcome in ("insufficient_evidence", "unable_to_assess"):
            if answer.support_level != "insufficient":
                updates["support_level"] = "insufficient"
            if not (updates.get("limitations") or answer.limitations):
                updates["limitations"] = [
                    "No publishable conclusion was supported by the retrieved evidence."
                    if english
                    else "没有可发布的、被检索证据支持的结论。"
                ]

    updates["outcome"] = outcome
    return answer.model_copy(update=updates)


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