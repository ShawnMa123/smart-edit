# Tasks

## 1. Design tokens and shared styles

- [x] 1.1 Define `--canvas`, `--radius`, `--radius-tag` in `web/src/styles.css`, adjust `--bg` / `--border`, and replace existing 6px/8px radii with the variables; verify `npm --prefix web run typecheck` passes and `npm --prefix web run test` stays green (existing class names unchanged).
- [x] 1.2 Change `.status` from an outlined pill to a square light-filled tag with a text label and add a shared `.tag` (with `tag--ok/warn/bad/muted`); verify `StatusChip` and the `.checks` unit tests pass and a browser check shows every status still carries both a word and a colour.
- [x] 1.3 Add base styles for `.empty` (icon/title/hint/action), `.metric`, `.editor-status`, `.paper-wrap`, `.paper`, `.paper-head`, `.paper-foot`; verify `npm --prefix web run build` succeeds and each new class name is present in `styles.css`.

## 2. Shell layers: top bar, environment strip, document header

- [x] 2.1 Add `web/src/components/AppShell.tsx` (`TopBar`, `EnvironmentStrip`, `DocumentHead`) and render it in `App.tsx` outside `.work-grid`, with no user or organisation identity; verify `App.test.tsx`'s `paneLabels()` assertions still pass (`.work-grid > *` is still exactly three panes).
- [x] 2.2 Restructure the header meta: breadcrumb, title, `Draft` tag and `{n} captured versions · {chars} characters · server draft rev {n}` stay visible, while `content_sha256`, lock lease and storage key move under `<details><summary>Technical details</summary>`; verify `e2e/draft.spec.ts`'s `/server draft rev/` assertion passes and a new unit test finds the digest inside the details control.
- [x] 2.3 Give the top bar a configurable product constant (default `Trade workspace`) and only a `Local demo session` label plus environment entry on the right; verify a new `AppShell` unit test asserts the bar contains no email, `Alpha Tech`, `HSBC` or member-management wording.
- [x] 2.4 Make `EnvironmentStrip` state the three boundaries (synthetic data, fixed snapshot with no approval by the assistant, history and templates in this browser only) and render it in both desktop and narrow layouts; verify new assertions in `e2e/layout.spec.ts` (visible, contains `synthetic`, `does not approve`, `this browser`) and a visibility assertion in `e2e/narrow.spec.ts`.
- [x] 2.5 Restyle `DocumentActions`: `Export` / `Formatting` / `Start approval` become quiet buttons with a `Not available` tag while keeping `data-unavailable`, the `${label} · not implemented` accessible name and the existing click-through status message; verify `DocumentActions.test.tsx` passes and a new assertion finds the tag text.
- [x] 2.6 Document the three shell layers and the "no unauthenticated identity" rule in `web/README.md`; verify the section is greppable and its commands match the real `npm --prefix web` scripts.

## 3. Page editor and status band

- [x] 3.1 Add `.paper-wrap > article.paper` (with `paper-head` / `paper-foot`) to `RichEditor` while leaving `EditorContent` and `data-testid="editor-rich"` in place; verify `RichEditor.test.tsx` passes (including `11 characters in the audit text`) and a new assertion finds `article.paper` containing `[data-testid="editor-rich"]`.
- [x] 3.2 Style the page body (serif 14/1.95, `max-width: 790px`, `padding: 43px 47px`), show the real `documentId` plus `WORKING COPY` in the page header and the version count in the footer; verify a unit test finds `demo-document` and `WORKING COPY` inside the page and finds no `DG-2026-00417`.
- [x] 3.3 Add `.editor-status` and move `data-testid="save-state"` into it verbatim (same message branches), alongside `snapshot v{n}`, `draft rev {n}` and `lock: this session|unknown`; verify `e2e/draft.spec.ts`, `App.test.tsx` and `App.draft.test.tsx` pass.
- [x] 3.4 Make the conflict state share one `saveState` branch between the band and the conflict panel, and assert the two cannot contradict; verify the new case in `RichEditor.conflict.test.tsx` passes.
- [x] 3.5 Adapt the page for narrow viewports (`paper-wrap` scrolls, page `width: 100%`, reduced padding); verify `e2e/narrow.spec.ts` passes and a new assertion checks `document.documentElement.scrollWidth <= clientWidth`.
- [x] 3.6 Extend the editor section of `web/README.md` with the page structure and the status-band field sources; verify `paper` and `save-state` are greppable there.

## 4. Version sidebar

