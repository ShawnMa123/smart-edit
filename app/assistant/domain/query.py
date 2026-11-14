"""Deterministic query analysis (design D7). No model call in A."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.knowledge.text import entities, tokens

Intent = str  # product_faq | trade_rule_explanation | document_explanation | out_of_scope
Handoff = str  # automation | standards_audit | regulatory_advice

_EDIT = re.compile(
    r"\b(rewrite|polish|modify|replace|fill in|change the wording|edit the clause)\b"
    r"|润色|改写|替换|修改|填充|改成|帮我改|改一下",
    re.IGNORECASE,
)
_AUDIT_ACTION = re.compile(
    r"\b(run|perform|start|check)\b.{0,24}\b(audit|compliance)\b"
    r"|审查(我的|这份)?文档|全文检查|合规审查|帮我检查",
    re.IGNORECASE,
)
_REGULATORY = re.compile(
    r"\b(export requirement|jurisdiction|is it legal|can we issue|sanctions?)\b"
    r"|出口管制|是否合法|能否开立|法规要求|法域|合规要求",
    re.IGNORECASE,
)
# Capability/help questions must stay after edit/audit/regulatory actions: a real "帮我改写" request
# is a handoff, not a help lookup. "你能修改文档吗" intentionally keeps the handoff path.
_HELP = re.compile(
    r"你能做什么|能做什么|不能做什么|怎么用(这个)?助手|助手怎么用|使用指南"
    r"|支持哪些(问题|类型)|可以问(什么|哪些)|怎么提问|如何提问",
    re.IGNORECASE,
)
_HELP_EN = re.compile(
    r"\b(what can you do|what can this assistant not do|what can't (you|this assistant) do"
    r"|how (should|do) i (ask|use)|how can i ask|what questions can i ask|usage guide)\b",
    re.IGNORECASE,
)

# A's help sources are fixtures; C can replace this with a configured per-language mapping.
HELP_SOURCE_IDS = {"zh-CN": "KS-HELP-001", "en": "KS-HELP-002"}
HELP_SOURCE_ID = HELP_SOURCE_IDS["zh-CN"]
_DOCUMENT = re.compile(r"\b(this document|selected text|selection|the document)\b|这段|本文|选区|当前文档", re.IGNORECASE)
_RULE = re.compile(r"\b(urdg|isp98|ucp|isbp|rule|clause|guarantee|standby)\b|条款|规则|惯例|保函", re.IGNORECASE)
_PRODUCT = re.compile(
    r"\b(lock|submit|version|import|editor|audit|save|toolbar|panel|scan|ocr|log|export|attachment"
    r"|approval|amount|limit|sanction|records?|documents?|application|apply|materials?|fees?|charges?"
    r"|cancellation|release|processing|rejection)\b"
    r"|编辑锁|提交|版本|导入|编辑器|工具栏|保存|面板|审查|检查|扫描|文件|日志|导出|附件|审批|金额|上限|制裁|记录",
    re.IGNORECASE,
)
_APPLICABILITY = re.compile(r"\b(appl(y|ies|icable)|scope)\b|适用|是否适用|适用于", re.IGNORECASE)


@dataclass
class QueryPlan:
    intent: Intent
    question: str
    language: str
    retrieval_terms: list[str]
    entities: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    handoff_target: Handoff | None = None
    selection_text: str | None = None
    has_snapshot: bool = False
    applicable_on: str | None = None
    jurisdictions: list[str] = field(default_factory=list)
    rule_version: str | None = None
    capability_help: bool = False
    help_source_id: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification_questions)


def _language(question: str) -> str:
    return "zh-CN" if re.search(r"[\u4e00-\u9fff]", question or "") else "en"


def analyze(
    question: str,
    *,
    selection_text: str | None = None,
    has_snapshot: bool = False,
    applicable_on: str | None = None,
    jurisdiction_codes: list[str] | None = None,
    rule_version: str | None = None,
) -> QueryPlan:
    question = (question or "").strip()
    language = _language(question)
    jurisdictions = list(jurisdiction_codes or [])
    terms = tokens(question)
    found = entities(question)

    intent: Intent
    handoff: Handoff | None = None
    clarifications: list[str] = []
    capability_help = False
    help_source_id: str | None = None

    if _EDIT.search(question):
        intent, handoff = "out_of_scope", "automation"
    elif _AUDIT_ACTION.search(question):
        intent, handoff = "out_of_scope", "standards_audit"
    elif _REGULATORY.search(question):
        intent, handoff = "out_of_scope", "regulatory_advice"
    elif _HELP.search(question) or _HELP_EN.search(question):
        intent = "product_faq"
        capability_help = True
        help_source_id = HELP_SOURCE_IDS.get(language)
    elif selection_text or (has_snapshot and _DOCUMENT.search(question)):
        intent = "document_explanation"
    elif _RULE.search(question) or found:
        intent = "trade_rule_explanation"
    elif _PRODUCT.search(question):
        intent = "product_faq"
    else:
        intent = "out_of_scope"

    if intent == "trade_rule_explanation" and _APPLICABILITY.search(question):
        if not (jurisdictions or applicable_on or rule_version):
            if language == "en":
                clarifications.append(
                    "Please confirm the rule name/version and the jurisdiction or applicable date; "
                    "without them the applicability cannot be determined."
                )
            else:
                clarifications.append(
                    "请确认适用的规则名称/版本，以及法域或交易日期；这些信息缺失时无法判断适用性。"
                )
        if found:
            terms.extend(found)

    if intent == "document_explanation" and not selection_text:
        if language == "en":
            clarifications.append(
                "Please select the passage you want explained, then ask the question again."
            )
        else:
            clarifications.append("请先选择要解释的文本片段，再发起提问。")

    if selection_text:
        terms.extend(tokens(selection_text))

    if intent == "product_faq" and language != "en":
        # Chinese corpus title carries 产品/手册; keep the old hint only for Chinese. For English,
        # injecting product/manual would make every chunk in the English product source match by
        # title and turn an unrelated question into a false "answered".
        terms.extend(["product", "manual"])

    return QueryPlan(
        intent=intent,
        question=question,
        language=language,
        retrieval_terms=list(dict.fromkeys(terms)),
        entities=found,
        clarification_questions=clarifications,
        handoff_target=handoff,
        selection_text=selection_text,
        has_snapshot=has_snapshot,
        applicable_on=applicable_on,
        jurisdictions=jurisdictions,
        rule_version=rule_version,
        capability_help=capability_help,
        help_source_id=help_source_id,
    )