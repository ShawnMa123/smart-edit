# Design

## Context

Current state lives in `web/src/App.tsx`, `web/src/styles.css` (506 lines, one stylesheet) and `web/src/components/`. Observed:

- `.app` contains only `document-head`, `ImportReport`, the narrow `pane-tabs` and `.work-grid`; there is no top bar and no global status strip.
- The document header is a title plus `DocumentActions` (`Import file` primary + three `· not implemented` buttons); its meta line reads `0 captured versions · 293 characters · server draft rev 112 · history stored in this browser`.
- The middle pane is a `.pane` card: `toolbar` + editor + `editor-footer` (character count + `data-testid="save-state"`).
- `VersionPanel` renders a `.versions` list plus three explanatory paragraphs; no timeline and no document-info block.
- `AssistantPanel` puts implementation status inside tab names (`Automation · fixture only`, `Legal advice · not implemented`), which wraps onto three rows at 352px; the panel's first screen is dominated by prose.
- Interface language is almost English but not consistently: `web/index.html` declares `lang="zh-CN"`, `App.tsx` renders `<h1>Demand Guarantee · 见索即付保函</h1>` and a breadcrumb containing `DG-2026-00417`, and `web/src/components/knowledgeSuggestions.ts` keeps Chinese strings for the `zh-CN` branch (unused by default).

Existing test contracts that must keep holding:

| Contract | Source |
|---|---|
| `.work-grid > *` is exactly `Version history` / `Document editor` / `AI assistant`, one pane when narrow | `App.test.tsx` |
| `section[aria-label="Document editor"]`, `aside[aria-label="AI assistant"]`, `tablist[aria-label="Workspace panes"]` | `e2e/layout.spec.ts`, `e2e/narrow.spec.ts` |
| `data-testid="save-state"` copy (`Saving…`, `Saved to server`, `Save conflict — local content is not saved to the server`) | `e2e/draft.spec.ts`, `App.test.tsx` |
| `getByText(/server draft rev/)` visible on first load | `e2e/draft.spec.ts`, `e2e/automation-workbench.spec.ts` |
| Exact `11 characters in the audit text` | `RichEditor.test.tsx` |
| Tab accessible names containing `Automation · fixture only` / `Legal advice · not implemented` | `AssistantPanel.test.tsx`, `e2e/draft.spec.ts`, `e2e/automation-workbench.spec.ts` |
| Unavailable action names containing `Export · not implemented` / `Start approval · not implemented` | `DocumentActions.test.tsx` |
| `toolbar[aria-label="Formatting"]` | `RichEditor.test.tsx` |
| Audit result copy (`Fixture-backed run`, `33 of 51 planned checks assessed`, `ratio 0.647`) | `e2e/audit.spec.ts` |

Reference prototype: `tradeAI_requirementDesign_v2/HSBC_Nexus_Document_Editor_Mock_Demo.html` (`topbar` 60px, `prototype-strip` 26px, `rail` 58px, `work-grid` 208/1fr/352, `paper` 790px with 43·47 padding and serif 14/1.95 body, `metrics`, `finding`, `empty`).

These four artifacts are written in English at the requester's explicit direction, overriding the project default of Chinese artifacts.

## Goals / Non-Goals

**Goals:**

- Align shell hierarchy, page presentation, status visibility and assistant information density with the reference prototype without changing behaviour, contracts or test semantics.
- Replace per-panel disclaimers with one standing environment band while keeping each panel's specific, testable promises.
- Make the interface consistently English: declared language, chrome copy, assistant locale and document identity all agree.
- Ensure every new presentation is guarded by an existing Vitest/Playwright assertion or a new one.

**Non-Goals:**

- Chinese localisation or any translation layer.
- New approval/comments/export/identity/version-compare capability, or entries that imply one.
- Copying prototype demo data (counterparties, template number, organisations, fixed findings, fixed hashes).
- Changing `rich/` projection, `api/` clients, `automation/` logic or any backend contract.
## Decisions

### D1 Shell components stay outside `.work-grid`

New `web/src/components/AppShell.tsx` exports `TopBar`, `EnvironmentStrip` and `DocumentHead`, rendered by `App.tsx` inside `.app` and before `.work-grid`. The direct children of `.work-grid` MUST remain the three panes, because `App.test.tsx` reads pane `aria-label`s from `.work-grid > *`; any wrapper breaks that contract.

Alternative: fold the top bar into the existing `document-head`. It would merge the product layer with the document layer and squeeze the 352px assistant column. Rejected.

### D2 The top bar shows only what the system knows

The product mark uses a configurable constant (default `Trade workspace`, no bank logo or name). The right side holds the session label (`Local demo session`) and document-level entries only. With no authentication the shell renders **no person name, avatar, organisation or member-management entry**; the prototype's identity card is deliberately skipped.

Alternative: copy the identity card but label it `Demo user`. It still reads as a signed-in session. Rejected.

### D3 The environment band is the single summary; panels keep their specific claims

