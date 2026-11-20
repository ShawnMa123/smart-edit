#!/usr/bin/env python3
"""Generate the smart-edit demo deck (`docs/demo/smart-edit-demo.pptx`).

Requires python-pptx (not a project dependency; install once):

    uv pip install --python .venv/bin/python python-pptx

Design language: HSBC-inspired editorial deck — ink, white, one red accent, hairline rules,
generous whitespace, timeline markers. No logos or brand assets are copied.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo" / "smart-edit-demo.pptx"

INK = RGBColor(0x1A, 0x1A, 0x1A)
INK_SOFT = RGBColor(0x33, 0x33, 0x33)
RED = RGBColor(0xDB, 0x00, 0x11)
RED_DARK = RGBColor(0xA3, 0x00, 0x0D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
MIST = RGBColor(0xF6, 0xF5, 0xF2)
PAPER = RGBColor(0xFC, 0xFB, 0xF9)
BORDER = RGBColor(0xD9, 0xDE, 0xE0)
MUTED = RGBColor(0x5B, 0x66, 0x72)
GREEN = RGBColor(0x1F, 0x7A, 0x4D)
AMBER = RGBColor(0x8A, 0x5A, 0x00)

FONT = "PingFang SC"
MONO = "Menlo"
W = Inches(13.333)
H = Inches(7.5)


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    return prs


def slide(prs: Presentation, *, dark: bool = False):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = INK if dark else PAPER
    return s


def _apply_font(run, *, size: float, bold: bool, color: RGBColor, font: str = FONT) -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    # PowerPoint uses a separate East-Asian typeface; set it so Chinese does not fall back oddly.
    rpr = run._r.get_or_add_rPr()
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = rpr.makeelement(qn("a:ea"), {})
        rpr.append(ea)
    ea.set("typeface", font)


def text(
    s,
    value: str,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 16,
    bold: bool = False,
    color: RGBColor = INK,
    font: str = FONT,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    spacing: float = 1.08,
) -> None:
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    run = p.add_run()
    run.text = value
    _apply_font(run, size=size, bold=bold, color=color, font=font)


def rect(
    s,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: RGBColor = WHITE,
    line: RGBColor | None = BORDER,
    radius: bool = False,
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
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(0.75)
    shape.shadow.inherit = False


def line(s, *, x: float, y: float, w: float, color: RGBColor = BORDER, height: float = 0.012) -> None:
    rect(s, x=x, y=y, w=w, h=height, fill=color, line=None)


def kicker(s, value: str, *, dark: bool = False) -> None:
    text(
        s,
        value.upper(),
        x=0.7,
        y=0.46,
        w=9,
        h=0.3,
        size=11,
        bold=True,
        color=RED if not dark else RED,
    )


def title(s, value: str, *, y: float = 0.82, color: RGBColor = INK, size: float = 30) -> None:
    text(s, value, x=0.7, y=y, w=11.9, h=0.9, size=size, bold=True, color=color)


def subtitle(s, value: str, *, y: float = 1.62, color: RGBColor = MUTED, size: float = 14) -> None:
    text(s, value, x=0.7, y=y, w=11.9, h=0.7, size=size, color=color)


def footer(s, page: int, *, dark: bool = False) -> None:
    line(s, x=0.7, y=7.02, w=11.93, color=RGBColor(0x3A, 0x3A, 0x3A) if dark else BORDER)
    text(
        s,
        "smart-edit ·  产品 Demo",
        x=0.7,
        y=7.1,
        w=5,
        h=0.25,
        size=9,
        color=RGBColor(0xB9, 0xB9, 0xB9) if dark else MUTED,
    )
    text(
        s,
        f"{page:02d}",
        x=11.9,
        y=7.1,
        w=0.7,
        h=0.25,
        size=9,
        color=RGBColor(0xB9, 0xB9, 0xB9) if dark else MUTED,
        align=PP_ALIGN.RIGHT,
    )


def bullets(
    s,
    items: list[tuple[str, str]],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 15,
    dark: bool = False,
) -> None:
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for index, (head, body) in enumerate(items):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.space_after = Pt(8)
        p.line_spacing = 1.08
        run = p.add_run()
        run.text = "•  "
        _apply_font(run, size=size, bold=True, color=RED)
        run = p.add_run()
        run.text = head
        _apply_font(run, size=size, bold=True, color=WHITE if dark else INK)
        if body:
            run = p.add_run()
            run.text = f"  {body}"
            _apply_font(
                run,
                size=size,
                bold=False,
                color=RGBColor(0xC9, 0xC9, 0xC9) if dark else MUTED,
            )


def badge(s, value: str, *, x: float, y: float, w: float, color: RGBColor = RED) -> None:
    rect(s, x=x, y=y, w=w, h=0.28, fill=color, line=None, radius=True)
    text(
        s,
        value,
        x=x,
        y=y + 0.035,
        w=w,
        h=0.2,
        size=9,
        bold=True,
        color=WHITE,
        align=PP_ALIGN.CENTER,
    )


def card(
    s,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    head: str,
    body: str,
    tag: str | None = None,
    tag_color: RGBColor = RED,
) -> None:
    rect(s, x=x, y=y, w=w, h=h, fill=WHITE, line=BORDER, radius=True)
    rect(s, x=x, y=y, w=0.04, h=h, fill=RED, line=None)
    text(s, head, x=x + 0.22, y=y + 0.2, w=w - 0.4, h=0.4, size=15, bold=True)
    text(s, body, x=x + 0.22, y=y + 0.68, w=w - 0.4, h=h - 0.9, size=12, color=MUTED)
    if tag:
        badge(s, tag, x=x + w - 1.45, y=y + 0.18, w=1.2, color=tag_color)


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
    rect(s, x=x, y=y, w=w, h=1.35, fill=WHITE, line=BORDER, radius=True)
    text(s, big, x=x + 0.18, y=y + 0.18, w=w - 0.36, h=0.55, size=26, bold=True, color=color)
    text(s, label, x=x + 0.18, y=y + 0.74, w=w - 0.36, h=0.26, size=12, bold=True)
    if note:
        text(s, note, x=x + 0.18, y=y + 1.0, w=w - 0.36, h=0.25, size=10, color=MUTED)


def notes(s, value: str) -> None:
    s.notes_slide.notes_text_frame.text = value


def header(s, kick: str, head: str, sub: str | None = None, *, dark: bool = False) -> None:
    kicker(s, kick, dark=dark)
    title(s, head, y=0.78, size=28, color=WHITE if dark else INK)
    if sub:
        text(
            s,
            sub,
            x=0.7,
            y=1.34,
            w=11.9,
            h=0.42,
            size=13,
            color=RGBColor(0xC9, 0xC9, 0xC9) if dark else MUTED,
        )
    line(s, x=0.7, y=1.8, w=11.93, color=RGBColor(0x3A, 0x3A, 0x3A) if dark else BORDER)


def slide_cover(prs: Presentation) -> None:
    s = slide(prs, dark=True)
    rect(s, x=0, y=0, w=0.18, h=7.5, fill=RED, line=None)
    text(s, "SMART-EDIT", x=0.9, y=0.9, w=5, h=0.45, size=14, bold=True, color=RED)
    text(
        s,
        "让保函从「能编辑」\n到「可审计、可交付」",
        x=0.9,
        y=1.75,
        w=9.8,
        h=2.2,
        size=42,
        bold=True,
        color=WHITE,
        spacing=1.15,
    )
    text(
        s,
        "AI 做建议，人做决定。每一句话都有出处，每一次不确定都明确说出来。",
        x=0.9,
        y=4.2,
        w=9.5,
        h=0.7,
        size=17,
        color=RGBColor(0xC9, 0xC9, 0xC9),
    )
    line(s, x=0.9, y=5.35, w=5.2, color=RGBColor(0x4A, 0x4A, 0x4A))
    text(s, "产品 Demo · 2026 年 11 月", x=0.9, y=5.55, w=6, h=0.4, size=14, color=WHITE)
    text(
        s,
        "导入  ·  标准化  ·  规范审计  ·  知识问答  ·  Legal  ·  Automation  ·  审批",
        x=0.9,
        y=6.15,
        w=11.5,
        h=0.5,
        size=12,
        color=RGBColor(0xB9, 0xB9, 0xB9),
    )
    notes(
        s,
        "开场：这份产品不是再做一个聊天框，而是把一份保函从原始材料到可提交版本之间的重复动作，"
        "放进一个有出处、有规则、有审批的工作台。今天重点演示三件事：字段从当前文本读出来、审计能解释、"
        "不确定的时候系统不会假装通过。",
    )


def slide_problem(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "WHY NOW", "一份保函，为什么还在靠人扛？", "工具很多，但“读完、抄对、审清楚、能交付”仍然断在四处。")
    card(
        s,
        x=0.7,
        y=1.9,
        w=3.8,
        h=2.2,
        head="材料散",
        body="邮件正文、PDF、Word、扫描件混在一起；格式、页眉页脚、表格各不相同。",
        tag="INPUT",
    )
    card(
        s,
        x=4.75,
        y=1.9,
        w=3.8,
        h=2.2,
        head="字段靠手抄",
        body="金额、币种、日期、主体、保函号反复复制；错一个数字就要返工。",
        tag="EXTRACT",
    )
    card(
        s,
        x=8.8,
        y=1.9,
        w=3.8,
        h=2.2,
        head="标准不一致",
        body="客户模板、银行规则、公司政策各说各话；人记不住，换人就更难。",
        tag="AUDIT",
    )
    rect(s, x=0.7, y=4.55, w=11.9, h=1.55, fill=WHITE, line=BORDER, radius=True)
    rect(s, x=0.7, y=4.55, w=0.05, h=1.55, fill=RED, line=None)
    text(
        s,
        "更危险的是：很多工具只给一个绿色结论，却不告诉你「检查了什么、值从哪来、哪里没检查」。",
        x=1.0,
        y=4.8,
        w=11.2,
        h=0.6,
        size=18,
        bold=True,
    )
    text(
        s,
        "在贸易金融里，“看起来通过”比“明确无法评估”更昂贵。",
        x=1.0,
        y=5.5,
        w=11.2,
        h=0.4,
        size=14,
        color=MUTED,
    )
    footer(s, 2)
    notes(
        s,
        "先对齐痛点：不是客户不会写保函，而是材料散、字段手抄、标准靠人记。"
        "最危险的是工具把“没检查”包装成“没问题”。这就是我们做确定性和 provenance 的原因。",
    )


def slide_value(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "VALUE", "一页看懂：客户得到什么", "不是“又一个 AI 按钮”，而是三个可验证的结果。")
    metric(s, x=0.7, y=1.9, w=3.8, big="少手抄", label="字段从当前文档读出来", note="span / page / confidence 可回溯", color=INK)
    metric(s, x=4.75, y=1.9, w=3.8, big="少出错", label="规则 / 模板 / 公司包确定性审计", note="missing、needs_input、pass 严格区分", color=INK)
    metric(s, x=8.8, y=1.9, w=3.8, big="可交付", label="版本冻结 + 两级审批 + 留痕", note="谁提交、谁批准、依据是什么", color=INK)
    bullets(
        s,
        [
            ("可解释", "每个 finding 都有字段、规则、阻塞动作和证据"),
            ("可重放", "同一文本 + 同一 as_of + 同一策略版本 → 同一结论"),
            ("可控", "AI 只给建议；不能写 review pass，不能自动 apply"),
        ],
        x=0.9,
        y=4.0,
        w=11.5,
        h=2.2,
        size=16,
    )
    footer(s, 3)
    notes(
        s,
        "客户价值用三个词：少手抄、少出错、可交付。下面每条都要能落到界面或报告里，"
        "不是泛泛说 AI 提效。可解释、可重放、可控是我们和普通文档 AI 的差别。",
    )
def slide_panorama(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "PRODUCT", "一个工作台，四类 AI 能力", "中间编辑、左侧版本、右侧助手；所有结论回到同一份文本快照。")
    card(
        s,
        x=0.7,
        y=1.85,
        w=5.8,
        h=1.85,
        head="Rule audit · 规范审计",
        body="规则 + 客户模板 + 公司策略；coverage / findings / gate / as_of，全部可解释。",
        tag="可用",
        tag_color=GREEN,
    )
    card(
        s,
        x=6.75,
        y=1.85,
        w=5.8,
        h=1.85,
        head="Knowledge Q&A · 知识问答",
        body="产品 / 规则 / 内部政策解释；Claim 级引用、support level、明确弃答。",
        tag="可用",
        tag_color=GREEN,
    )
    card(
        s,
        x=0.7,
        y=3.9,
        w=5.8,
        h=1.85,
        head="Legal advice · 法律建议",
        body="法规问答 + 确定性规则检查；引用可追溯，失败不伪装成“无发现”。",
        tag="L1",
        tag_color=AMBER,
    )
    card(
        s,
        x=6.75,
        y=3.9,
        w=5.8,
        h=1.85,
        head="Automation · 自动化工作台",
        body="模板、变量、下游 OpenAPI 映射、JSON 预览；当前 fixture/local。",
        tag="FIXTURE",
        tag_color=AMBER,
    )
    rect(s, x=0.7, y=6.0, w=11.9, h=0.75, fill=WHITE, line=None, radius=True)
    text(
        s,
        "共同底座：富文本编辑 · 服务端草稿 · 版本历史 · 审批 · Activity · 组织/角色",
        x=0.95,
        y=6.18,
        w=11.4,
        h=0.35,
        size=13,
        bold=True,
        color=INK,
    )
    footer(s, 4)
    notes(
        s,
        "四个能力不要平铺讲。先讲共同底座：同一份文本快照、同一套版本和审批。"
        "再讲四个能力各自解决什么。Legal 是 L1，Automation 是 fixture/local，这两点主动说明。",
    )


def slide_flow(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "FLOW", "端到端：从原始材料到可交付版本", "每一步都有输入、输出和失败状态，不把“没跑”藏在成功里。")
    steps = [
        ("01", "导入", "PDF / DOCX / 图片 / 文本"),
        ("02", "Parse", "block + 页码 + 错误"),
        ("03", "Extract", "profile / fixture / 模型"),
        ("04", "Normalize", "类型 + 出处 + 三态"),
        ("05", "Audit", "规则 + 模板 + as_of"),
        ("06", "人复核", "findings + 引用"),
        ("07", "提交/审批", "冻结 + 两级审批"),
    ]
    x0, y0, step_w, gap = 0.7, 2.05, 1.62, 0.12
    line(s, x=x0 + 0.2, y=y0 + 0.48, w=11.4, color=BORDER, height=0.02)
    for index, (number, head, body) in enumerate(steps):
        x = x0 + index * (step_w + gap)
        circle = s.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x + 0.52), Inches(y0 + 0.28), Inches(0.38), Inches(0.38)
        )
        circle.fill.solid()
        circle.fill.fore_color.rgb = RED if index in (2, 4) else INK
        circle.line.fill.background()
        text(
            s,
            number,
            x=x + 0.52,
            y=y0 + 0.34,
            w=0.38,
            h=0.2,
            size=9,
            bold=True,
            color=WHITE,
            align=PP_ALIGN.CENTER,
        )
        text(s, head, x=x, y=y0 + 0.85, w=step_w, h=0.3, size=13, bold=True, align=PP_ALIGN.CENTER)
        text(s, body, x=x, y=y0 + 1.2, w=step_w, h=0.7, size=10, color=MUTED, align=PP_ALIGN.CENTER)
    rect(s, x=0.7, y=4.55, w=11.9, h=1.55, fill=WHITE, line=BORDER, radius=True)
    text(s, "关键控制点", x=0.95, y=4.75, w=3, h=0.3, size=13, bold=True, color=RED)
    bullets(
        s,
        [
            ("审计只读纯文本投影", "改格式不改结论；改文字才改结论"),
            ("字段必须可回原文", "file / page / bbox / span / form_label"),
            ("失败状态独立", "missing / needs_input / unable_to_assess / failed 不合并"),
        ],
        x=0.95,
        y=5.1,
        w=11.2,
        h=1.0,
        size=12,
    )
    footer(s, 5)
    notes(
        s,
        "这一页讲全链路。重点是控制点：审计读纯文本、字段可回原文、失败状态独立。"
        "Demo 时不需要每一步都点，但报告里能看到每个 stage 的状态。",
    )
def slide_editor(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "EDITOR", "导入与编辑：先让人愿意用", "富文本不是装饰，它让客户敢改；审计仍然只读纯文本。")
    bullets(
        s,
        [
            ("PDF / DOCX / 图片 / 文本", "带文本层、扫描件 OCR、DOCX 只读 OOXML 不执行宏"),
            ("富文本编辑", "标题、粗斜体、列表、表格、查找替换"),
            ("服务端草稿 + 自动保存", "If-Match revision + 编辑锁 + 冲突恢复"),
            ("版本历史 + 只读", "提交后冻结，审批期间不可编辑"),
        ],
        x=0.8,
        y=1.9,
        w=6.4,
        h=3.8,
        size=15,
    )
    rect(s, x=7.55, y=1.85, w=5.0, h=4.3, fill=WHITE, line=BORDER, radius=True)
    rect(s, x=7.55, y=1.85, w=5.0, h=0.55, fill=INK, line=None)
    text(s, "DEMAND GUARANTEE", x=7.8, y=1.98, w=4.4, h=0.3, size=11, bold=True, color=WHITE)
    rows = [
        ("Guarantee No.", "BG-2026-00417"),
        ("Amount", "USD 500,000.00"),
        ("Currency", "USD"),
        ("Issue Date", "2026-03-12"),
        ("Expiry Date", "2027-03-12"),
        ("Governing Rules", "URDG 758"),
    ]
    for index, (label, value) in enumerate(rows):
        y = 2.62 + index * 0.5
        text(s, label, x=7.85, y=y, w=1.9, h=0.3, size=11, color=MUTED)
        text(s, value, x=9.6, y=y, w=2.7, h=0.3, size=11, bold=True)
        line(s, x=7.85, y=y + 0.36, w=4.4, color=BORDER, height=0.008)
    text(
        s,
        "同一份文本 → 审计投影；格式变化不改变结论",
        x=7.85,
        y=5.7,
        w=4.5,
        h=0.3,
        size=10,
        color=RED,
        bold=True,
    )
    footer(s, 6)
    notes(
        s,
        "先让客户觉得“这是我的编辑器”：导入 DOCX/PDF、保留结构、表格、查找替换。"
        "但强调审计读的是纯文本投影，所以格式不会让审计变得不确定。",
    )


def slide_extraction(prs: Presentation) -> None:
    s = slide(prs)
    header(
        s,
        "EXTRACT",
        "确定性提取：值从当前文本来，不从 fixture 来",
        "profile 只描述“在哪里找”，不重复定义字段，也不接受正则/脚本。",
    )
    bullets(
        s,
        [
            ("配置驱动", "labels / aliases、value_kind、same_block / next_block、max_chars"),
            ("受控类型", "amount / date / currency / integer / text / clause_text"),
            ("出处", "file / page / bbox / span / form_label"),
            ("冲突降级", "同值去重；不同值 → unconfirmed + trail，不静默选一个"),
            ("可重放", "同一文本 + 同一 profile → 同一结果；model_calls = 0"),
        ],
        x=0.8,
        y=1.9,
        w=6.4,
        h=4.2,
        size=14,
    )
    rect(s, x=7.55, y=1.85, w=5.0, h=4.5, fill=INK, line=None, radius=True)
    code = [
        "{",
        '  "profile_id": "guarantee-default",',
        '  "version": "1.0.0",',
        '  "published": true,',
        '  "fields": {',
        '    "guarantee_amount": {',
        '      "labels": ["保函金额", "AMOUNT"],',
        '      "value_kind": "amount",',
        '      "search": "same_block"',
        "    },",
        '    "expiry_date": {',
        '      "labels": ["到期日", "EXPIRY DATE"],',
        '      "value_kind": "date",',
        '      "search": "same_or_next_block"',
        "    }",
        "  }",
        "}",
    ]
    for index, value in enumerate(code):
        text(
            s,
            value,
            x=7.85,
            y=2.05 + index * 0.205,
            w=4.5,
            h=0.2,
            size=9,
            color=WHITE,
            font=MONO,
        )
    footer(s, 7)
    notes(
        s,
        "这是和普通抽取最不一样的地方：profile 只决定“值在哪里”，字段类型仍由 fields.yaml 决定。"
        "没有正则、没有脚本；未知 key 或未知 value_kind 直接加载失败。真实文本 model_calls=0。",
    )
def slide_audit(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "AUDIT", "规范审计：可解释，而不是一个绿色勾", "规则、模板、公司包、审计基准日全部版本化；报告能说清“检查了什么、没检查什么”。")
    metric(s, x=0.7, y=1.85, w=3.7, big="56", label="默认计划单元", note="银行基线 + 公司规则")
    metric(s, x=4.6, y=1.85, w=3.7, big="63", label="模板匹配时", note="+ 3 字段 + 2 条款 + 1 声明")
    metric(s, x=8.5, y=1.85, w=4.1, big="11", label="已发布规则", note="每条含 pass / finding / needs_input 向量")
    bullets(
        s,
        [
            ("三套来源", "fields.yaml：字段定义；template：客户期望；rule bundle：银行/公司策略"),
            ("as_of", "固定审计基准日；Issue Date 不得早于 today，引擎不读系统时钟"),
            ("冲突可见", "公司包与客户模板 gate 冲突 → unable_to_assess，绝不 allowed"),
            ("报告可重放", "schema / bundle / template / engine 版本全部记录"),
            ("闸门保守", "不确定 → blocked / indeterminate；审计本身不批准任何操作"),
        ],
        x=0.85,
        y=3.55,
        w=11.5,
        h=2.9,
        size=14,
    )
    footer(s, 8)
    notes(
        s,
        "数字要讲清楚：56 是默认计划，63 是模板对手方匹配时的计划（样例对手方是 Beta，填 Adidas 模板会显示未解析/57）。"
        "重点讲 as_of、冲突可见、版本可重放，以及 gate 默认保守。UI 样例的 Issue Date 在过去，会触发 CO-ISSUE-NOT-PAST，"
        "这是公司规则在起作用；想演示 clean 用 ?as_of=2026-03-12 或 audit_demo.py。",
    )


def slide_finding(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "FINDINGS", "一条 finding 怎么读", "标题、字段、阻塞动作、规则、证据分层；客户一眼知道“改哪里”。")
    rect(s, x=0.8, y=1.9, w=7.3, h=3.75, fill=WHITE, line=BORDER, radius=True)
    rect(s, x=0.8, y=1.9, w=0.06, h=3.75, fill=RED, line=None)
    badge(s, "CRITICAL", x=1.1, y=2.12, w=1.15)
    text(s, "B-001", x=6.9, y=2.14, w=0.9, h=0.25, size=10, color=MUTED, align=PP_ALIGN.RIGHT)
    text(s, "Required field is missing", x=1.1, y=2.55, w=6.5, h=0.45, size=19, bold=True)
    rows = [
        ("Field", "保函编号  guarantee_number"),
        ("Blocks", "Start approval · Formal export · Handoff"),
        ("Check", "SCHEMA:guarantee_number:required · deterministic"),
        ("Evidence", "—（缺失字段没有原文，明确说明）"),
    ]
    for index, (label, value) in enumerate(rows):
        y = 3.2 + index * 0.52
        text(s, label, x=1.1, y=y, w=1.1, h=0.3, size=10, bold=True, color=RED)
        text(s, value, x=2.25, y=y, w=5.6, h=0.3, size=11, color=INK)
        line(s, x=1.1, y=y + 0.38, w=6.6, color=BORDER, height=0.008)
    bullets(
        s,
        [
            ("不显示 schema 哈希", "审查人不需要 commit 风格的版本号"),
            ("gate 用词可读", "Blocks / Needs human review / Advisory"),
            ("按紧急度排序", "hard_block → human_review → advisory，再按 severity"),
            ("每条都有下一步", "改哪里、为什么、阻塞什么"),
        ],
        x=8.55,
        y=1.95,
        w=4.1,
        h=3.6,
        size=12,
    )
    footer(s, 9)
    notes(
        s,
        "这是上次 UI 优化的重点：finding 不再把所有机器字段挤在一行。客户先看到“缺什么”，"
        "再看字段、阻塞动作、规则和证据。缺字段没有 evidence 时明确写出来，不编造。",
    )
def slide_knowledge(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "KNOWLEDGE", "知识问答：解释 + 引用 + 弃答", "不是“问什么答什么”，而是“有证据才回答，没证据明确说不够”。")
    rect(s, x=0.8, y=1.9, w=5.4, h=4.0, fill=WHITE, line=BORDER, radius=True)
    text(s, "可以这样问", x=1.05, y=2.1, w=4.8, h=0.3, size=13, bold=True, color=RED)
    questions = [
        "What documents are required for the application?",
        "URDG 758 是否适用于德国？",
        "How do I enable dark mode in the toolbar?",
        "帮我改写这段条款",
    ]
    for index, question in enumerate(questions):
        y = 2.55 + index * 0.72
        rect(s, x=1.05, y=y, w=4.85, h=0.55, fill=MIST, line=None, radius=True)
        text(s, question, x=1.2, y=y + 0.12, w=4.55, h=0.3, size=10, color=INK)
    rect(s, x=6.5, y=1.9, w=6.1, h=4.0, fill=WHITE, line=BORDER, radius=True)
    badge(s, "ANSWERED", x=6.75, y=2.1, w=1.1, color=GREEN)
    badge(s, "STRONG SUPPORT", x=8.0, y=2.1, w=1.7, color=GREEN)
    text(
        s,
        "提交版本后编辑锁会释放；审批期间文档只读。",
        x=6.75,
        y=2.55,
        w=5.5,
        h=0.7,
        size=15,
        bold=True,
    )
    line(s, x=6.75, y=3.4, w=5.5, color=BORDER)
    text(s, "引用 1 · 产品手册 · 提交与审批", x=6.75, y=3.55, w=5.5, h=0.3, size=10, color=RED, bold=True)
    text(s, "引用 2 · 文件导入 · 支持的文件类型", x=6.75, y=3.9, w=5.5, h=0.3, size=10, color=RED, bold=True)
    text(
        s,
        "边界：引用只返回本次获准的摘录与定位；不会返回整份来源。",
        x=6.75,
        y=4.45,
        w=5.4,
        h=0.5,
        size=10,
        color=MUTED,
    )
    text(
        s,
        "insufficient_evidence ≠ 文档合规；needs_handoff ≠ 助手已执行。",
        x=6.75,
        y=5.1,
        w=5.5,
        h=0.5,
        size=11,
        bold=True,
        color=RED_DARK,
    )
    footer(s, 10)
    notes(
        s,
        "知识问答的差异不是“回答更长”，而是每条 claim 有引用、support level 和 limitations。"
        "现场问一个产品问题、一个澄清问题、一个无证据问题、一个转交请求，四个状态都能看到。",
    )


def slide_legal(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "LEGAL", "Legal advice（L1）：法规建议 + 确定性规则", "先把“能引用、能失败、能重放”做对，再扩完整 DSL 与异步持久化。")
    card(
        s,
        x=0.8,
        y=1.9,
        w=3.8,
        h=1.8,
        head="Amount missing",
        body="Findings / Critical / Blocks: Start approval",
        tag="FINDING",
        tag_color=RED,
    )
    card(
        s,
        x=4.75,
        y=1.9,
        w=3.8,
        h=1.8,
        head="Amount confirmed",
        body="No findings / Pass",
        tag="PASS",
        tag_color=GREEN,
    )
    card(
        s,
        x=8.7,
        y=1.9,
        w=3.9,
        h=1.8,
        head="Amount unconfirmed",
        body="Unable to assess / 需要人工确认",
        tag="NO GUESS",
        tag_color=AMBER,
    )
    rect(s, x=0.8, y=4.0, w=11.8, h=2.0, fill=WHITE, line=BORDER, radius=True)
    text(s, "Statute advice", x=1.05, y=4.2, w=3.5, h=0.35, size=14, bold=True, color=RED)
    bullets(
        s,
        [
            ("引用可追溯", "条文号 / 法域 / 生效日 / 摘录 / chunk id"),
            ("answer_status 闸门", "answered / partial 才产出 finding；unavailable 不展示无关 references"),
            ("失败可区分", "timeout / corpus_updating / unsupported / statute_unavailable"),
        ],
        x=1.05,
        y=4.62,
        w=11.2,
        h=1.2,
        size=12,
    )
    footer(s, 11)
    notes(
        s,
        "Legal 今天只做 L1：一条合成规则 + 法规问答映射。重点演示三种事实态，以及离题问题不硬凑引用。"
        "明确说这不是完整法律意见，正式审查仍需人。",
    )
def slide_automation(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "AUTOMATION", "Automation：把“重复动作”变成工作台", "模板、变量、下游映射三块；当前 fixture/local，先把交互跑通。")
    card(
        s,
        x=0.8,
        y=1.9,
        w=3.8,
        h=2.5,
        head="Template",
        body="捕获当前文档为快照；预览来源/revision/字符数/变量；Apply 回编辑器；同 id 可升版本。",
        tag="LOCAL",
        tag_color=AMBER,
    )
    card(
        s,
        x=4.75,
        y=1.9,
        w=3.8,
        h=2.5,
        head="Variables & Fill",
        body="选中正文 → 标记变量 → 所有 occurrence 的 before/after 预览 → 一次性替换。",
        tag="LOCAL",
        tag_color=AMBER,
    )
    card(
        s,
        x=8.7,
        y=1.9,
        w=3.9,
        h=2.5,
        head="Downstream Mapping",
        body="OpenAPI 3.x JSON 在浏览器解析；变量映射到 request schema；下载 JSON；mock send 不触网。",
        tag="MOCK SEND",
        tag_color=AMBER,
    )
    rect(s, x=0.8, y=4.7, w=11.8, h=1.55, fill=WHITE, line=BORDER, radius=True)
    rect(s, x=0.8, y=4.7, w=0.05, h=1.55, fill=AMBER, line=None)
    text(
        s,
        "边界要主动说：模板/下游系统当前存浏览器 localStorage；真实 HTTP 发送、回执、幂等、服务端持久化尚未实现。",
        x=1.15,
        y=4.95,
        w=11.1,
        h=0.6,
        size=14,
        bold=True,
    )
    text(
        s,
        "下一步：服务端模板 + OpenAPI 系统注册表 + PG run 队列 + 真实发送/审计。",
        x=1.15,
        y=5.6,
        w=11.1,
        h=0.4,
        size=12,
        color=MUTED,
    )
    footer(s, 12)
    notes(
        s,
        "Automation 现在更像“前端工作台”，不是完整交付链路。现场演示模板、变量、映射和 JSON 下载即可，"
        "但一定要说明 mock send/本地存储的边界，避免客户以为已经能真实发下游。",
    )


def slide_collaboration(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "WORKFLOW", "人机协作：编辑 → 提交 → 两级审批", "系统不替人批准；它保证版本、锁、留痕和只读。")
    steps = [
        ("Draft", "编辑 + 自动保存\n编辑锁 / 冲突恢复"),
        ("Submitted", "冻结不可变版本\n释放锁，进入只读"),
        ("First approval", "Bank Operations\napprove / return / reject"),
        ("Second approval", "Compliance\napprove / return / reject"),
        ("Approved", "只读版本\n可导出 / 交付"),
    ]
    x0, y0, step_w = 0.8, 2.0, 2.25
    line(s, x=x0 + 0.2, y=y0 + 0.32, w=11.5, color=BORDER, height=0.02)
    for index, (head, body) in enumerate(steps):
        x = x0 + index * (step_w + 0.18)
        circle = s.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x), Inches(y0 + 0.16), Inches(0.34), Inches(0.34)
        )
        circle.fill.solid()
        circle.fill.fore_color.rgb = RED if index in (1, 2, 3) else INK
        circle.line.fill.background()
        text(
            s,
            str(index + 1),
            x=x,
            y=y0 + 0.22,
            w=0.34,
            h=0.18,
            size=9,
            bold=True,
            color=WHITE,
            align=PP_ALIGN.CENTER,
        )
        text(s, head, x=x, y=y0 + 0.7, w=step_w, h=0.3, size=13, bold=True)
        text(s, body, x=x, y=y0 + 1.05, w=step_w, h=0.8, size=10, color=MUTED)
    bullets(
        s,
        [
            ("职责分离", "提交人不能审批自己的请求；审批按组织/部门范围过滤"),
            ("可追溯", "每个阶段记录 actor、时间、意见、revision"),
            ("只读保护", "审批中/已批准不可编辑；退回后可修改再提交"),
            ("Activity", "登录、组织、文档、审批、助手 run、API Key 变更全部写服务端事件"),
            ("身份", "PG 模式真实账号；本地 fake 仅用于演示"),
        ],
        x=0.9,
        y=4.3,
        w=11.4,
        h=2.3,
        size=13,
    )
    footer(s, 13)
    notes(
        s,
        "审批是产品可信度的关键：系统不替人决定，但保证不可变版本、职责分离和留痕。"
        "如果现场有 PG，演示一次提交→Bank Ops→Compliance；没有就讲清楚本地模式边界。",
    )
def slide_architecture(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "ARCHITECTURE", "技术架构：确定性内核 + 可选 AI", "AI 是增强层，不是审计结论的来源。")
    boxes = [
        (0.8, 1.9, 3.1, 1.1, "React + TypeScript", "三栏工作台 / TipTap / Vitest", MIST),
        (4.25, 1.9, 3.0, 1.1, "FastAPI", "runs / documents / assistant / legal / approvals", MIST),
        (7.6, 1.9, 2.7, 1.1, "确定性内核", "parse → extract → normalize → audit", WHITE),
        (10.65, 1.9, 1.9, 1.1, "SQLite / PG", "host.db + 可选身份 PG", MIST),
    ]
    for x, y, w, h, head, body, fill in boxes:
        rect(s, x=x, y=y, w=w, h=h, fill=fill, line=BORDER, radius=True)
        text(s, head, x=x + 0.16, y=y + 0.16, w=w - 0.3, h=0.3, size=12, bold=True)
        text(s, body, x=x + 0.16, y=y + 0.52, w=w - 0.3, h=0.5, size=9, color=MUTED)
    for x in (3.95, 7.3, 10.45):
        text(s, "→", x=x, y=2.25, w=0.3, h=0.3, size=18, bold=True, color=RED)
    rect(s, x=0.8, y=3.45, w=11.8, h=2.4, fill=WHITE, line=BORDER, radius=True)
    text(
        s,
        "可选 AI / 外部证据（默认关闭，显式配置）",
        x=1.05,
        y=3.65,
        w=7,
        h=0.3,
        size=12,
        bold=True,
        color=RED,
    )
    bullets(
        s,
        [
            ("Doubao Gateway", "知识问答结构化；JSON 校验 + 纠正重试 + 超时"),
            ("Mercatoria /v1/chat", "法规语料检索 + 服务端草稿；Legal 与 Knowledge 共用"),
            ("Egress 闸门", "默认拒绝、脱敏、审计 query digest；不把全文/密钥写日志"),
        ],
        x=1.05,
        y=4.05,
        w=11.2,
        h=1.5,
        size=11,
    )
    text(
        s,
        "回归：830 后端 · 540 前端 · typecheck/build · OpenSpec strict",
        x=0.9,
        y=6.15,
        w=11.5,
        h=0.35,
        size=11,
        bold=True,
    )
    footer(s, 14)
    notes(
        s,
        "架构一句话：确定性内核负责审计，AI 只是增强层。豆包/法规都是可选、显式配置、经过 egress 闸门。"
        "当前 SQLite 单进程，PG 只用于身份；这是 demo 的边界，也是下一步要补的。",
    )


def slide_principles(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "PRINCIPLES", "八条硬约束：为什么客户敢用", "这些不是文案，是代码里的测试和不变量。")
    items = [
        ("只改形式，不改事实", "字段必须能回原文"),
        ("没检查 ≠ 没问题", "状态在数据结构上分开"),
        ("引用可追溯", "chunk / 条号 / 法域 / 摘录"),
        ("配置驱动", "fields + profile + template + bundle"),
        ("AI 只做建议", "不能写 pass / 不能自动 apply"),
        ("闸门默认保守", "不确定 → blocked"),
        ("每次操作留痕", "trail 记录 read/transform/llm"),
        ("失败可区分", "timeout / no-hit / unsupported"),
    ]
    for index, (head, body) in enumerate(items):
        col = index % 2
        row = index // 2
        x = 0.8 + col * 6.0
        y = 1.85 + row * 1.15
        rect(s, x=x, y=y, w=5.7, h=0.95, fill=WHITE, line=BORDER, radius=True)
        rect(s, x=x, y=y, w=0.04, h=0.95, fill=RED, line=None)
        text(s, head, x=x + 0.22, y=y + 0.14, w=5.2, h=0.3, size=13, bold=True)
        text(s, body, x=x + 0.22, y=y + 0.5, w=5.2, h=0.3, size=10, color=MUTED)
    footer(s, 15)
    notes(
        s,
        "如果客户只记一页，就记这八条。它们解释了为什么我们的 AI 不会乱改、为什么 missing 不等于 pass、"
        "为什么报告可以重放。每条都能在代码/测试里找到对应。",
    )
def slide_demo(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "DEMO", "现场怎么跑：15 分钟脚本", "三条主线：当前文本 → 可解释审计；有证据才回答；不确定不假装通过。")
    steps = [
        ("01  导入 / 编辑  2 min", "Import file → guarantee.docx；展示富文本、表格、自动保存"),
        ("02  规范审计  4 min", "sample_document → Run；56/37/0.661；模板未匹配 57 / 匹配 63；Issue Date 触发 finding"),
        ("03  确定性证明  1 min", "终端：?profile=guarantee-default → source=deterministic, calls=0"),
        ("04  知识问答  2 min", "产品 FAQ / 澄清 / 无证据 / 转交，四种 outcome"),
        ("05  Legal  2 min", "Rule check 三态；Statute advice 引用；离题不硬凑"),
        ("06  Automation  2 min", "Template → Variables → OpenAPI mapping → Download JSON"),
        ("07  审批（可选） 1 min", "PG：提交 → Bank Ops → Compliance；否则讲边界"),
        ("08  收尾  1 min", "Now / Next / Later；Q&A"),
    ]
    for index, (head, body) in enumerate(steps):
        col = index % 2
        row = index // 2
        x = 0.8 + col * 6.0
        y = 1.8 + row * 1.2
        rect(s, x=x, y=y, w=5.7, h=1.0, fill=WHITE, line=BORDER, radius=True)
        text(s, head, x=x + 0.2, y=y + 0.14, w=5.3, h=0.3, size=12, bold=True, color=RED)
        text(s, body, x=x + 0.2, y=y + 0.5, w=5.3, h=0.4, size=9, color=MUTED)
    text(
        s,
        "准备：./scripts/dev.sh   ·   样例：fixtures/llm/sample_document.txt   ·   备用：--honest / 录屏 60s",
        x=0.85,
        y=6.7,
        w=11.5,
        h=0.3,
        size=10,
        color=MUTED,
    )
    footer(s, 16)
    notes(
        s,
        "按这个节奏走，不要在每个 tab 里停留太久。审计是主菜，知识/ Legal / Automation 是能力证明。"
        "如果现场网络或法规服务不稳，立刻切到 Rule check 和 --honest，讲“失败也诚实”。",
    )


def slide_roadmap(prs: Presentation) -> None:
    s = slide(prs)
    header(s, "ROADMAP", "现在、下一步、再下一步", "Demo 讲能力，也要讲清楚生产化还差什么。")
    columns = [
        (
            "NOW · 本次 demo",
            GREEN,
            [
                "导入 / 富文本 / 自动保存 / 冲突恢复",
                "确定性审计 + 模板 + 公司包",
                "Knowledge Q&A + 引用",
                "Legal L1：法规 + 规则检查",
                "Automation 工作台（local/mock）",
                "PG 身份 + 两级审批",
            ],
        ),
        (
            "NEXT · 1–2 个月",
            AMBER,
            [
                "Automation 模板 / 系统服务端化",
                "PG run 队列 + Worker + 租约",
                "真实下游发送 / 回执 / 幂等",
                "AI advisory：改写 / 提取 / 映射建议",
                "评测集 + 成本 / 质量指标",
            ],
        ),
        (
            "LATER · 生产化",
            RED,
            [
                "向量检索 / 重排",
                "多租户 / 可观测性 / 备份",
                "法规语料扩展与治理",
                "审批 gate 接入 AI findings",
                "SLA / 审计 / 权限加固",
            ],
        ),
    ]
    for index, (head, color, items) in enumerate(columns):
        x = 0.8 + index * 4.05
        rect(s, x=x, y=1.8, w=3.8, h=4.6, fill=WHITE, line=BORDER, radius=True)
        rect(s, x=x, y=1.8, w=3.8, h=0.08, fill=color, line=None)
        text(s, head, x=x + 0.22, y=2.05, w=3.4, h=0.35, size=13, bold=True, color=color)
        for item_index, item in enumerate(items):
            text(
                s,
                f"•  {item}",
                x=x + 0.22,
                y=2.55 + item_index * 0.55,
                w=3.35,
                h=0.45,
                size=10,
                color=INK,
            )
    text(
        s,
        "一句话：先把“可解释 + 可演示”做扎实，再把“服务端 + 真实发送 + 评测”补齐。",
        x=0.9,
        y=6.55,
        w=11.5,
        h=0.3,
        size=11,
        color=MUTED,
    )
    footer(s, 17)
    notes(
        s,
        "路线图不要报喜不报忧。Now 是今天能演示的，Next 是产品化必须补的，Later 是规模化。"
        "客户最关心 Next：服务端持久化、真实发送、AI advisory 的评测闭环。",
    )


def slide_closing(prs: Presentation) -> None:
    s = slide(prs, dark=True)
    rect(s, x=0, y=0, w=0.18, h=7.5, fill=RED, line=None)
    text(s, "THANK YOU", x=0.9, y=0.95, w=4, h=0.35, size=12, bold=True, color=RED)
    text(
        s,
        "让 AI 做建议，\n让人做决定。",
        x=0.9,
        y=1.75,
        w=7.5,
        h=1.7,
        size=40,
        bold=True,
        color=WHITE,
        spacing=1.15,
    )
    line(s, x=0.9, y=3.9, w=5.0, color=RGBColor(0x4A, 0x4A, 0x4A))
    text(
        s,
        "每一句话都有出处 · 每一次不确定都明确说出来 · 每一次操作都可追溯",
        x=0.9,
        y=4.2,
        w=10.5,
        h=0.5,
        size=14,
        color=RGBColor(0xC9, 0xC9, 0xC9),
    )
    text(s, "Q&A", x=0.9, y=5.3, w=3, h=0.5, size=22, bold=True, color=WHITE)
    text(
        s,
        "demo 材料：docs/demo/smart-edit-product-intro.md · docs/demo/smart-edit-demo.pptx",
        x=0.9,
        y=6.35,
        w=11.5,
        h=0.3,
        size=10,
        color=RGBColor(0xB9, 0xB9, 0xB9),
    )
    notes(
        s,
        "收尾回到一句话：AI 做建议，人做决定。感谢时间，进入 Q&A。"
        "如果客户问生产化，直接翻到 roadmap 页，不要临场承诺。",
    )


def build() -> Path:
    prs = new_deck()
    slide_cover(prs)
    slide_problem(prs)
    slide_value(prs)
    slide_panorama(prs)
    slide_flow(prs)
    slide_editor(prs)
    slide_extraction(prs)
    slide_audit(prs)
    slide_finding(prs)
    slide_knowledge(prs)
    slide_legal(prs)
    slide_automation(prs)
    slide_collaboration(prs)
    slide_architecture(prs)
    slide_principles(prs)
    slide_demo(prs)
    slide_roadmap(prs)
    slide_closing(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")