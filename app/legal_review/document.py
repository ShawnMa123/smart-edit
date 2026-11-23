"""Clause planning for a document risk scan (`legal-document-risk-scan` D1).

The denominator of every coverage number is built here, before anything is evaluated: the draft is
projected to canonical text (`project_document`), split into clause-sized units that keep their
code-point offsets, and capped. A finding can therefore point at a real slice of the draft, and a
clause that was never planned can never appear as "checked, nothing found".

Splitting is deliberately conservative: it only starts a new clause on a heading-looking block, a
numbered item, or when the current clause would exceed the character cap. Guessing semantics from
text is the model's job, not the splitter's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.documents.projection import BlockSpan, Projection, plain_text_document, project_document

DEFAULT_MAX_CLAUSES = 12
DEFAULT_CLAUSE_CHARS = 1200
# How much of a clause is quoted in an anchor; still a substring of the draft text.
QUOTE_CHARS = 240

_TERMINAL = "。．.!?！？;；:："
# `第一条` / `1.` / `1.2.3)` / `(a)` / a short ALL-CAPS line are headings for our purposes.
_HEADING_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百千零〇\d]+[条款章节项部分]"
    r"|[0-9]+(?:\.[0-9]+)*[.、)]"
    r"|\([0-9a-zA-Z]{1,3}\)"
    r"|[A-Z][A-Z0-9 ,.&/'-]{2,60}"
    r")$"
)
# A numbered marker that starts a new clause even mid-paragraph.
_NUMBERED_START_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百千零〇\d]+[条款]"
    r"|[0-9]+(?:\.[0-9]+)*[.、)]"
    r"|\([a-zA-Z0-9]{1,3}\))"
)


@dataclass(frozen=True)
class Clause:
    clause_id: str
    index: int
    block_index: int
    start_cp: int
    end_cp: int
    text: str
    heading: str | None = None

    @property
    def preview(self) -> str:
        text = re.sub(r"\s+", " ", (self.heading or self.text)).strip()
        return text[:80]


@dataclass(frozen=True)
class ClausePlan:
    """The planned units plus everything the report needs to describe its own limits."""

    clauses: tuple[Clause, ...] = ()
    projection: Projection = field(default_factory=lambda: Projection("", ()))
    total_blocks: int = 0
    truncated: bool = False
    no_text: bool = False

    @property
    def text(self) -> str:
        return self.projection.text

    @property
    def blocks(self) -> tuple[BlockSpan, ...]:
        return self.projection.blocks

    def top_blocks(self) -> tuple[BlockSpan, ...]:
        return tuple(
            block for block in self.projection.blocks if re.fullmatch(r"b\d+", block.node_id)
        )

    def block_at(self, offset: int) -> BlockSpan | None:
        """The top-level block containing `offset` (used for marker anchors)."""
        for block in self.top_blocks():
            if block.start_cp <= offset < block.end_cp:
                return block
        return None


def _block_text(text: str, block: BlockSpan) -> str:
    return text[block.start_cp : block.end_cp]


def _looks_like_heading(value: str) -> bool:
    stripped = value.strip()
    if not stripped or len(stripped) > 90:
        return False
    if stripped[-1] in _TERMINAL:
        return False
    return bool(_HEADING_RE.match(stripped))


def _starts_numbered_item(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and len(stripped) <= 90 and bool(_NUMBERED_START_RE.match(stripped))


def split_clauses(
    content: dict | None,
    *,
    text: str | None = None,
    max_chars: int = DEFAULT_CLAUSE_CHARS,
    max_clauses: int = DEFAULT_MAX_CLAUSES,
) -> ClausePlan:
    """Project and split a rich document. `text` is a fallback for plain-text drafts."""
    document = content if content else (plain_text_document(text or "") if text else None)
    projection = project_document(document)
    blocks = tuple(block for block in projection.blocks if re.fullmatch(r"b\d+", block.node_id))
    if not projection.text.strip() or not blocks:
        return ClausePlan(projection=projection, total_blocks=len(blocks), no_text=True)

    groups: list[list[BlockSpan]] = []
    current: list[BlockSpan] = []
    current_chars = 0
    for block in blocks:
        block_text = _block_text(projection.text, block)
        starts_new = bool(current) and (
            _looks_like_heading(block_text)
            or _starts_numbered_item(block_text)
            or current_chars + len(block_text) + 2 > max_chars
        )
        if starts_new:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(block)
        current_chars += len(block_text) + 2
    if current:
        groups.append(current)

    truncated = len(groups) > max_clauses
    groups = groups[:max_clauses]

    clauses: list[Clause] = []
    for index, group in enumerate(groups, start=1):
        start = group[0].start_cp
        end = group[-1].end_cp
        raw = projection.text[start:end]
        first_line = raw.splitlines()[0].strip() if raw.strip() else None
        clauses.append(
            Clause(
                clause_id=f"clause-{index:02d}",
                index=index,
                block_index=int(group[0].node_id[1:]),
                start_cp=start,
                end_cp=end,
                text=raw,
                heading=first_line if first_line and _looks_like_heading(first_line) else None,
            )
        )
    return ClausePlan(
        clauses=tuple(clauses),
        projection=projection,
        total_blocks=len(blocks),
        truncated=truncated,
        no_text=False,
    )


def split_text(text: str, **kwargs) -> ClausePlan:
    return split_clauses(None, text=text, **kwargs)


def quote_for(plan: ClausePlan, start_cp: int, end_cp: int) -> str:
    """A short quote that is always a real substring of the drafted text."""
    text = plan.text
    start = max(0, min(len(text), start_cp))
    end = max(start, min(len(text), end_cp))
    return text[start:end][:QUOTE_CHARS]


__all__ = [
    "Clause",
    "ClausePlan",
    "DEFAULT_CLAUSE_CHARS",
    "DEFAULT_MAX_CLAUSES",
    "QUOTE_CHARS",
    "quote_for",
    "split_clauses",
    "split_text",
]