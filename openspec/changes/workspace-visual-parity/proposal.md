# Proposal

## Why

The three-pane workspace matches the reference prototype's grid (208 / 1fr / 352) but none of its hierarchy: there is no top bar or standing environment notice, the document header spends its most valuable space on three `· not implemented` buttons, the 208px sidebar carries an explanatory paragraph instead of a version timeline, the centre pane is a rounded card rather than a page, the assistant's four tabs wrap onto three lines at 352px, and the first screen explains the audit in prose instead of showing the metrics/finding/empty structures the prototype demonstrates. The build reads as an engineering console rather than a product.

The interface is also only *mostly* English: `web/index.html` declares `lang="zh-CN"`, the document title renders a Chinese gloss (`Demand Guarantee · 见索即付保函`), and the breadcrumb shows an invented document number (`DG-2026-00417`). Those leftovers contradict both an English-only demo and the project rule that the UI never presents data it does not hold.

This change aligns presentation and interface language only. It adds no capability, changes no backend contract, and leaves the audit/automation state machines untouched.

## What Changes

- **Design tokens**: radius drops from 6px to 4px (3px for tags); status moves from outlined pills to square light-filled tags; a grey-green canvas and a paper layer are introduced; shell typography stays sans-serif while page body text becomes serif.
- **New shell layers**: a 60px top bar (product mark, workspace label, environment entry, no fabricated identity), a 24–28px standing environment strip that replaces disclaimers scattered across panels, and a document header with breadcrumb / title / status tag / meta line.
- **Document header rewrite**: business facts first, and only facts the build actually holds (document id, character count, version count, draft revision, save state, content source). Parties, template numbers and organisations are omitted or shown as `not provided`; **no invented values**. Technical facts (sha256, lock lease, storage key) move into a collapsible detail.
- **Unavailable actions quieted**: `Export` / `Start approval` stay in the header and stay marked (the existing `document-editor` requirement), but become quiet buttons with a `Not available` tag instead of competing with the primary action.
- **Editor becomes a page**: grey canvas plus a centred 790px paper with a page header (document id / WORKING COPY), a page footer (version and snapshot markers) and serif body text. The paper is a container only: projected text, character count, digest and the audit request stay byte-identical.
- **Standing status band**: a strip above the toolbar shows snapshot/version, save state and edit-lock state (known vs unknown, worded separately), derived from the same `saveState` the conflict panel uses so the two can never disagree.
- **Version sidebar**: entries become a timeline; the current version carries a `current` word marker in addition to the highlight; a document-info block lists only real metadata (document id, storage locality, version count, character count, draft revision) and never demo organisations.
- **Assistant pane frame**: tabs use short labels (Audit / Knowledge / Automation / Legal) and fit on one row at 352px; implementation status moves to a separate tag (Full / Fixture only / Not implemented); unimplemented tabs still say so and still render no sample output; the footnote collapses to one line.
- **Empty states and result surfaces**: audit-not-run, knowledge-not-asked and empty version history use one "icon + title + primary action + hint" structure; the audit result reuses the existing `metrics` / `finding` card styles instead of a "what this audit will check" list.
- **Narrow viewport**: below 1365px the pane switcher stays, and the same top bar, environment strip, document header and status band remain visible or reachable.
- **English-only interface**: every piece of interface copy stays English, `web/index.html` declares `lang="en"`, the assistant session is pinned to the `en` locale, and no Chinese gloss, Chinese fixture text or invented document number reaches the rendered chrome. User-supplied document text may remain in any language — that is content, not interface.

## Capabilities

### New Capabilities

- `workspace-shell`: the hierarchy and presentation of the workspace shell — the standing environment notice, a document header limited to real metadata, the paper rendering of the editor that leaves audit input unchanged, the standing save/lock status band, the version timeline and its real-metadata info block, short assistant tabs with a separate capability tag, empty-state structure, and the same layers on a narrow viewport.
- `interface-language`: which language the interface speaks and how identity-bearing text is sourced — English-only chrome, a declared document language, an assistant locale pinned to English, and the rule that stored document metadata (not example strings) supplies the title and document identifier while user content may stay in any language.

### Modified Capabilities

<!-- None: document-editor, rich-text-editing and document-import requirements are unchanged. The unimplemented-action and colour-plus-word requirements continue to hold; only their presentation moves. -->

## Impact

- **Frontend**: `web/src/styles.css` (tokens, shell, paper, status band, timeline, empty states), `web/src/App.tsx` (shell composition, document header, title/breadcrumb from metadata), new `web/src/components/AppShell.tsx` (top bar + environment strip + document head), `web/src/components/RichEditor.tsx` (paper container, status band move), `web/src/components/VersionPanel.tsx` (timeline + info block), `web/src/components/AssistantPanel.tsx` (short tabs + capability tag + one-line footnote), `web/src/components/DocumentActions.tsx` (quiet style + `Not available` tag), empty-state shells in `AuditPanel.tsx` / `KnowledgePanel.tsx`; `web/index.html` (`lang`). No changes to `api/`, the `rich/` projection or `automation/` logic.
- **Tests**: `web/src/components/*.test.tsx` and `web/e2e/*.spec.ts` selectors that depend on visible copy or heading levels need to follow the structure (known hotspots: `layout.spec.ts`, `narrow.spec.ts`, `audit.spec.ts`, `honesty.spec.ts`, and the Automation tab name in `automation-workbench.spec.ts`); new assertions cover the paper container, status-band wording, the absence of invented organisations, one-row tabs, and the absence of Chinese characters in rendered chrome.
- **APIs / dependencies**: no new dependencies; `/api/documents/*` and `/runs*` contracts unchanged; the audit projection and snapshot digest must stay byte-identical (the existing golden tests are the guard).
- **Risks**: presentation work can break text-based e2e selectors; "closer to the prototype" conflicts with "never invent facts" (the prototype's parties, template number, organisations and fixed findings cannot be copied); paper layout can narrow the editing area or break keyboard reachability; pinning the assistant locale to English narrows what the demo corpus can answer.
- **Language of these artifacts**: written in English at the requester's explicit direction, overriding the project default that artifacts are written in Chinese. The archived `workspace-shell` and `interface-language` specs will therefore be the first English capabilities in this repository.
**Explicitly out of scope**: Chinese localisation, new approval/comment/export/identity/version-compare capabilities, backend and state-machine changes, real business metadata, bank brand assets, and the prototype's fixed demo data.