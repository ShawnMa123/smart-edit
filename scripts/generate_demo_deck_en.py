#!/usr/bin/env python3
"""Generate the English HSBC Nexus demo deck.

    uv pip install --python .venv/bin/python python-pptx
    .venv/bin/python scripts/generate_demo_deck_en.py

Style: HSBC Nexus pitch language — dark ink, white type, one red accent, mint status tags,
hairline tables, evidence-first narrative. No HSBC logo asset is copied; the wordmark is typographic.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo" / "HSBC_Nexus_Document_Editor_Demo.pptx"

BG = RGBColor(0x08, 0x0D, 0x16)
BG_2 = RGBColor(0x0D, 0x16, 0x25)
CARD = RGBColor(0x10, 0x1A, 0x2B)
CARD_2 = RGBColor(0x0B, 0x18, 0x23)
RED = RGBColor(0xDB, 0x00, 0x11)
RED_SOFT = RGBColor(0x8E, 0x08, 0x18)
MINT = RGBColor(0x72, 0xE3, 0xB0)
MINT_DARK = RGBColor(0x12, 0x5C, 0x4A)
WHITE = RGBColor(0xF7, 0xFA, 0xFC)
GREY = RGBColor(0x9A, 0xAA, 0xBC)
GREY_2 = RGBColor(0x6B, 0x7D, 0x93)
LINE = RGBColor(0x26, 0x37, 0x4F)
LINE_2 = RGBColor(0x1A, 0x28, 0x3D)

FONT = "Arial"
MONO = "Menlo"
W, H = Inches(13.333), Inches(7.5)
TOTAL = 15


def deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    return prs


def slide(prs: Presentation):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fill = s.background.fill
    fill.solid()
    fill.fore_color.rgb = BG
    return s


def _font(run, size: float, bold: bool, color: RGBColor, name: str = FONT) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = rpr.makeelement(qn("a:ea"), {})
        rpr.append(ea)
    ea.set("typeface", name)


def text(
    s,
    value: str,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 14,
    bold: bool = False,
    color: RGBColor = WHITE,
    name: str = FONT,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    spacing: float = 1.05,
) -> None:
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    run = p.add_run()
    run.text = value
    _font(run, size, bold, color, name)


def rect(
    s,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: RGBColor = CARD,
    line_color: RGBColor | None = LINE,
    radius: bool = False,
    width: float = 0.75,
) -> None:
    shape = s.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line_color is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line_color
        shape.line.width = Pt(width)
    shape.shadow.inherit = False


def rule(s, *, x: float, y: float, w: float, color: RGBColor = LINE, h: float = 0.012) -> None:
    rect(s, x=x, y=y, w=w, h=h, fill=color, line_color=None)


def tag(s, value: str, *, x: float, y: float, w: float, color: RGBColor = MINT, fill: RGBColor = MINT_DARK) -> None:
    rect(s, x=x, y=y, w=w, h=0.27, fill=fill, line_color=color, radius=True, width=0.5)
    text(s, value, x=x, y=y + 0.045, w=w, h=0.18, size=8, bold=True, color=color, align=PP_ALIGN.CENTER)


def kicker(s, value: str) -> None:
    text(s, value.upper(), x=0.62, y=0.8, w=9.0, h=0.22, size=9.5, bold=True, color=RED)


def headline(s, value: str, *, size: float = 26, y: float = 1.02, h: float = 0.62) -> None:
    text(s, value, x=0.62, y=y, w=12.1, h=h, size=size, bold=True, color=WHITE, spacing=1.0)


def subhead(s, value: str, *, y: float = 1.68, size: float = 11, h: float = 0.3) -> None:
    text(s, value, x=0.62, y=y, w=12.1, h=h, size=size, color=GREY)


def header(s, kick: str, head: str, sub: str | None = None, *, size: float = 26) -> None:
    kicker(s, kick)
    headline(s, head, size=size)
    if sub:
        subhead(s, sub)


def footer(s, page: int) -> None:
    rule(s, x=0.62, y=7.08, w=12.08, color=LINE_2)
    text(
        s,
        "HSBC NEXUS  ·  AI TRADE DOCUMENT WORKSPACE",
        x=0.62,
        y=7.16,
        w=7.5,
        h=0.18,
        size=7.5,
        bold=True,
        color=GREY_2,
    )
    text(
        s,
        f"{page:02d} / {TOTAL:02d}",
        x=11.8,
        y=7.16,
        w=0.9,
        h=0.18,
        size=7.5,
        color=GREY_2,
        align=PP_ALIGN.RIGHT,
    )


def brand(s) -> None:
    rect(s, x=0.62, y=0.38, w=0.32, h=0.32, fill=RED, line_color=None, radius=True)
    text(s, "N", x=0.62, y=0.43, w=0.32, h=0.2, size=12, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    text(s, "HSBC", x=1.05, y=0.41, w=0.75, h=0.22, size=12, bold=True, color=WHITE)
    text(s, "NEXUS", x=1.7, y=0.41, w=0.9, h=0.22, size=12, bold=True, color=RED)


def scope_tag(s, value: str = "P0 PILOT  ·  DOCUMENT WORKSPACE") -> None:
    tag(s, value, x=9.9, y=0.4, w=2.85, color=MINT, fill=RGBColor(0x0B, 0x23, 0x1E))


def notes(s, value: str) -> None:
    s.notes_slide.notes_text_frame.text = value
def bullets(
    s,
    items: list[tuple[str, str]],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 10.5,
    dot: str = "•",
) -> None:
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for index, (head, body) in enumerate(items):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.space_after = Pt(6)
        p.line_spacing = 1.05
        run = p.add_run()
        run.text = f"{dot}  "
        _font(run, size, True, RED)
        run = p.add_run()
        run.text = head
        _font(run, size, True, WHITE)
        if body:
            run = p.add_run()
            run.text = f"  {body}"
            _font(run, size, False, GREY)


def card(
    s,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    head: str,
    body: str,
    tag_text: str | None = None,
    tag_color: RGBColor = MINT,
    border: RGBColor = LINE,
    accent: RGBColor = RED,
) -> None:
    rect(s, x=x, y=y, w=w, h=h, fill=CARD, line_color=border, radius=True)
    rect(s, x=x, y=y, w=0.035, h=h, fill=accent, line_color=None)
    text(s, head, x=x + 0.2, y=y + 0.12, w=w - 1.4, h=0.28, size=11.5, bold=True, color=WHITE)
    text(s, body, x=x + 0.2, y=y + 0.48, w=w - 0.38, h=h - 0.6, size=8.8, color=GREY)
    if tag_text:
        fill = RGBColor(0x0B, 0x23, 0x1E) if tag_color == MINT else RGBColor(0x2A, 0x0A, 0x10)
        tag(s, tag_text, x=x + w - 1.28, y=y + 0.12, w=1.12, color=tag_color, fill=fill)


def metric(
    s,
    *,
    x: float,
    y: float,
    w: float,
    big: str,
    label: str,
    note: str = "",
    color: RGBColor = RED,
) -> None:
    rect(s, x=x, y=y, w=w, h=1.22, fill=CARD, line_color=LINE, radius=True)
    text(s, big, x=x + 0.16, y=y + 0.12, w=w - 0.3, h=0.48, size=23, bold=True, color=color)
    text(s, label, x=x + 0.16, y=y + 0.65, w=w - 0.3, h=0.22, size=9.2, bold=True, color=WHITE)
    if note:
        text(s, note, x=x + 0.16, y=y + 0.9, w=w - 0.3, h=0.2, size=7.8, color=GREY)


def rows(
    s,
    data: list[list[str]],
    *,
    x: float,
    y: float,
    widths: list[float],
    row_h: float = 0.3,
    size: float = 8.2,
    head: bool = True,
    colors: list[RGBColor] | None = None,
) -> None:
    """Hairline evidence table; no zebra fill."""
    for r_index, row in enumerate(data):
        yy = y + r_index * row_h
        if r_index == 0 and head:
            rect(
                s,
                x=x,
                y=yy,
                w=sum(widths),
                h=row_h,
                fill=RGBColor(0x0B, 0x18, 0x23),
                line_color=None,
            )
        cx = x
        for c_index, value in enumerate(row):
            color = WHITE if r_index == 0 and head else GREY
            if colors and r_index > 0 and c_index < len(colors):
                color = colors[c_index]
            text(
                s,
                value,
                x=cx + 0.08,
                y=yy + 0.045,
                w=widths[c_index] - 0.12,
                h=row_h - 0.06,
                size=size,
                bold=(r_index == 0 and head),
                color=color,
            )
            cx += widths[c_index]
        rule(s, x=x, y=yy + row_h, w=sum(widths), color=LINE, h=0.008)


def quote(s, value: str, *, x: float, y: float, w: float, h: float = 0.55, size: float = 10) -> None:
    rect(s, x=x, y=y, w=w, h=h, fill=RGBColor(0x14, 0x0A, 0x12), line_color=RED_SOFT, radius=True)
    rect(s, x=x, y=y, w=0.04, h=h, fill=RED, line_color=None)
    text(s, value, x=x + 0.18, y=y + 0.12, w=w - 0.3, h=h - 0.18, size=size, bold=True, color=WHITE)


def chrome(s, page: int, *, scope: str = "P0 PILOT  ·  DOCUMENT WORKSPACE") -> None:
    brand(s)
    scope_tag(s, scope)
    footer(s, page)


def rich(
    s,
    segments: list[tuple[str, RGBColor]],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float,
    bold: bool = True,
    spacing: float = 1.0,
) -> None:
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.line_spacing = spacing
    for value, color in segments:
        run = p.add_run()
        run.text = value
        _font(run, size, bold, color)


def slide_cover(prs: Presentation) -> None:
    s = slide(prs)
    rect(s, x=0, y=0, w=13.333, h=0.045, fill=MINT, line_color=None)
    brand(s)
    scope_tag(s, "P0 PILOT  ·  DEMAND GUARANTEE / STANDBY LC")
    text(s, "FOCUSED PRODUCT DEMO  ·  B2B TRADE DOCUMENTS", x=0.9, y=1.25, w=9.5, h=0.25, size=9.5, bold=True, color=RED)
    rich(
        s,
        [("The trade document workspace\n", WHITE), ("that can prove itself.", RED)],
        x=0.9,
        y=1.72,
        w=10.8,
        h=1.9,
        size=40,
        spacing=1.12,
    )
    text(
        s,
        "Draft, review, approve and hand off a Demand Guarantee with four AI agents, one evidence trail and a human decision at the end.",
        x=0.9,
        y=3.78,
        w=10.6,
        h=0.7,
        size=13.5,
        color=GREY,
    )
    x = 0.9
    for value, width in [
        ("FOUR AGENTS · ONE SNAPSHOT", 3.0),
        ("EVIDENCE BEFORE OPINION", 3.15),
        ("NO SILENT PASS", 2.1),
    ]:
        tag(s, value, x=x, y=4.85, w=width, color=MINT, fill=RGBColor(0x0B, 0x23, 0x1E))
        x += width + 0.16
    rule(s, x=0.9, y=6.2, w=11.5, color=LINE_2)
    text(s, "Demo deck  ·  November 2026  ·  Synthetic data only", x=0.9, y=6.35, w=7, h=0.25, size=9, color=GREY_2)
    text(s, "01 / 15", x=11.8, y=6.35, w=0.9, h=0.25, size=9, color=GREY_2, align=PP_ALIGN.RIGHT)
    notes(
        s,
        "Opening: this is not another chat box. It is a document workspace where every value, finding and approval is tied to a fixed snapshot. "
        "The promise is simple: AI proposes, the deterministic engine verifies, and a human decides. Everything shown today uses synthetic data.",
    )


def slide_scope(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "SCOPE FIRST",
        "Fix the document. Not the payment.",
        "Phase 1 owns the document lifecycle — draft, review, approve and hand off. It does not execute payments, SWIFT messages or legal conclusions.",
    )
    card(
        s,
        x=0.62,
        y=2.08,
        w=3.85,
        h=2.6,
        head="IN SCOPE · P0",
        body="Import PDF/DOCX/images + OCR · rich editor and lock · structured variables · Audit, Legal, Knowledge and Automation agents · two-stage approval · audit trail.",
        tag_text="P0",
        tag_color=MINT,
        border=RGBColor(0x1E, 0x6E, 0x5A),
        accent=MINT,
    )
    card(
        s,
        x=4.74,
        y=2.08,
        w=3.85,
        h=2.6,
        head="OUT OF SCOPE",
        body="No auto sign, issue, pay or SWIFT. No AML/KYC decision. No AI approval or exemption. No global legal coverage. No full CRDT multi-user editing.",
        tag_text="NOT NOW",
        tag_color=RED,
        border=RGBColor(0x6E, 0x16, 0x22),
    )
    card(
        s,
        x=8.86,
        y=2.08,
        w=3.85,
        h=2.6,
        head="DONE MEANS",
        body="Every value traceable to source · every finding has gate type and evidence · every approval bound to one snapshot · every failure visible, never a clean pass.",
        tag_text="DONE",
        tag_color=MINT,
        border=RGBColor(0x1E, 0x6E, 0x5A),
        accent=MINT,
    )
    quote(
        s,
        "The product is allowed to say “I could not assess this”. It is not allowed to say “looks clean” when it did not check.",
        x=0.62,
        y=5.18,
        w=12.08,
        h=0.62,
        size=11,
    )
    text(
        s,
        "Phase 1 pilot document: Demand Guarantee / Standby LC. Synthetic scenarios, approved identities and explicit limitations.",
        x=0.62,
        y=6.0,
        w=11.9,
        h=0.3,
        size=8.5,
        color=GREY_2,
    )
    chrome(s, 2)
    notes(
        s,
        "Scope first: we are not rebuilding the payment engine. We are fixing the document loop that feeds it. "
        "The red box is as important as the green ones: no autonomous execution, no AI approval, no global legal claim. "
        "The pilot document is a Demand Guarantee; all data is synthetic.",
    )
def slide_problem(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "BUSINESS PROBLEM",
        "The work is not writing. It is proving.",
        "A guarantee gets stuck between versions, fields and comments — not because nobody can type.",
    )
    items = [
        ("APPLICANT / TRADE USER", "“Which version is current, what is missing, and what do I do next?”", "A shared snapshot, visible owners and a clear next action."),
        ("BANK OPERATIONS", "Re-keying amounts, dates and party names; chasing the latest attachment.", "Extracted candidates with page/bbox, one confirmation step."),
        ("COMPLIANCE / LEGAL", "“Why is this flagged? Which rule, which clause, which source?”", "Finding-level evidence, rule versions and coverage boundaries."),
        ("MANAGER / AUDITOR", "Approvals bound to the wrong version; no reliable trail.", "Immutable versions, maker-checker, server-side activity."),
    ]
    for index, (head, pain, change) in enumerate(items):
        col = index % 2
        row = index // 2
        x = 0.62 + col * 6.14
        y = 2.02 + row * 1.55
        rect(s, x=x, y=y, w=5.95, h=1.38, fill=CARD, line_color=LINE, radius=True)
        text(s, head, x=x + 0.2, y=y + 0.12, w=5.5, h=0.22, size=8.5, bold=True, color=RED)
        text(s, pain, x=x + 0.2, y=y + 0.38, w=5.5, h=0.36, size=10.5, bold=True, color=WHITE)
        text(s, change, x=x + 0.2, y=y + 0.88, w=5.5, h=0.35, size=8.6, color=GREY)
    quote(
        s,
        "The expensive part is the round trip: which version, which field, who changed it, and why.",
        x=0.62,
        y=5.3,
        w=12.08,
        h=0.6,
        size=11,
    )
    text(
        s,
        "Pilot measures (baseline first): median time to hand-off · round trips per document · re-keying time · suggestion acceptance · false-positive rate · task failure rate.",
        x=0.62,
        y=6.12,
        w=11.9,
        h=0.35,
        size=8.3,
        color=GREY_2,
    )
    chrome(s, 3)
    notes(
        s,
        "Frame the problem around evidence, not typing. Each persona has a different question: which version, which field, why flagged, which approval. "
        "The bottom line is that we measure the baseline before claiming ROI; security and version loss are launch blockers, not efficiency trade-offs.",
    )
def slide_workspace(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "PRODUCT AT A GLANCE",
        "One workspace. Four agents. One snapshot.",
        "The editor is the source of truth; the agents work on the same fixed snapshot and return evidence, not side effects.",
    )
    rect(s, x=0.62, y=2.02, w=7.55, h=4.55, fill=CARD_2, line_color=LINE, radius=True)
    rect(s, x=0.62, y=2.02, w=1.55, h=4.55, fill=RGBColor(0x0A, 0x12, 0x1F), line_color=None)
    text(s, "VERSION HISTORY", x=0.78, y=2.18, w=1.3, h=0.2, size=6.5, bold=True, color=GREY_2)
    for i, (label, meta) in enumerate(
        [("v3 · current", "shared · read-only"), ("v2 · shared", "awaiting review"), ("v1 · baseline", "approved draft")]
    ):
        y = 2.55 + i * 0.75
        rect(s, x=0.78, y=y, w=1.22, h=0.55, fill=CARD, line_color=LINE_2, radius=True)
        text(s, label, x=0.86, y=y + 0.08, w=1.05, h=0.18, size=7.2, bold=True, color=WHITE)
        text(s, meta, x=0.86, y=y + 0.3, w=1.05, h=0.16, size=6, color=GREY_2)
    text(s, "DEMAND GUARANTEE", x=2.4, y=2.2, w=3.2, h=0.25, size=9, bold=True, color=WHITE)
    text(s, "Alpha Tech → Beta Construction", x=2.4, y=2.46, w=3.3, h=0.18, size=6.5, color=GREY_2)
    doc_rows = [
        ("01 / Undertaking", "The aggregate liability shall not exceed {{currency}} {{amount}}."),
        ("02 / Demand and payment", "A demand must identify this guarantee and include a signed statement."),
        ("03 / Expiry", "This guarantee expires on {{expiry}}."),
        ("04 / Document status", "Synthetic working draft · applicable rules subject to human confirmation."),
    ]
    for i, (head, body) in enumerate(doc_rows):
        y = 2.85 + i * 0.82
        text(s, head, x=2.4, y=y, w=3.6, h=0.18, size=7.4, bold=True, color=WHITE)
        text(s, body, x=2.4, y=y + 0.22, w=3.7, h=0.36, size=6.6, color=GREY)
    rect(s, x=6.35, y=2.02, w=1.82, h=4.55, fill=RGBColor(0x0B, 0x18, 0x23), line_color=None)
    text(s, "NEXUS AI", x=6.5, y=2.18, w=1.5, h=0.2, size=7, bold=True, color=RED)
    for i, label in enumerate(["Rule audit", "Knowledge Q&A", "Automation", "Legal advice"]):
        y = 2.55 + i * 0.55
        rect(s, x=6.5, y=y, w=1.5, h=0.42, fill=CARD, line_color=LINE_2, radius=True)
        text(s, label, x=6.58, y=y + 0.12, w=1.35, h=0.18, size=6.8, bold=True, color=WHITE)
    text(s, "Fixed snapshot · evidence · human decides", x=6.5, y=5.0, w=1.55, h=0.5, size=6.2, color=GREY_2)
    agent_cards = [
        ("Automation Agent", "Extract · confirm · variables · rewrite proposals", "PROPOSAL", MINT),
        ("Audit Agent", "Rules · templates · coverage · findings · gate", "DETERMINISTIC", MINT),
        ("Legal Agent", "Applicability · citations · coverage gaps", "ADVISORY", MINT),
        ("Knowledge Assistant", "Explain · cite · refuse · hand off", "EVIDENCE", MINT),
    ]
    for i, (head, body, tag_text, color) in enumerate(agent_cards):
        y = 2.02 + i * 1.12
        rect(s, x=8.55, y=y, w=4.15, h=1.0, fill=CARD, line_color=LINE, radius=True)
        rect(s, x=8.55, y=y, w=0.035, h=1.0, fill=RED if i < 3 else MINT, line_color=None)
        text(s, head, x=8.75, y=y + 0.1, w=2.7, h=0.22, size=9, bold=True, color=WHITE)
        text(s, body, x=8.75, y=y + 0.38, w=3.5, h=0.4, size=7.2, color=GREY)
        tag(s, tag_text, x=11.45, y=y + 0.12, w=1.08, color=color, fill=RGBColor(0x0B, 0x23, 0x1E))
    text(
        s,
        "Mock demo sections: 01 Undertaking · 02 Demand and payment · 03 Expiry · 04 Document status",
        x=0.7,
        y=6.7,
        w=11.5,
        h=0.22,
        size=7.5,
        color=GREY_2,
    )
    chrome(s, 4)
    notes(
        s,
        "This is the product in one picture: the document on the left/center, the four agents on the right, and the same fixed snapshot underneath. "
        "The mock demo uses the four document sections shown here. The right panel is not a chatbot; each agent has a defined job and returns evidence.",
    )
def slide_flow(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "END-TO-END JOURNEY",
        "From upload to hand-off, without losing the thread.",
        "Every step produces a state and an artefact; a version is not an approval, and an AI suggestion is not an edit.",
    )
    steps = [
        ("01", "Ingest", "PDF / DOCX / image / template"),
        ("02", "Parse + OCR", "blocks, pages, errors, losses"),
        ("03", "Extract + confirm", "candidate · source · receipt"),
        ("04", "Edit under lock", "variables · save · conflict"),
        ("05", "Audit + Legal", "snapshot · evidence · gate"),
        ("06", "Submit snapshot", "immutable · lock released"),
        ("07", "Two-stage approval", "maker-checker · no self-approval"),
        ("08", "Hand-off", "approved version + receipt"),
    ]
    x0, y0, step_w, gap = 0.62, 2.0, 1.48, 0.1
    rule(s, x=x0 + 0.2, y=y0 + 0.3, w=11.55, color=LINE)
    for i, (num, head, body) in enumerate(steps):
        x = x0 + i * (step_w + gap)
        color = RED if i in (2, 4, 6) else MINT
        circle = s.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x), Inches(y0 + 0.1), Inches(0.28), Inches(0.28)
        )
        circle.fill.solid()
        circle.fill.fore_color.rgb = color
        circle.line.fill.background()
        text(
            s,
            num,
            x=x,
            y=y0 + 0.15,
            w=0.28,
            h=0.16,
            size=7,
            bold=True,
            color=BG,
            align=PP_ALIGN.CENTER,
        )
        text(s, head, x=x, y=y0 + 0.55, w=step_w, h=0.24, size=8.8, bold=True, color=WHITE)
        text(s, body, x=x, y=y0 + 0.82, w=step_w, h=0.45, size=6.8, color=GREY)
    rows(
        s,
        [
            ["State dimension", "What it means", "What the UI must show"],
            ["Draft", "Autosave does not create a formal version", "Saving / saved / conflict; recovery draft"],
            ["Submitted snapshot", "Immutable content + variables + template version", "Version, content hash, owner, time"],
            ["In review", "Body frozen; comments allowed; lock blocked", "Current stage, reviewer, open findings"],
            ["Approved", "Current target version approved; history preserved", "Approver, decision, timestamp"],
            ["Handed off", "Approved snapshot delivered; not a payment", "Receipt, target, no “paid” claim"],
        ],
        x=0.62,
        y=3.75,
        widths=[2.2, 4.5, 5.3],
        row_h=0.36,
        size=8,
    )
    quote(
        s,
        "A version is not an approval. An AI suggestion is not an edit. A hand-off is not a payment.",
        x=0.62,
        y=6.0,
        w=12.08,
        h=0.55,
        size=10.5,
    )
    chrome(s, 5)
    notes(
        s,
        "Walk the journey left to right. The red dots are the control points: extraction confirmation, audit snapshot and maker-checker approval. "
        "The table is the state semantics from the requirements: draft, submitted, in review, approved, handed off are different events and must never be collapsed into one 'Submit'.",
    )
def slide_editor(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "DOCUMENT EDITOR",
        "The editor is the source. The audit reads a projection.",
        "Formatting is preserved for the human; the deterministic layer reads one stable text projection.",
    )
    rect(s, x=0.62, y=1.98, w=7.7, h=4.5, fill=WHITE, line_color=LINE, radius=True)
    rect(s, x=0.62, y=1.98, w=7.7, h=0.55, fill=RGBColor(0x11, 0x1B, 0x2C), line_color=None)
    text(s, "DEMAND GUARANTEE / STANDBY LC", x=0.85, y=2.12, w=5, h=0.22, size=8.5, bold=True, color=WHITE)
    text(s, "Alpha Tech Ltd. → Beta Construction · Template DEMO-DG / 1.0", x=0.85, y=2.36, w=6, h=0.18, size=6.8, color=GREY)
    sections = [
        ("01 / Undertaking", "At the request of Shenzhen Alpha Tech Ltd., this guarantee is issued in favour of Hanoi Beta Construction.", "The aggregate liability shall not exceed ", "USD 500,000.00", "."),
        ("02 / Demand and payment", "A demand must identify this guarantee and include the Beneficiary's signed statement.", "Payment within a reasonable time after examination.", None, None),
        ("03 / Expiry", "This guarantee expires on ", "12 March 2027", ". Any demand must be received before expiry.", None),
        ("04 / Document status", "Synthetic working draft · governing law and execution details require human confirmation.", None, None, None),
    ]
    y = 2.72
    for head, body, body2, value, tail in sections:
        text(s, head, x=0.9, y=y, w=6.9, h=0.2, size=8, bold=True, color=RED)
        text(s, body, x=0.9, y=y + 0.22, w=6.9, h=0.28, size=7.4, color=RGBColor(0x20, 0x28, 0x33))
        if value:
            text(s, body2 or "", x=0.9, y=y + 0.5, w=3.4, h=0.22, size=7.2, color=RGBColor(0x20, 0x28, 0x33))
            rect(s, x=4.25, y=y + 0.49, w=1.4, h=0.24, fill=RGBColor(0xEF, 0xF4, 0xF8), line_color=RGBColor(0xC8, 0xD4, 0xE0), radius=True)
            text(s, value, x=4.3, y=y + 0.52, w=1.3, h=0.18, size=6.6, bold=True, color=RGBColor(0x8E, 0x08, 0x18))
            if tail:
                text(s, tail, x=5.7, y=y + 0.5, w=1.5, h=0.2, size=7, color=RGBColor(0x20, 0x28, 0x33))
            y += 0.9
        else:
            y += 0.78
    text(s, "v3 · shared snapshot · read-only · lock released", x=0.9, y=6.05, w=6.8, h=0.2, size=6.8, color=GREY_2)
    bullets(
        s,
        [
            ("Import, do not re-type", "PDF / DOCX / JPG / PNG; OCR results stay unconfirmed until a human accepts them."),
            ("One writer at a time", "Server-side lock, fence token, 2-second autosave, conflict recovery; no silent overwrite."),
            ("Immutable versions", "Submit freezes content, variables and template version; approval binds to that snapshot."),
            ("Content boundaries", "Shared text, organisation-private notes and bank-internal notes are separated server-side, not hidden in the DOM."),
        ],
        x=8.65,
        y=2.05,
        w=4.0,
        h=2.9,
        size=8.8,
    )
    quote(s, "Formatting does not change the audit. Text does.", x=8.65, y=5.05, w=4.0, h=0.55, size=10)
    text(s, "Source file kept for verification · every field has page/bbox/span", x=8.65, y=5.75, w=4.0, h=0.4, size=7.5, color=GREY_2)
    chrome(s, 6)
    notes(
        s,
        "The editor is deliberately ordinary: rich text, tables, find/replace, autosave. The important part is what sits underneath: "
        "a server-side lock, immutable snapshots and a single text projection for audit. The mock demo's four sections are 01 Undertaking, 02 Demand and payment, 03 Expiry, 04 Document status.",
    )
def slide_automation(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "AUTOMATION AGENT",
        "Extraction is a proposal, not a write.",
        "The agent finds candidates; the user confirms; the host applies. The original file stays available for verification.",
    )
    card(
        s,
        x=0.62,
        y=1.98,
        w=3.85,
        h=2.35,
        head="1 · EXTRACT",
        body="Applicant, beneficiary, amount, currency, dates, references, addresses. Each candidate carries raw value, normalised candidate, page/bbox and confidence.",
        tag_text="CANDIDATE",
        tag_color=MINT,
        border=RGBColor(0x1E, 0x6E, 0x5A),
        accent=MINT,
    )
    card(
        s,
        x=4.74,
        y=1.98,
        w=3.85,
        h=2.35,
        head="2 · CONFIRM",
        body="The user accepts, corrects or rejects. OCR values remain unconfirmed; a confirmation receipt records who, when, source and reason.",
        tag_text="RECEIPT",
        tag_color=MINT,
        border=RGBColor(0x1E, 0x6E, 0x5A),
        accent=MINT,
    )
    card(
        s,
        x=8.86,
        y=1.98,
        w=3.85,
        h=2.35,
        head="3 · APPLY",
        body="A ChangeProposal shows a real diff and all affected nodes. Apply requires the edit lock, base snapshot and explicit user action; undo is a new revision.",
        tag_text="HOST COMMAND",
        tag_color=RED,
        border=RGBColor(0x6E, 0x16, 0x22),
    )
    flow = [
        ("Source", "file / page / bbox"),
        ("Candidate", "multiple · conflict"),
        ("Confirm", "receipt · human"),
        ("Proposal", "diff · protected facts"),
        ("Apply", "lock · baseline · undo"),
    ]
    x = 0.62
    for i, (head, body) in enumerate(flow):
        w = 2.25 if i < 4 else 2.3
        rect(s, x=x, y=4.72, w=w, h=0.85, fill=CARD_2, line_color=LINE, radius=True)
        text(s, head, x=x + 0.12, y=4.84, w=w - 0.2, h=0.2, size=8.5, bold=True, color=WHITE if i < 4 else MINT)
        text(s, body, x=x + 0.12, y=5.1, w=w - 0.2, h=0.3, size=6.8, color=GREY)
        if i < 4:
            text(s, "→", x=x + w + 0.02, y=5.0, w=0.2, h=0.2, size=12, bold=True, color=RED)
        x += w + 0.12
    bullets(
        s,
        [
            ("Variables", "{{currency}}, {{amount}}, {{expiry}} keep one ID across every occurrence; fill is atomic."),
            ("Rewrite", "polish / replace clause / rewrite text: protected facts stay guarded; a new obligation is a hand-off, not a silent edit."),
            ("External API mapping", "P0 suggestion: map a fixed snapshot to a published target schema, confirm each field, generate a payload draft."),
        ],
        x=0.7,
        y=5.78,
        w=12.0,
        h=0.65,
        size=7.6,
    )
    quote(
        s,
        "Agent never writes. Apply is a host command with lock, baseline and user confirmation.",
        x=0.62,
        y=6.5,
        w=12.08,
        h=0.5,
        size=9.5,
    )
    chrome(s, 7)
    notes(
        s,
        "Automation is where demos usually cheat: the model silently overwrites text. Here the chain is explicit: candidate → confirm → proposal → host apply. "
        "The external API mapping is a P0 suggestion: generate a payload draft, never send it.",
    )
def slide_audit(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "AUDIT AGENT",
        "Audit is deterministic first. Semantic second.",
        "Rules and schemas produce recomputable results; semantic judgement is labelled as judgement, never disguised as a hard failure.",
    )
    metric(s, x=0.62, y=1.98, w=2.75, big="56", label="Base check units", note="schema + rules + evidence")
    metric(s, x=3.47, y=1.98, w=2.75, big="63", label="When template matches", note="+ fields, clauses, declarations")
    metric(s, x=6.32, y=1.98, w=2.75, big="11", label="Published rules", note="pass / finding / needs_input vectors")
    metric(s, x=9.17, y=1.98, w=3.45, big="0", label="Model calls in deterministic path", note="same text + same as_of = same result", color=MINT)
    rows(
        s,
        [
            ["Check family", "Question it answers", "Output"],
            ["Schema", "Is the field present, typed, within length/charset?", "pass / finding / needs_input"],
            ["Cross-field", "Does the amount match the currency and totals?", "pass / finding / needs_input"],
            ["Template + clauses", "Are required / controlled clauses present?", "pass / finding / not_applicable"],
            ["Semantic (advisory)", "Do party, amount or obligation statements conflict?", "finding + evidence anchors"],
            ["Coverage", "What was not assessed, and why?", "unsettled units + reason codes"],
        ],
        x=0.62,
        y=3.45,
        widths=[2.25, 6.1, 3.65],
        row_h=0.36,
        size=8,
    )
    rect(s, x=0.62, y=5.75, w=7.4, h=0.95, fill=CARD, line_color=LINE, radius=True)
    text(s, "A finding is a structured object", x=0.82, y=5.86, w=3.5, h=0.2, size=8, bold=True, color=RED)
    text(
        s,
        "snapshot + rule version + field/field anchor + severity + gate_type + evidence + suggested action + disposition",
        x=0.82,
        y=6.12,
        w=6.9,
        h=0.45,
        size=8,
        color=GREY,
    )
    quote(
        s,
        "No hit ≠ compliant. Missing ≠ pass. Conflict ≠ whoever loaded last wins.",
        x=8.25,
        y=5.75,
        w=4.45,
        h=0.95,
        size=8.8,
    )
    chrome(s, 8)
    notes(
        s,
        "This is the core of the product. Deterministic checks run first and are recomputable; semantic checks are advisory and labelled. "
        "The finding object carries the snapshot, rule version, anchor, gate type and evidence, so a reviewer can answer 'why'. "
        "The counts reflect the current implementation snapshot; the template count applies when the counterparty actually matches.",
    )


def slide_agents(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "LEGAL & KNOWLEDGE",
        "Explain with evidence. Refuse without it.",
        "Two different jobs: Legal assesses applicability; Knowledge explains. Both must show what they did not cover.",
    )
    rect(s, x=0.62, y=1.98, w=5.95, h=4.45, fill=CARD, line_color=LINE, radius=True)
    text(s, "LEGAL AGENT", x=0.85, y=2.15, w=3, h=0.25, size=10, bold=True, color=RED)
    text(s, "Applicability + deterministic rule checks", x=0.85, y=2.45, w=5.3, h=0.3, size=11, bold=True, color=WHITE)
    bullets(
        s,
        [
            ("Coverage profile first", "Jurisdictions, topics, instrument versions and effective dates."),
            ("answer_status gate", "answered / partial → finding; unavailable / unsupported → unable_to_assess."),
            ("Citations", "Article, jurisdiction, effective date, excerpt and chunk id."),
            ("No final legal opinion", "Missing facts or coverage gaps become questions, not a clean conclusion."),
        ],
        x=0.85,
        y=2.9,
        w=5.4,
        h=2.3,
        size=8.3,
    )
    for i, (label, color) in enumerate([("FINDING", RED), ("PASS", MINT), ("UNABLE TO ASSESS", GREY_2)]):
        tag(s, label, x=0.85 + i * 1.65, y=5.45, w=1.55, color=color, fill=RGBColor(0x0B, 0x23, 0x1E) if color == MINT else RGBColor(0x2A, 0x0A, 0x10))
    rect(s, x=6.75, y=1.98, w=5.95, h=4.45, fill=CARD, line_color=LINE, radius=True)
    text(s, "KNOWLEDGE ASSISTANT", x=6.98, y=2.15, w=3.5, h=0.25, size=10, bold=True, color=MINT)
    text(s, "Product FAQ · trade rules · document selection", x=6.98, y=2.45, w=5.4, h=0.3, size=11, bold=True, color=WHITE)
    bullets(
        s,
        [
            ("Claim-level evidence", "Each factual claim is bound to one or more retrieved sources."),
            ("Support level", "strong / qualified / insufficient / not applicable — never a fixed “high confidence”."),
            ("Hand-off, not hand-wave", "“Rewrite this clause” returns needs_handoff; the assistant does not edit."),
            ("Snapshot-bound", "Changing the document requires a new session; old answers do not silently follow."),
        ],
        x=6.98,
        y=2.9,
        w=5.4,
        h=2.3,
        size=8.3,
    )
    quote(
        s,
        "AI can explain. It cannot approve, edit, or exempt.",
        x=6.98,
        y=5.45,
        w=5.4,
        h=0.55,
        size=9.5,
    )
    text(
        s,
        "Source types are always separated: statute · standard · internal policy · customer document · model explanation.",
        x=0.85,
        y=6.15,
        w=11.7,
        h=0.25,
        size=7.5,
        color=GREY_2,
    )
    chrome(s, 9)
    notes(
        s,
        "Legal and Knowledge are deliberately separate. Legal assesses whether a rule applies and gives coverage-bounded advice; Knowledge explains rules and documents with claim-level citations. "
        "Both share the same honesty rule: if evidence or coverage is missing, say unable_to_assess or insufficient, never pass.",
    )
def slide_control(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "MACHINE REVIEWER & GATE",
        "AI proposes. The engine verifies. The human decides.",
        "The agent never holds a document, approval or exemption permission. The host command layer is the only write path.",
    )
    rect(s, x=0.62, y=1.98, w=5.9, h=2.65, fill=RGBColor(0x14, 0x0A, 0x12), line_color=RED_SOFT, radius=True)
    text(s, "FIVE RED LINES", x=0.85, y=2.12, w=3, h=0.25, size=9.5, bold=True, color=RED)
    bullets(
        s,
        [
            ("No autonomous release or payment", "The agent cannot submit, sign or send SWIFT."),
            ("No silent fact change", "Amounts, dates, parties and obligations are protected."),
            ("No AML / legal conclusion", "It can flag and ask; it cannot decide."),
            ("No external message", "No customer or bank message is sent by the model."),
            ("No “looks certain” when evidence is missing", "Unknown stays unknown."),
        ],
        x=0.85,
        y=2.5,
        w=5.35,
        h=1.95,
        size=7.8,
    )
    rect(s, x=6.7, y=1.98, w=6.0, h=2.65, fill=RGBColor(0x0B, 0x18, 0x1E), line_color=RGBColor(0x1E, 0x6E, 0x5A), radius=True)
    text(s, "HOW IT IS ENFORCED", x=6.93, y=2.12, w=3.5, h=0.25, size=9.5, bold=True, color=MINT)
    bullets(
        s,
        [
            ("Allow-listed tools + JSON schema", "No arbitrary URL, shell or database access."),
            ("Reader / writer separation", "The agent service has no document write or approval permission."),
            ("Max steps + retry budget", "Bounded runs; one repair, then abstain or hand off."),
            ("Sensitive-field switch", "Amount, account, address or party change forces human review."),
            ("Audit", "Prompt/model/version, output, decision and evidence are recorded."),
        ],
        x=6.93,
        y=2.5,
        w=5.55,
        h=1.95,
        size=7.8,
    )
    rows(
        s,
        [
            ["Action", "Agent", "Maker (document owner)", "Checker / risk owner"],
            ["Read snapshot + evidence", "Allowed", "Can verify", "Can audit"],
            ["Generate suggestion", "Allowed", "Must review / confirm", "Reviews against policy"],
            ["Modify sensitive field or send", "Forbidden", "Only via authorised host command", "Approves under policy"],
            ["High risk or evidence conflict", "Must hand off", "Supplies evidence", "Retains final decision"],
        ],
        x=0.62,
        y=4.85,
        widths=[4.15, 2.0, 3.1, 2.85],
        row_h=0.3,
        size=7.8,
        colors=[WHITE, MINT, WHITE, WHITE],
    )
    quote(
        s,
        "The gate is a server-side function. A browser cannot send “approved = true”.",
        x=0.62,
        y=6.4,
        w=12.08,
        h=0.5,
        size=9.5,
    )
    chrome(s, 10)
    notes(
        s,
        "This slide answers the trust question. The left column is what the agent can never do; the right column is how the architecture enforces it. "
        "The table is the maker-checker model: the agent prepares, the document owner confirms, the checker/risk owner decides. The gate is re-evaluated server-side for the exact version being submitted.",
    )


def slide_trust(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "TRUST & ACCESS",
        "A lawyer’s badge is not a permission.",
        "Access is the intersection of organisation, trade workspace, document grant and content layer — never a client-declared role.",
    )
    layers = [
        ("ORGANISATION", "Bank / company / law firm; verified membership; active role.", "identity + membership"),
        ("TRADE WORKSPACE", "Participant organisations, document set, jurisdiction and business metadata.", "workspace grant"),
        ("DOCUMENT", "Document-level grant: read, comment, edit, export, AI.", "per-document ACL"),
        ("CONTENT LAYER", "Shared · organisation-private · bank-internal.", "server-side isolation"),
    ]
    for i, (head, body, meta) in enumerate(layers):
        x = 0.62 + i * 3.05
        rect(s, x=x, y=2.0, w=2.85, h=1.75, fill=CARD, line_color=LINE, radius=True)
        tag(s, f"LAYER {i+1}", x=x + 0.16, y=2.12, w=0.75, color=MINT, fill=RGBColor(0x0B, 0x23, 0x1E))
        text(s, head, x=x + 0.16, y=2.48, w=2.5, h=0.22, size=8.5, bold=True, color=WHITE)
        text(s, body, x=x + 0.16, y=2.75, w=2.5, h=0.65, size=7.2, color=GREY)
        text(s, meta, x=x + 0.16, y=3.42, w=2.5, h=0.18, size=6.4, color=GREY_2)
    bullets(
        s,
        [
            ("External lawyer / guest", "Default: read + comment on named documents only; edit, download, export and AI are separate grants."),
            ("Revocation is immediate", "Expiry or removal blocks new reads, edits, citations and AI calls; persisted drafts are preserved."),
            ("Internal notes stay internal", "Server-side isolation, not hidden DOM; they never enter external search, AI context, diffs or exports."),
            ("Lock + fencing", "One writer at a time; old sessions cannot overwrite a newer draft; force-unlock needs review."),
            ("Audit trail", "Login, lock, submit, AI run, finding decision, approval and permission change are server-side events."),
        ],
        x=0.75,
        y=4.1,
        w=11.8,
        h=2.1,
        size=8.5,
    )
    quote(
        s,
        "Permissions are checked before retrieval, before generation, before publication and again when a citation is opened.",
        x=0.62,
        y=6.35,
        w=12.08,
        h=0.5,
        size=9.2,
    )
    chrome(s, 11)
    notes(
        s,
        "Security is not a disclaimer. The four layers are independent: being a lawyer does not grant edit or AI access; a guest grant is scoped to named documents. "
        "Revocation is server-side and immediate, and internal notes never enter the external layer.",
    )
def slide_architecture(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "SOLUTION DESIGN",
        "Modular monolith now. Production seams built in.",
        "The same document snapshot flows through every agent; only the host command layer can write.",
    )
    boxes = [
        (0.62, 2.0, 2.2, 1.25, "UI", "TipTap editor\nVersion history\nNexus AI panel", MINT),
        (3.05, 2.0, 2.55, 1.25, "API + Orchestrator", "FastAPI · Pydantic\nAuth · snapshot · job\nOpenAPI client", WHITE),
        (5.85, 2.0, 2.55, 1.25, "Four agents", "Automation · Audit\nLegal · Knowledge\nread-only service identity", WHITE),
        (8.65, 2.0, 2.35, 1.25, "Reviewer + Publisher", "Machine review\neligibility checks\natomic publish", WHITE),
        (11.25, 2.0, 1.45, 1.25, "Data", "Postgres\nobject store\noutbox", MINT),
    ]
    for x, y, w, h, head, body, color in boxes:
        rect(s, x=x, y=y, w=w, h=h, fill=CARD, line_color=LINE, radius=True)
        text(s, head, x=x + 0.14, y=y + 0.12, w=w - 0.25, h=0.28, size=8.8, bold=True, color=color)
        text(s, body, x=x + 0.14, y=y + 0.46, w=w - 0.25, h=0.65, size=6.8, color=GREY)
    for x in (2.82, 5.6, 8.4, 11.0):
        text(s, "→", x=x, y=2.45, w=0.25, h=0.2, size=12, bold=True, color=RED)
    rect(s, x=0.62, y=3.55, w=12.08, h=1.3, fill=RGBColor(0x0B, 0x18, 0x23), line_color=RGBColor(0x1E, 0x6E, 0x5A), radius=True)
    text(s, "HOST COMMAND LAYER", x=0.85, y=3.68, w=2.8, h=0.22, size=8.5, bold=True, color=MINT)
    text(s, "Document edit · apply proposal · submit version · approve · hand off", x=3.4, y=3.68, w=5.8, h=0.22, size=8.2, color=WHITE)
    text(s, "GateEvaluator re-checks the exact target version and policy before any protected action.", x=0.85, y=4.0, w=11.2, h=0.5, size=7.5, color=GREY)
    bullets(
        s,
        [
            ("Async by design", "Persist the job with the business record; claim with FOR UPDATE SKIP LOCKED; idempotent retries."),
            ("No agent DB / write access", "Agents read an authorised snapshot and publish a proposal; host commands own all writes."),
            ("Model gateway is optional", "Approved provider + egress policy; missing provider fails loudly, never substitutes fixture."),
            ("Outbox + audit", "Publication, notification and audit events are committed with the result."),
        ],
        x=0.75,
        y=5.0,
        w=11.8,
        h=1.45,
        size=8.2,
    )
    quote(
        s,
        "Same snapshot · same policy · same as_of → same deterministic result.",
        x=0.62,
        y=6.55,
        w=12.08,
        h=0.48,
        size=9.2,
    )
    chrome(s, 12)
    notes(
        s,
        "Architecture is a modular monolith, not a microservice zoo. The four agents share the same snapshot and are read-only; the host command layer is the only writer. "
        "The job table uses FOR UPDATE SKIP LOCKED, and every publication writes audit/outbox in the same transaction.",
    )


def slide_demo(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "THE DEMO",
        "12 minutes, one evidence trail.",
        "Open the mock, run the loop, then show what happens when a service cannot answer.",
    )
    steps = [
        ("01  1 min", "Set the scene", "Open Demand Guarantee v3. Point at version, role, lock and snapshot."),
        ("02  3 min", "Import + confirm", "Upload a DOCX/PDF; show OCR as unconfirmed; accept a candidate and show source page."),
        ("03  2 min", "Edit under lock", "Insert {{currency}} {{amount}} {{expiry}}; save; simulate a conflict and recover."),
        ("04  3 min", "Audit + legal", "Run Audit: deterministic pass/finding + semantic sample. Open a finding and its coverage."),
        ("05  2 min", "Ask with evidence", "Knowledge: product/rule question with citations. Legal: applicability with coverage gap."),
        ("06  1 min", "Approve + hand off", "Submit snapshot, two-stage approval, hand-off receipt; show the audit trail."),
    ]
    for i, (time, head, body) in enumerate(steps):
        col = i % 2
        row = i // 2
        x = 0.62 + col * 6.14
        y = 1.98 + row * 1.35
        rect(s, x=x, y=y, w=5.95, h=1.18, fill=CARD, line_color=LINE, radius=True)
        text(s, time, x=x + 0.18, y=y + 0.12, w=0.95, h=0.2, size=7.5, bold=True, color=RED)
        text(s, head, x=x + 1.15, y=y + 0.1, w=4.6, h=0.24, size=9.5, bold=True, color=WHITE)
        text(s, body, x=x + 1.15, y=y + 0.4, w=4.6, h=0.65, size=7.3, color=GREY)
    rect(s, x=0.62, y=6.05, w=7.5, h=0.65, fill=RGBColor(0x14, 0x0A, 0x12), line_color=RED_SOFT, radius=True)
    text(s, "If a service fails: show unable_to_assess and continue manual editing.", x=0.82, y=6.18, w=7.1, h=0.35, size=8.5, bold=True, color=WHITE)
    text(s, "Point at: version chip · page/bbox · gate type · coverage gap · unknown reason · audit trail", x=8.3, y=6.15, w=4.4, h=0.4, size=7, color=GREY_2)
    chrome(s, 13)
    notes(
        s,
        "Keep the demo to 12 minutes. The mock HTML is the fastest path: Demand Guarantee v3, four sections, right-side agents. "
        "If a service is unavailable, do not improvise a pass: show unable_to_assess and continue editing. That is the product behavior.",
    )
def slide_status(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "CURRENT BUILD",
        "Demo-ready today. Production seams are explicit.",
        "No production claim: the local host is SQLite, some surfaces are fixture/mock, and every gap is labelled.",
    )
    rows(
        s,
        [
            ["Capability", "What is demo-ready now", "What comes next"],
            ["Editor · import · lock · versions", "Rich text, PDF/DOCX/image import, autosave, conflict recovery, snapshots", "Approved identity, PG host, multi-instance"],
            ["Audit Agent", "Deterministic rules, templates, company pack, coverage, gate, as_of", "Semantic advisory, PG persistence, more rule packs"],
            ["Legal Agent", "L1: statute advice + deterministic rule check, honest failure", "Full DSL, async worker, coverage expansion"],
            ["Knowledge Assistant", "Fixture corpus, claim citations, support levels, refusal", "Vector/PG, approved sources, evaluation loop"],
            ["Automation Agent", "Extract/confirm/variables/rewrite proposals; external mapping preview", "Server persistence, real downstream send, worker"],
            ["Approval · access · audit", "PG identity, two-stage approval, read-only, activity", "Notifications, delegation, real hand-off"],
        ],
        x=0.62,
        y=1.98,
        widths=[3.2, 5.4, 3.5],
        row_h=0.48,
        size=7.6,
    )
    quote(
        s,
        "The demo shows capability and honesty. It does not claim production SLA, global legal coverage or autonomous execution.",
        x=0.62,
        y=5.55,
        w=12.08,
        h=0.58,
        size=9.5,
    )
    text(
        s,
        "Current regression: 830 backend tests · 540 frontend tests · typecheck/build clean · OpenSpec strict validation.",
        x=0.62,
        y=6.35,
        w=11.8,
        h=0.25,
        size=7.5,
        color=GREY_2,
    )
    chrome(s, 14)
    notes(
        s,
        "Be explicit about the boundary. The editor, audit, knowledge and approval surfaces are demo-ready; Legal is L1; Automation is local/mock; the host is still SQLite. "
        "Do not let a successful demo imply production SLA or full legal coverage. The next column is the honest roadmap.",
    )


def slide_roadmap(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "ROADMAP",
        "P0 pilot → production seams → scale.",
        "The shortest path to customer value is server persistence, a real worker and an evaluation loop — not more chat.",
    )
    columns = [
        (
            "NOW · PILOT",
            MINT,
            [
                "Document loop: import, edit, lock, versions",
                "Deterministic audit + templates + gate",
                "Knowledge + Legal L1 with citations",
                "Automation proposals + external mapping preview",
                "PG identity + two-stage approval",
            ],
        ),
        (
            "NEXT · PRODUCTION SEAMS",
            RED,
            [
                "Server-side templates and API registry",
                "PG job queue + worker + leases",
                "Real downstream send / receipt / idempotency",
                "LLM advisory: rewrite, extract, mapping",
                "Evaluation set + cost / quality metrics",
            ],
        ),
        (
            "LATER · SCALE",
            GREY_2,
            [
                "Vector / rerank and broader statute coverage",
                "Multi-tenant isolation and observability",
                "Approval gate consumes AI findings",
                "More instruments and jurisdictions",
                "SLA, backup/restore and DR exercises",
            ],
        ),
    ]
    for i, (head, color, items) in enumerate(columns):
        x = 0.62 + i * 4.05
        rect(s, x=x, y=1.98, w=3.85, h=3.55, fill=CARD, line_color=LINE, radius=True)
        rect(s, x=x, y=1.98, w=3.85, h=0.07, fill=color, line_color=None)
        text(s, head, x=x + 0.2, y=2.18, w=3.4, h=0.25, size=9.5, bold=True, color=color)
        for j, item in enumerate(items):
            text(s, f"•  {item}", x=x + 0.2, y=2.6 + j * 0.52, w=3.45, h=0.42, size=7.6, color=WHITE if i < 2 else GREY)
    quote(
        s,
        "AI proposes. The engine verifies. The human decides.",
        x=0.62,
        y=5.75,
        w=7.4,
        h=0.65,
        size=12,
    )
    text(s, "Q & A", x=8.6, y=5.8, w=3.9, h=0.4, size=24, bold=True, color=RED, align=PP_ALIGN.RIGHT)
    text(
        s,
        "Synthetic data only · no production claim · evidence available on request",
        x=8.6,
        y=6.3,
        w=3.9,
        h=0.25,
        size=7,
        color=GREY_2,
        align=PP_ALIGN.RIGHT,
    )
    chrome(s, 15)
    notes(
        s,
        "Close on the roadmap and the principle. Now is the pilot loop; next is production seams; later is scale. "
        "The quote is the product contract: AI proposes, the engine verifies, the human decides. Open the floor for questions.",
    )


def build() -> Path:
    prs = deck()
    slide_cover(prs)
    slide_scope(prs)
    slide_problem(prs)
    slide_workspace(prs)
    slide_flow(prs)
    slide_editor(prs)
    slide_automation(prs)
    slide_audit(prs)
    slide_agents(prs)
    slide_control(prs)
    slide_trust(prs)
    slide_architecture(prs)
    slide_demo(prs)
    slide_status(prs)
    slide_roadmap(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")