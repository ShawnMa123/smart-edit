import { useEffect, useMemo, useReducer, useState } from 'react';

import { ApiError } from './api/errors';
import { createRun, createRunWithFiles, triggerStage } from './api/client';
import type { ImportedDocument } from './api/types';
import { auditReducer, initialAuditState } from './auditMachine';
import { fieldChecksRan } from './auditView';
import { richToPlainText } from './rich/plainText';
import { plainTextToDocument, type RichDocument } from './rich/richDocument';
import { createSnapshot, digestText } from './snapshot';
import { versionStore, type VersionEntry } from './versionStore';
import { AssistantPanel } from './components/AssistantPanel';
import { DocumentActions } from './components/DocumentActions';
import type { LegalState } from './components/LegalPanel';
import { ImportReport, initialImportState, type ImportState } from './components/ImportReport';
import { RichEditor } from './components/RichEditor';
import { VersionPanel } from './components/VersionPanel';
import { useNarrowViewport } from './components/useViewport';

const DOCUMENT_ID = 'demo-document';
type PaneId = 'versions' | 'editor' | 'assistant';

export function App() {
  const narrow = useNarrowViewport();
  const [pane, setPane] = useState<PaneId>('editor');
  /** The editor owns a rich document; everything downstream reads its projection (D2/D3). */
  const [richDoc, setRichDoc] = useState<RichDocument>(() => plainTextToDocument(''));
  const text = useMemo(() => richToPlainText(richDoc), [richDoc]);
  const [dirty, setDirty] = useState(false);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [versions, setVersions] = useState<VersionEntry[]>(() => versionStore.list(DOCUMENT_ID));
  const [currentDigest, setCurrentDigest] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const [audit, dispatch] = useReducer(auditReducer, initialAuditState);
  const [legalState, setLegalState] = useState<LegalState>({ phase: 'idle' });
  const [legalRun, setLegalRun] = useState<{ threadId: string; digest: string } | null>(null);
  /** Which published template to audit against; empty means "rule bundle only" (design D18). */
  const [templateId, setTemplateId] = useState('');
  /** File-import round: what was uploaded and how it went (`document-import` D10). */
  const [importState, setImportState] = useState<ImportState>(initialImportState);

  // Keep the "current" digest in step with the editor, so staleness is instant on the next keystroke.
  useEffect(() => {
    let alive = true;
    void digestText(text).then((digest) => {
      if (alive) setCurrentDigest(digest);
    });
    return () => {
      alive = false;
    };
  }, [text]);

  // Elapsed timer for the running state only.
  useEffect(() => {
    if (audit.phase !== 'running') return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [audit.phase]);

  const refreshVersions = () => setVersions(versionStore.list(DOCUMENT_ID));

  /** Every edit arrives as a document; the projected text is derived, never typed twice. */
  const handleDocumentChange = (next: RichDocument) => {
    if (next === richDoc) return;
    setRichDoc(next);
    setDirty(richToPlainText(next) !== text);
  };

  const handleCapture = async () => {
    const snapshot = await createSnapshot(text, currentVersionId);
    const version = versionStore.capture(DOCUMENT_ID, {
      digest: snapshot.digest,
      text,
      rich: richDoc,
    });
    refreshVersions();
    setCurrentVersionId(version.id);
    setDirty(false);
  };

  const handleRestore = (id: string) => {
    const restored = versionStore.restore(DOCUMENT_ID, id);
    if (restored === null) return;
    // Older entries have no rich document: they come back as paragraphs of the same text.
    setRichDoc(versionStore.restoreRich(DOCUMENT_ID, id) ?? plainTextToDocument(restored));
    setCurrentVersionId(id);
    setDirty(true);
    setPane('editor');
  };

  const handleClear = () => {
    versionStore.clear(DOCUMENT_ID);
    setVersions([]);
    setCurrentVersionId(null);
  };

  const handleImport = async (files: File[]) => {
    setImportState({ phase: 'reading', documents: [], failure: null });
    try {
      const created = await createRunWithFiles(files);
      const parsed = await triggerStage(created.thread_id, 'parse');
      setImportState({
        phase: 'ready',
        documents: parsed.documents ?? [],
        failure: null,
      });
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? { code: error.code, message: error.message }
          : { code: 'NETWORK', message: String(error) };
      setImportState({ phase: 'failed', documents: [], failure });
    }
  };

  /** Filling the editor is the only thing import does; user edits are never replaced silently. */
  const replaceDocument = (next: RichDocument) => {
    const hasUserText = text.trim().length > 0 && dirty;
    if (hasUserText && !window.confirm('Replace the current editor content with the imported text?')) {
      return false;
    }
    setRichDoc(next);
    setDirty(true);
    setPane('editor');
    return true;
  };

  /** Imported structure wins; a document without `rich` degrades to paragraphs of its text. */
  const handleUseImported = (document: ImportedDocument) => {
    const next = (document.rich as RichDocument | undefined) ?? plainTextToDocument(document.full_text);
    if (replaceDocument(next)) setImportState(initialImportState);
  };

  const handleStartBlank = () => {
    if (replaceDocument(plainTextToDocument(''))) setImportState(initialImportState);
  };

  const handleRunAudit = async () => {
    const snapshot = await createSnapshot(text, currentVersionId);
    setLegalState({ phase: 'idle' });
    dispatch({ type: 'start', snapshot, at: Date.now() });
    try {
      const created = await createRun(snapshot.text);
      // The audit only runs on values, never on placeholders: with no provider `normalize` still
      // reports `done` while every field is a placeholder, so the guard is `extract` **and** `normalize`.
      const normalized = await triggerStage(created.thread_id, 'normalize');
      const report = fieldChecksRan(normalized)
        ? await triggerStage(created.thread_id, 'audit', {
            template: templateId.trim() || undefined,
          })
        : normalized;
      dispatch({ type: 'succeed', envelope: report, at: Date.now() });
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? { code: error.code, message: error.message, detail: error.detail }
          : { code: 'NETWORK', message: String(error) };
      dispatch({ type: 'fail', failure, at: Date.now() });
    }
  };

  /**
   * Reuse the audit's run when it still matches the editor; otherwise create a fresh run from the
   * current document. The legal check is therefore usable without running the audit first, and a
   * stale audit can never make it inspect old text.
   */
  const handleRunLegal = async () => {
    if (!text.trim()) return;
    setLegalState({ phase: 'running' });
    try {
      let threadId: string;
      let digest: string;
      if (legalRun && legalRun.digest === currentDigest) {
        threadId = legalRun.threadId;
        digest = legalRun.digest;
      } else if (audit.phase === 'report' && audit.snapshot.digest === currentDigest) {
        threadId = audit.envelope.thread_id;
        digest = currentDigest;
      } else {
        const snapshot = await createSnapshot(text, currentVersionId);
        const created = await createRun(snapshot.text);
        threadId = created.thread_id;
        digest = snapshot.digest;
      }
      setLegalRun({ threadId, digest });
      const report = await triggerStage(threadId, 'agent3');
      setLegalState({ phase: 'report', envelope: report });
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? { code: error.code, message: error.message }
          : { code: 'NETWORK', message: String(error) };
      setLegalState({ phase: 'failed', failure });
    }
  };

  // "Stop waiting" only drops this client's interest: the reducer ignores the late response, so a
  // run that finishes afterwards can never be rendered as if it were still current.
  const handleStopWaiting = () => dispatch({ type: 'reset' });

  const panes: Record<PaneId, JSX.Element> = {
    versions: (
      <VersionPanel
        versions={versions}
        currentVersionId={currentVersionId}
        onCapture={() => void handleCapture()}
        onRestore={handleRestore}
        onClear={handleClear}
      />
    ),
    editor: (
      <RichEditor document={richDoc} onChange={handleDocumentChange} dirty={dirty} />
    ),
    assistant: (
      <AssistantPanel
        state={audit}
        currentDigest={currentDigest}
        onRun={() => void handleRunAudit()}
        onStopWaiting={handleStopWaiting}
        templateId={templateId}
        onTemplateChange={setTemplateId}
        now={now}
        legalState={legalState}
        onRunLegal={() => void handleRunLegal()}
        canRunLegal={text.trim().length > 0}
        legalHint="Type or import a document first."
      />
    ),
  };

  const paneLabels: Record<PaneId, string> = {
    versions: 'Version history',
    editor: 'Document',
    assistant: 'AI assistant',
  };

  return (
    <div className="app">
      <header className="document-head">
        <div>
          <div className="crumb tiny">Trade documents / Guarantees / DG-2026-00417</div>
          <h1>Demand Guarantee · 见索即付保函</h1>
          <div className="meta tiny">
            {versions.length} captured version{versions.length === 1 ? '' : 's'} ·{' '}
            {text.length} characters · history stored in this browser
          </div>
        </div>
        <DocumentActions onImport={(files) => void handleImport(files)} />
      </header>

      <ImportReport
        state={importState}
        onUse={handleUseImported}
        onRetry={() => setImportState(initialImportState)}
        onStartBlank={handleStartBlank}
      />

      {narrow ? (
        <div className="pane-tabs" role="tablist" aria-label="Workspace panes">
          {(Object.keys(paneLabels) as PaneId[]).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={pane === id}
              onClick={() => setPane(id)}
            >
              {paneLabels[id]}
            </button>
          ))}
        </div>
      ) : null}

      <div className="work-grid" data-narrow={narrow}>
        {narrow ? panes[pane] : [panes.versions, panes.editor, panes.assistant]}
      </div>
    </div>
  );
}