- [x] 4.1 Restyle the version list as a timeline (left rule plus dots) and add a `current` word tag in addition to `data-current`; verify `VersionPanel.test.tsx` passes and a new assertion checks the `current` text follows `currentVersionId`.
- [x] 4.2 Add an optional `facts?: { documentId?: string; draftRevision?: number | null }` and render a "Document info" block with real metadata only (version count, storage locality, optional document id / revision); verify a new unit test asserts that without `facts` no `organization`, `workspace` or `participants` wording appears.
- [x] 4.3 Replace the empty list with `EmptyState` (icon, title, hint, `Capture version`); verify `VersionPanel.test.tsx`'s `/No versions yet/` and `Capture version` assertions still pass.
- [x] 4.4 Pass `documentId` and `draft?.revision` from `App.tsx` into `VersionPanel`; verify `App.test.tsx` passes and a browser check shows `demo-document` in the info block.

## 5. Assistant pane frame and empty states

- [x] 5.1 Give `TABS` a `shortLabel` and `statusLabel`, render the short label plus an `aria-hidden` status tag, and keep the current `aria-label`; verify `AssistantPanel.test.tsx` passes, including `Automation · fixture only` and `Legal advice · not implemented`.
- [x] 5.2 Fit four tabs on one row at 352px (`flex: 1`, `white-space: nowrap`, tighter padding); verify a new `e2e/layout.spec.ts` assertion checks the four tab heights match and the tablist height stays within 44px.
- [x] 5.3 Collapse the pane footnote to one line that still contains `does not approve or submit`, and remove long explanations duplicated by the environment band; verify `AssistantPanel.test.tsx`'s `/does not approve or submit/i` passes and `e2e/audit.spec.ts`'s `Fixture-backed run` and `33 of 51 planned checks assessed` assertions are unchanged.
- [x] 5.4 Replace the audit-not-run surface with `EmptyState` (title, scope summary, `Run spec audit` primary action) and render result metrics through `.metrics`; verify `App.test.tsx`'s `Run spec audit` assertion and `e2e/audit.spec.ts` pass.
- [x] 5.5 Replace the knowledge-not-asked surface with `EmptyState` (title, what can be asked, question input still visible); verify `e2e/knowledge.spec.ts` passes and `AssistantPanel.test.tsx`'s `Knowledge question` and `Ask` assertions hold.
- [x] 5.6 Document the short-label plus capability-tag convention in `web/README.md`; verify `Fixture only` and the accessible-name rule are greppable there.

## 6. English-only interface

- [x] 6.1 Set `lang="en"` in `web/index.html` and keep the English `<title>`; verify a new e2e assertion reads `document.documentElement.lang === 'en'` and a non-empty English `document.title`.
- [x] 6.2 Render the header title from `draft?.title` with the `Untitled document` fallback and the breadcrumb from `draft?.document_id`, removing the Chinese gloss and `DG-2026-00417`; verify a new unit test renders an untitled draft and finds `Untitled document`, and finds neither `见索即付保函` nor `DG-2026-00417` anywhere in the header.
- [x] 6.3 Pin the knowledge binding to `locale="en"` in `App.tsx` and correct the outdated comment in `knowledgeSuggestions.ts`; verify `e2e/knowledge.spec.ts` passes and a new assertion checks the session request carries `locale: 'en'`.
- [x] 6.4 Add the chrome-only CJK guard from design D13: collect text from the named chrome roots and assert no CJK code point, excluding the editor body and citation text; verify the new e2e assertion passes in both desktop and narrow projects.
- [x] 6.5 Record the English-only baseline in `web/README.md` (chrome copy, `lang`, assistant locale, title source); verify the section is greppable and agrees with the implemented behaviour.

## 7. Integration verification and visual comparison

- [x] 7.1 Run `npm --prefix web run verify` (typecheck + vitest + playwright) and fix every regression; verify the command exits 0 with no failing tests.
- [x] 7.2 Compare screenshots at 1440×900 and 1024×800 against `tradeAI_requirementDesign_v2/HSBC_Nexus_Document_Editor_Mock_Demo.html` and confirm shell layers, page, status band and single-row tabs; verify no horizontal scrolling, one-row tabs and a visible environment band in both viewports.
- [x] 7.3 Re-check honesty: no sample counterparties, template numbers, organisations or fixed findings, and no contradiction between the environment band and panel-level statements; verify by grepping the build output (`web/dist/assets/*.js`) and confirming `Alpha Tech`, `DG-2026-00417`, `跨组织共享` and `见索即付保函` are absent.

## Workflow follow-up

- Archive this change once the project's review requirements are satisfied, and confirm both `workspace-shell` and `interface-language` purposes were carried into the main specs.
- Keep a future Chinese-localisation effort scoped as a separate change that modifies `interface-language` rather than adding ad-hoc translations.