The band (directly under the top bar, 24–28px, wrapping to two lines when narrow) carries three statements: synthetic/demo data, fixed snapshot with the assistant not approving, and history/templates stored in this browser. Panels **keep** their own precise assertions (`History is stored in **this browser only**` in the sidebar, `does not approve or submit` in the assistant footnote) because existing specs and tests assert them; the band supplements rather than replaces them. What is removed is duplicated long-form explanation (the audit coverage list, the knowledge onboarding paragraphs), whose content moves into empty-state hints or a details control.

### D4 The page is a container; the projection stays the only truth

`RichEditor` output becomes:

```
section.pane[aria-label="Document editor"]
  row (title + note)
  div.editor-status  (band: snapshot/version · lock · save-state)
  div.toolbar[aria-label="Formatting"]
  div.paper-wrap     (grey canvas)
    article.paper
      header.paper-head   (document id · WORKING COPY)
      EditorContent > .editor-rich[data-testid="editor-rich"]
      footer.paper-foot   (version count · short digest)
  div.editor-footer   (character count + page hint)
```

- `EditorContent` remains the only editing node and keeps `data-testid="editor-rich"` in place; the page adds CSS plus two static header/footer nodes.
- Page width `790px`, `margin: 0 auto`, `padding: 43px 47px`; at `max-width: 1365px` it becomes `width: 100%` with `padding: 20px`; the canvas uses `--canvas`.
- The page header shows the real `documentId` (currently `demo-document`) and `WORKING COPY`; **no `DG-2026-00417`**. The footer shows the version count and the short digest when available.
- Projection, character count and snapshot digest do not participate in this change (`richToPlainText` input unchanged); the `rich-text-editing` golden tests act as the regression guard.

Alternative: fake the page with a CSS background image. It cannot carry real header/footer text and hurts accessibility. Rejected.

### D5 One source of truth for the status band

New `.editor-status` moves the `data-testid="save-state"` rendering **verbatim** (all message branches) and adds `snapshot v{n}` (`versions.length`, or `no captured version`), `draft rev {n}` (or `no server draft`) and `lock: this session` / `lock: unknown` from the `LockView` the app already acquires. Conflict wording reuses the same `saveState` branch the conflict panel reads, so the band can never say "saved to server" while the panel reports a conflict.

`editor-footer` keeps the exact `{n} characters in the audit text` copy (`RichEditor.test.tsx` asserts it) and the character count must not move into the band.

### D6 Version sidebar: timeline plus a real-metadata block

`VersionPanel` keeps `.versions` / `.version` class names, `data-current`, `Restore into editor`, `Capture version`, `Clear version history` and the "stored in ... this browser only" copy (`VersionPanel.test.tsx`). Additions:

- Timeline styling (left rule plus dots) and a `<span class="tag">current</span>` word marker that does not rely on background colour.
- A "Document info" block fed by a new optional prop `facts?: { documentId?: string; draftRevision?: number | null }`; without it the block shows only the version count and browser storage locality and **renders no organisation or workspace rows**.
- An `EmptyState` (icon + title + hint + `Capture version`) whose copy still contains `No versions yet` for the existing assertion.
### D7 Assistant pane: short labels plus a separate status tag, accessible names unchanged

`TABS` gains `shortLabel` and `statusLabel`:

| id | visible label | status tag | accessible name (`aria-label`, unchanged) |
|---|---|---|---|
| audit | Audit | Full | `Rule audit` |
| knowledge | Knowledge | Full | `Knowledge Q&A` |
| automation | Automation | Fixture only | `Automation · fixture only` |
| legal | Legal | Not implemented | `Legal advice · not implemented` |

- Each tab renders `<span class="tab-label">Automation</span><span class="tab-status tag">Fixture only</span>` with `white-space: nowrap` and `flex: 1`, so four tabs fit one row at 352px.
- The status tag is `aria-hidden="true"` and the tab keeps its current `aria-label`, so existing assertions and screen-reader information both survive.
- The unimplemented tab still renders `Legal advice is not implemented in this build` and no sample output.
- The footnote collapses to one line and still contains `does not approve or submit`.

### D8 Document header: business first, technical details collapsed, identity from metadata

The meta line keeps `{n} captured versions · {chars} characters · server draft rev {n}` (the `/server draft rev/` assertion depends on it being visible) and gains a business-first line: breadcrumb `Trade documents / Guarantees / {documentId}`, the stored `draft.title` (fallback `Untitled document`) and a `Draft` status tag. The digest, lock lease and storage key move into `<details><summary>Technical details</summary>`. The `/server draft rev/` text MUST stay visible, never inside the details.

The breadcrumb and title MUST come from stored data: today that means `draft?.document_id` and `draft?.title`. The hardcoded `DG-2026-00417` is removed because it is an example reference, not this document's identifier.

### D9 Unavailable actions stay present but quiet

`DocumentActions` renders `Export` / `Formatting` / `Start approval` as quiet buttons with a `Not available` square tag while keeping `aria-label="… · not implemented"`, `data-unavailable="true"` and the existing click-through status message. That satisfies `DocumentActions.test.tsx` and the existing `document-editor` requirement (present and marked) without giving them primary weight. `Import file` stays the primary action.

