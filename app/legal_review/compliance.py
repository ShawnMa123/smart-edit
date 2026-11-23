"""Substantive compliance red flags: sanctions destinations, controlled goods, evasion wording.

**This is a red-flag layer, not a screening service.** It answers "does the text contain wording a
trade-compliance officer must look at?" — never "this transaction is legal/illegal". Real clearance
needs denied-party screening (OFAC SDN, BIS Entity List, EU/UN lists), a goods classification
(ECCN/USML) and a licence determination, none of which live in this repository.

The catalogues are curated data on purpose: each term is explainable in the report, and a match
carries the exact substring plus its draft anchor. They are deliberately conservative (high
precision): a term that fires on innocent text (`arms length`, `alarm`, `shipment` alone) is not a
red flag on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# tier: `embargoed` = comprehensive sanctions / arms embargo; `sectoral` = restricted sectors.
DESTINATIONS: tuple[tuple[str, str, str], ...] = (
    ("Iran", r"伊朗|\biran\b", "embargoed"),
    ("North Korea", r"朝鲜|北韩|\bnorth\s+korea\b|\bdprk\b", "embargoed"),
    ("Syria", r"叙利亚|\bsyria\b", "embargoed"),
    ("Cuba", r"古巴|\bcuba\b", "embargoed"),
    ("Crimea", r"克里米亚|\bcrimea\b", "embargoed"),
    ("Donetsk", r"顿涅茨克|\bdonetsk\b", "embargoed"),
    ("Luhansk", r"卢甘斯克|\bluhansk\b", "embargoed"),
    ("Russia", r"俄罗斯|\brussia\b", "sectoral"),
    ("Belarus", r"白俄罗斯|\bbelarus\b", "sectoral"),
    ("Myanmar", r"缅甸|\bmyanmar\b|\bburma\b", "sectoral"),
    ("Venezuela", r"委内瑞拉|\bvenezuela\b", "sectoral"),
)

# label, pattern. Order matters only for the order of the report line.
GOODS: tuple[tuple[str, str], ...] = (
    (
        "weapons / munitions",
        r"武器|军火|军械|枪械|弹药|火炮|军品|"
        r"\b(?:weapons?|munitions?|firearms?|ammunition|artillery|small\s+arms)\b",
    ),
    (
        "missiles / rockets",
        r"导弹|火箭弹|弹头|"
        r"\b(?:missiles?|rockets?|warheads?|ballistic|rocket\s+artillery)\b",
    ),
    (
        "military drones / UAVs",
        r"军用无人机|武装无人机|"
        r"\b(?:military[- ]grade|military|armed|combat|strike)\s+(?:drones?|uavs?)\b",
    ),
    (
        "armoured vehicles / tanks",
        r"坦克|装甲车|\b(?:armou?red\s+vehicles?|battle\s+tanks?)\b",
    ),
    (
        "combat aircraft / warships",
        r"战斗机|军舰|潜艇|"
        r"\b(?:fighter\s+(?:aircraft|jets?)|warships?|submarines?|combat\s+aircraft)\b",
    ),
    (
        "nuclear / WMD",
        r"核武器|核材料|浓缩铀|离心机|化学武器|生物武器|神经毒剂|大规模杀伤性武器|"
        r"\b(?:nuclear\s+weapons?|enriched\s+uranium|centrifug\w*|chemical\s+weapons?|"
        r"biological\s+weapons?|nerve\s+agent|weapons?\s+of\s+mass\s+destruction|wmd)\b",
    ),
    ("dual-use items", r"军民两用|两用物项|\bdual[- ]use\b"),
    (
        "cluster munitions / landmines",
        r"集束弹药|地雷|"
        r"\b(?:cluster\s+munitions?|landmines?|anti[- ]personnel\s+mines?)\b",
    ),
    (
        "torture equipment",
        r"刑具|电击(?:设备|棍)|\b(?:torture\s+equipment|electric\s+shock\s+(?:belt|equipment))\b",
    ),
    (
        "narcotics / precursors",
        r"毒品|芬太尼|前体化学品|\b(?:narcotics?|fentanyl|precursor\s+chemicals?)\b",
    ),
    (
        "endangered species / cultural property",
        r"象牙|犀牛角|濒危物种|文物|"
        r"\b(?:ivory|rhino\s+horn|endangered\s+species|antiquities|cultural\s+property)\b",
    ),
)

# Moving goods across a border.
CHANNELS: tuple[str, str] = (
    "export-channel",
    r"出口|再出口|转口|转运|过境|运往|发往|报关|"
    r"\b(?:export(?:ed|s|ing)?|re-?export(?:ed|s|ing)?|transship(?:ped|ment)?|"
    r"trans-ship(?:ped|ment)?|shipped|shipment|consign(?:ed|ment)?|deliver(?:ed|y)?)\b",
)

# Wording that only makes sense when someone is trying not to be seen.
EVASION: tuple[tuple[str, str], ...] = (
    (
        "sanctions avoidance",
        r"规避制裁|逃避制裁|绕过制裁|绕开制裁|规避审查|"
        r"\b(?:circumvent|evade|bypass)\w*\b[^.\n]{0,30}\bsanctions?\b|"
        r"\b(?:sanctions?|embargo)\s+(?:avoidance|evasion|circumvention)\b|"
        r"\bavoid\s+(?:the\s+)?sanctions?\b",
    ),
    (
        "third-country routing",
        r"第三国转运|经第三国|经由第三国|中转(?:国|地)|"
        r"\bthird[- ]country\b|\bvia\s+a\s+third\s+country\b",
    ),
    (
        "payment splitting / cash",
        r"拆单|拆分付款|化整为零|现金支付|以现金|不记名|"
        r"\b(?:split|splitting)\s+(?:the\s+)?(?:payment|shipment|order)s?\b|"
        r"\bbreak\s+bulk\b|\bcash\s+payment\b|\bin\s+cash\b|\bbearer\s+shares?\b",
    ),
    (
        "opaque end user",
        r"最终用户不明|最终用途不明|空壳公司|壳公司|"
        r"\bend[- ]user\s+(?:unknown|undisclosed|not\s+disclosed)\b|\bshell\s+compan(?:y|ies)\b",
    ),
)

CATEGORY = "compliance"
BLOCKING_OPERATIONS = (
    "submit_version",
    "start_approval",
    "formal_export",
    "handoff",
    "formal_mapping",
)

# Rule ids the composer may reference (kept in one place so the prompt and the validator agree).
COMPOSER_RULES: tuple[dict, ...] = (
    {
        "rule_id": "LEGAL-COMPLIANCE-PROHIBITED",
        "label": "Sensitive goods + sanctioned destination",
        "severity": "Warning",
        "gate_type": "human_review",
    },
    {
        "rule_id": "LEGAL-COMPLIANCE-EXPORT-CONTROL",
        "label": "Export-controlled goods",
        "severity": "Warning",
        "gate_type": "human_review",
    },
    {
        "rule_id": "LEGAL-COMPLIANCE-SANCTIONS",
        "label": "Sanctioned destination",
        "severity": "Warning",
        "gate_type": "human_review",
    },
    {
        "rule_id": "LEGAL-COMPLIANCE-EVASION",
        "label": "Circumvention wording",
        "severity": "Warning",
        "gate_type": "human_review",
    },
    {
        "rule_id": "LEGAL-COMPLIANCE-BRIBERY",
        "label": "Bribery / facilitation payments",
        "severity": "Warning",
        "gate_type": "human_review",
    },
    {
        "rule_id": "LEGAL-COMPLIANCE-AML",
        "label": "Money-laundering indicators",
        "severity": "Warning",
        "gate_type": "human_review",
    },
)


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    matched: str
    start: int
    end: int


@dataclass(frozen=True)
class ComplianceAssessment:
    destinations: tuple[Signal, ...] = ()
    goods: tuple[Signal, ...] = ()
    channels: tuple[Signal, ...] = ()
    evasion: tuple[Signal, ...] = ()

    @property
    def embargoed(self) -> tuple[Signal, ...]:
        return tuple(signal for signal in self.destinations if signal.key == "embargoed")

    @property
    def sectoral(self) -> tuple[Signal, ...]:
        return tuple(signal for signal in self.destinations if signal.key == "sectoral")

    @property
    def blocking_pair(self) -> bool:
        """Controlled goods + a comprehensively sanctioned destination: the hard stop."""
        return bool(self.goods) and bool(self.embargoed)

    @property
    def sectoral_pair(self) -> bool:
        return bool(self.goods) and bool(self.sectoral)

    @property
    def export_signal(self) -> bool:
        return bool(self.goods) and bool(self.channels)

    @property
    def has_any(self) -> bool:
        return bool(self.destinations or self.goods or self.evasion)


def _first_matches(pattern: str, text: str, *, label: str, key: str) -> list[Signal]:
    """One signal per label: the first match is enough to raise the flag."""
    found = re.search(pattern, text, re.IGNORECASE)
    if found is None:
        return []
    return [
        Signal(
            key=key,
            label=label,
            matched=found.group(0),
            start=found.start(),
            end=found.end(),
        )
    ]


def detect(text: str, *, extra_destinations: tuple[str, ...] = ()) -> ComplianceAssessment:
    """Scan the draft for curated red-flag terms. Pure and side-effect free."""
    body = text or ""
    destinations: list[Signal] = []
    for name, pattern, tier in DESTINATIONS:
        destinations.extend(_first_matches(pattern, body, label=name, key=tier))
    for name in extra_destinations:
        name = (name or "").strip()
        if name:
            destinations.extend(
                _first_matches(re.escape(name), body, label=name, key="embargoed")
            )

    goods: list[Signal] = []
    for label, pattern in GOODS:
        goods.extend(_first_matches(pattern, body, label=label, key="goods"))

    channels: list[Signal] = []
    label, pattern = CHANNELS
    channels.extend(_first_matches(pattern, body, label=label, key="channel"))

    evasion: list[Signal] = []
    for label, pattern in EVASION:
        evasion.extend(_first_matches(pattern, body, label=label, key="evasion"))

    return ComplianceAssessment(
        destinations=tuple(destinations),
        goods=tuple(goods),
        channels=tuple(channels),
        evasion=tuple(evasion),
    )


def labels(signals: tuple[Signal, ...]) -> str:
    return ", ".join(dict.fromkeys(signal.label for signal in signals))


def _anchor(plan, signal: Signal):
    """The draft block containing the matched term, or `None` when it has no block."""
    from app.legal_review.checks import anchor_for

    return anchor_for(plan, None, signal.start, signal.end)


def _check(check_id: str, status: str, reasons: list[str], findings: list[str] | None = None):
    from app.legal_review.contracts import CheckResult

    return CheckResult(
        check_id=check_id,
        method="deterministic",
        scope_key="compliance",
        status=status,
        reason_codes=reasons,
        finding_ids=findings or [],
    )


def evaluate_compliance(plan) -> list[tuple[object, object | None]]:
    """Four planned units: prohibited pair, export control, sanctions destination, evasion.

    Every unit is evaluated (pass/finding/not_applicable), so the coverage denominator always
    includes the compliance layer and "no terms matched" is a verdict, not silence.
    """
    from app.legal_review.checks import make_finding

    assessment = detect(plan.text)
    results: list[tuple[object, object | None]] = []

    # 1 · controlled goods + comprehensively sanctioned destination → the hard stop
    prohibited_id = "LEGAL:compliance:prohibited-transaction"
    if assessment.blocking_pair or assessment.sectoral_pair:
        blocking = assessment.blocking_pair
        destinations = assessment.embargoed if blocking else assessment.sectoral
        anchors = [
            anchor
            for anchor in (
                *(_anchor(plan, signal) for signal in assessment.goods),
                *(_anchor(plan, signal) for signal in destinations),
            )
            if anchor is not None
        ]
        finding = make_finding(
            check_id=prohibited_id,
            title=(
                "Sensitive goods destined for a sanctioned country"
                if blocking
                else "Sensitive goods destined for a restricted country"
            ),
            explanation=(
                f"The draft combines controlled goods ({labels(assessment.goods)}) with "
                f"{labels(destinations)} as a destination. Under US EAR/ITAR and OFAC country "
                "programmes — and equivalent EU/UN measures — such an export is prohibited unless "
                "a licence or exception applies. This is a red-flag check on the text itself, not "
                "a licence determination."
            ),
            severity="Critical",
            gate_type="hard_block" if blocking else "human_review",
            category=CATEGORY,
            operations=BLOCKING_OPERATIONS if blocking else (),
            rule_id="LEGAL-COMPLIANCE-PROHIBITED",
            suggestion=(
                "Stop and escalate to trade compliance: screen every party against denied-party "
                "lists (OFAC SDN, BIS Entity List, EU/UN), classify the goods (ECCN/USML), and do "
                "not submit until a licence or a documented no-licence-required decision exists."
            ),
            document_anchors=anchors,
            applicability={
                "jurisdictions": [],
                "limitations": ["lexical red flag, not legal advice"],
            },
        )
        results.append(
            (_check(prohibited_id, "finding", ["prohibited_pair"], [finding.finding_id]), finding)
        )
    else:
        results.append(
            (_check(prohibited_id, "not_applicable", ["no_sensitive_sanctioned_pair"]), None)
        )

    # 2 · controlled goods moving across a border
    export_id = "LEGAL:compliance:export-control"
    if assessment.goods:
        cross_border = assessment.export_signal
        anchors = [a for a in (_anchor(plan, signal) for signal in assessment.goods) if a]
        finding = make_finding(
            check_id=export_id,
            title=(
                "Export-controlled goods without a stated licence"
                if cross_border
                else "Export-controlled goods referenced in the draft"
            ),
            explanation=(
                f"The draft references {labels(assessment.goods)}"
                + (" and describes them crossing a border." if cross_border else ".")
                + " Such items are typically listed (ECCN/USML or EU dual-use annex); the draft "
                "states no classification, licence or end-user undertaking. This is a red flag, "
                "not a classification decision."
            ),
            severity="Critical" if cross_border else "Warning",
            gate_type="human_review",
            category=CATEGORY,
            operations=(),
            rule_id="LEGAL-COMPLIANCE-EXPORT-CONTROL",
            suggestion=(
                "Record the goods classification, the licence (or licence exception) and the "
                "end-user/end-use statement before the export is approved."
            ),
            document_anchors=anchors,
            applicability={
                "jurisdictions": [],
                "limitations": ["lexical red flag, not legal advice"],
            },
        )
        results.append(
            (_check(export_id, "finding", ["controlled_goods"], [finding.finding_id]), finding)
        )
    else:
        results.append((_check(export_id, "pass", ["no_controlled_goods"]), None))

    # 3 · sanctioned destination
    sanctions_id = "LEGAL:compliance:sanctions"
    if assessment.destinations:
        embargoed = assessment.embargoed
        destinations = embargoed or assessment.sectoral
        anchors = [a for a in (_anchor(plan, signal) for signal in destinations) if a]
        finding = make_finding(
            check_id=sanctions_id,
            title=(
                "Comprehensively sanctioned destination referenced"
                if embargoed
                else "Restricted (sectoral sanctions) destination referenced"
            ),
            explanation=(
                f"The draft names {labels(destinations)}. "
                + (
                    "Comprehensive sanctions restrict most dealings, including with government "
                    "entities, unless a general or specific licence applies."
                    if embargoed
                    else "Sectoral sanctions restrict listed sectors, entities and financing; the "
                    "counterparty and the goods must be screened."
                )
                + " This is a red flag on the text, not a screening result."
            ),
            severity="Critical" if embargoed else "Warning",
            gate_type="human_review",
            category=CATEGORY,
            operations=(),
            rule_id="LEGAL-COMPLIANCE-SANCTIONS",
            suggestion=(
                "Run denied-party and country screening, document the legal basis for any "
                "permitted dealing, and escalate to compliance before approval."
            ),
            document_anchors=anchors,
            applicability={
                "jurisdictions": [],
                "limitations": ["lexical red flag, not legal advice"],
            },
        )
        results.append(
            (_check(sanctions_id, "finding", ["sanctioned_destination"], [finding.finding_id]), finding)
        )
    else:
        results.append((_check(sanctions_id, "pass", ["no_sanctioned_destination"]), None))

    # 4 · circumvention wording
    evasion_id = "LEGAL:compliance:evasion"
    if assessment.evasion:
        anchors = [a for a in (_anchor(plan, signal) for signal in assessment.evasion) if a]
        finding = make_finding(
            check_id=evasion_id,
            title="Circumvention wording detected",
            explanation=(
                "The draft contains wording that is typical of sanctions circumvention: "
                f"{labels(assessment.evasion)}. Even where the underlying transaction is otherwise "
                "permissible, this wording must be resolved before approval."
            ),
            severity="Warning",
            gate_type="human_review",
            category=CATEGORY,
            operations=(),
            rule_id="LEGAL-COMPLIANCE-EVASION",
            suggestion=(
                "Remove or explain the routing/payment structure, identify the end user, and "
                "document why the structure is needed."
            ),
            document_anchors=anchors,
            applicability={
                "jurisdictions": [],
                "limitations": ["lexical red flag, not legal advice"],
            },
        )
        results.append(
            (_check(evasion_id, "finding", ["circumvention_wording"], [finding.finding_id]), finding)
        )
    else:
        results.append((_check(evasion_id, "pass", ["no_circumvention_wording"]), None))

    return results


__all__ = [
    "BLOCKING_OPERATIONS",
    "CATEGORY",
    "CHANNELS",
    "COMPOSER_RULES",
    "ComplianceAssessment",
    "DESTINATIONS",
    "EVASION",
    "GOODS",
    "Signal",
    "detect",
    "evaluate_compliance",
    "labels",
]