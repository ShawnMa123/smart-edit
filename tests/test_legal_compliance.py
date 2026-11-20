"""Compliance red flags: sanctions / export control / circumvention (`legal-document-risk-scan`).

The case this layer exists for: a draft that proposes exporting controlled goods to a sanctioned
country. The deterministic catalogue must catch it, produce draft anchors, and block the gate —
without pretending to be a licence determination.
"""

from __future__ import annotations

from app.documents.projection import plain_text_document
from app.legal_review.compliance import detect, evaluate_compliance
from app.legal_review.contracts import ReviewCreate
from app.legal_review.document import split_text
from app.legal_review.scan import ScanSettings, run_document_scan

EXPORT_EN = """EXPORT AGREEMENT
Seller: Northbridge Arms Trading LLC (United States)
Buyer: Sepahan Logistics Co. (Iran)
Destination: Tehran, Iran
Goods: 120 units of military-grade drone components, guided missile spare parts and ammunition
Contract value: USD 4,800,000.00
Governing law: Singapore
Payment: cash in a third country, shipment routed via a third country to avoid sanctions screening
"""

EXPORT_ZH = """出口合同
卖方：Northbridge Arms Trading LLC（美国）
买方：Sepahan Logistics Co.（伊朗）
目的地：伊朗德黑兰
货物：军用无人机部件、导弹备件及弹药 120 套
合同金额：USD 4,800,000.00
适用法律：新加坡
付款：第三国现金支付，经第三国转运以规避制裁审查
"""

CLEAN = """SOFTWARE LICENCE AGREEMENT
Supplier: Northwind Software Ltd (Singapore)
Customer: Harbourview Logistics Pte Ltd (Singapore)
Contract value: USD 25,000.00
Governing law: Singapore
The supplier grants a non-exclusive licence for warehouse management software, delivered
electronically. Payment is by bank transfer within 30 days of invoice.
"""


def _scan(text: str):
    request = ReviewCreate(
        workspace_id="ws_demo",
        document_id="doc_1",
        modes=["deterministic", "legal"],
        scope="document",
    )
    return run_document_scan(
        request,
        {
            "document_id": "doc_1",
            "revision": 1,
            "content_sha256": "sha-1",
            "text": text,
            "content": plain_text_document(text),
        },
        run_id="lr_1",
        report_id="lrep_1",
        statute=None,
        composer=None,
        settings=ScanSettings(),
    )


def test_detect_finds_goods_destination_and_circumvention():
    assessment = detect(EXPORT_EN)

    assert assessment.blocking_pair is True
    assert {signal.label for signal in assessment.goods} >= {
        "weapons / munitions",
        "missiles / rockets",
        "military drones / UAVs",
    }
    assert [signal.label for signal in assessment.embargoed] == ["Iran"]
    assert assessment.export_signal is True
    assert any(signal.label == "sanctions avoidance" for signal in assessment.evasion)
    assert any(signal.label == "third-country routing" for signal in assessment.evasion)


def test_detect_handles_the_chinese_wording():
    assessment = detect(EXPORT_ZH)

    assert assessment.blocking_pair is True
    assert [signal.label for signal in assessment.embargoed] == ["Iran"]
    assert any(signal.label == "military drones / UAVs" for signal in assessment.goods)
    assert any(signal.label == "third-country routing" for signal in assessment.evasion)


def test_sectoral_destination_is_a_restricted_pair_not_a_hard_block():
    assessment = detect("We export machine tools and dual-use items to Russia.")

    assert assessment.blocking_pair is False
    assert assessment.sectoral_pair is True
    assert [signal.label for signal in assessment.sectoral] == ["Russia"]


def test_ordinary_commercial_text_does_not_raise_a_flag():
    assessment = detect(CLEAN)

    assert assessment.goods == ()
    assert assessment.destinations == ()
    assert assessment.evasion == ()
    assert assessment.has_any is False


def test_the_compliance_layer_blocks_with_anchors_on_the_sanctions_sample():
    report = _scan(EXPORT_EN)

    assert report.snapshot["document_type"] == "contract"
    combined = next(
        finding
        for finding in report.findings
        if finding.check_id == "LEGAL:compliance:prohibited-transaction"
    )
    assert combined.severity == "Critical"
    assert combined.gate_type == "hard_block"
    assert combined.document_anchors, "the hard stop must point at the goods and the destination"
    assert "Iran" in combined.explanation

    statuses = {
        check.check_id: check.status
        for check in report.coverage
        if check.check_id.startswith("LEGAL:compliance:")
    }
    assert statuses["LEGAL:compliance:prohibited-transaction"] == "finding"
    assert statuses["LEGAL:compliance:export-control"] == "finding"
    assert statuses["LEGAL:compliance:sanctions"] == "finding"
    assert statuses["LEGAL:compliance:evasion"] == "finding"
    assert report.gate["status"] == "blocked"
    assert "hard_block_finding" in report.gate["reasons"]

    # A contract must not be judged against guarantee elements ("claim documents", "expiry").
    element_ids = {check.check_id for check in report.coverage if ":element:" in check.check_id}
    assert element_ids == {
        "LEGAL:element:amount",
        "LEGAL:element:currency",
        "LEGAL:element:parties",
        "LEGAL:element:jurisdiction",
    }


def test_a_clean_document_gets_pass_and_not_applicable_for_compliance():
    report = _scan(CLEAN)

    statuses = {
        check.check_id: check.status
        for check in report.coverage
        if check.check_id.startswith("LEGAL:compliance:")
    }
    assert statuses == {
        "LEGAL:compliance:prohibited-transaction": "not_applicable",
        "LEGAL:compliance:export-control": "pass",
        "LEGAL:compliance:sanctions": "pass",
        "LEGAL:compliance:evasion": "pass",
    }
    assert report.findings == []
    assert report.gate["status"] != "blocked"


def test_evasion_wording_alone_is_a_human_review_finding():
    plan = split_text("Payment must be split into three tranches and routed via a third country.")
    results = {check.check_id: (check, finding) for check, finding in evaluate_compliance(plan)}

    check, finding = results["LEGAL:compliance:evasion"]
    assert check.status == "finding"
    assert finding.gate_type == "human_review"
    assert finding.document_anchors