### D10 Token mapping

| Purpose | Reference prototype | This change |
|---|---|---|
| Primary action | `#db0011` | keep `--accent: #1f4e79` (lower brand risk); primary buttons use it |
| Canvas | `#e9edee` / `#f3f5f5` | new `--canvas: #eceff0` (outside the page), `--bg: #f4f6f6` (app) |
| Rules | `#dce1e3` | `--border: #d9dee0` |
| Radius | 3–4px | `--radius: 4px`, `--radius-tag: 3px`, replacing 6/8px |
| Status | square `.tag.good/.warn/.bad` | `.status--*` becomes square + light fill + word; new generic `.tag` |
| Type | Aptos/Segoe shell + Georgia/Noto Serif SC page | shell keeps the system stack; page body `Georgia, "Noto Serif SC", serif` at 14px/1.95 |
| Sidebar surface | `#fbfcfc` | `.pane--versions { background: #fbfcfc }` |

Status still has to pair colour with a word (`document-editor` requirement); this change alters shape and fill only.

### D11 Empty-state component

New `components/EmptyState.tsx` (`icon`, `title`, `hint`, `action`) reused by `VersionPanel` (no versions), `AuditPanel` (not run) and `KnowledgePanel` (not asked). The audit empty state must keep `Run spec audit` as its primary action (`App.test.tsx`), and explanatory text must not become the main element.

### D12 English-only interface baseline

- `web/index.html`: `lang="zh-CN"` → `lang="en"`; `<title>` stays English (`smart-edit · document workspace`).
- `App.tsx`: the `<h1>` renders `draft?.title ?? 'Untitled document'` with no gloss; the breadcrumb renders `draft?.document_id ?? DOCUMENT_ID`.
- Assistant locale: `App.tsx` passes `locale="en"` into the knowledge binding (today the panel defaults to `en`; pinning it makes the choice explicit and testable) so the session is created with `locale: 'en'` and the English corpus (`fixtures/knowledge/*_en.json`) is the only source of citations.
- `knowledgeSuggestions.ts` keeps its `zh-CN` branch as dead-but-valid copy; it is not reachable while the locale is pinned. Its file comment that "questions stay in Chinese because the demo corpus is zh-CN" is corrected to describe the English default.
- Out of scope for this decision: Chinese *content* (document text, pasted text, OCR output), Chinese matching rules in `automation/mockWorkbench.ts` (`/guarantee|保函/i` — matching input, not copy), Chinese test fixtures, and repository documentation.

### D13 How "English-only chrome" is verified

A Playwright assertion collects `innerText` from chrome roots only — `header`, `.topbar`, `.environment-strip`, `.pane-tabs`, `.document-head`, `.assistant-tabs`, `.editor-status`, `.editor-footer` — and asserts no CJK code point appears. The editor body and citation excerpts are excluded on purpose, because user content and quoted source text may legitimately be Chinese. `html[lang]` and the `<title>` are asserted directly.
## Risks / Trade-offs

- **Text-selector regressions** → keep `data-testid`, `aria-label` and the exact copy listed in Context; every PR runs `npm --prefix web run verify` (typecheck + vitest + playwright). Tasks name the spec files that must stay green.
- **`.work-grid > *` contract broken by a wrapper** → shell renders outside the grid; `App.test.tsx` is the guard.
- **Page layout squeezes the editing column at 1366px** → page is `max-width: 790px` with `min-width: 0` and `paper-wrap` scrolls; the `useViewport` breakpoint stays 1365px and does not depend on page width.
- **A second account of the save state** → the band derives from `saveState` only and reuses the conflict branch; a unit test asserts conflict wording and panel wording cannot contradict.
- **Honesty vs. resemblance** → no sample counterparties, template numbers, organisations or findings; the prototype's `prototype-strip` becomes the environment band, and its `rail`/identity card are not built because no capability backs them.
- **English-only pinning narrows the demo** → the English corpus answers fewer questions than the Chinese one; the panel must state the limitation in English rather than surfacing Chinese text. The trade-off is accepted for a single-language demo.
- **CJK detection can be brittle** → the assertion scans named chrome roots, not `document.body`, and excludes the editor body and citation text so legitimate Chinese content does not fail the build.
- **Mixed-language drift over time** → `interface-language` makes "English chrome" a spec-level requirement, so a future Chinese-localisation change must modify that capability rather than add ad-hoc translations.

## Migration Plan

Frontend only, no data or API migration. The change can be reverted per commit; `localStorage` keys and existing drafts/templates are unaffected. Removing the Chinese gloss changes only rendered copy, not stored document content.

## Open Questions

- None. The product mark is deliberately configurable but disabled by default (D2); whether the interface later gains a Chinese locale is a separate change against `interface-language`, and does not affect this task breakdown.
- Localising repository documentation (`how_to_use.md`, `web/README.md`) beyond the sections this change touches.