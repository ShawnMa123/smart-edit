import { useEffect, useReducer, useState } from 'react';

import { ApiError } from './api/errors';
import { createRun, createRunWithFiles, triggerStage } from './api/client';
import type { ImportedDocument } from './api/types';
import { auditReducer, initialAuditState } from './auditMachine';
import { fieldChecksRan } from './auditView';
import { createSnapshot, digestText } from './snapshot';
import { versionStore, type VersionEntry } from './versionStore';
import { AssistantPanel } from './components/AssistantPanel';
import { DocumentActions } from './components/DocumentActions';
import { EditorColumn } from './components/EditorColumn';
import { ImportReport, initialImportState, type ImportState } from './components/ImportReport';
import { VersionPanel } from './components/VersionPanel';
import { useNarrowViewport } from './components/useViewport';

const DOCUMENT_ID = 'demo-document';
type PaneId = 'versions' | 'editor' | 'assistant';

export function App() {
  const narrow = useNarrowViewport();
  const [pane, setPane] = useState<PaneId>('editor');
  const [text, setText] = useState('');
  const [dirty, setDirty] = useState(false);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [versions, setVersions] = useState<VersionEntry[]>(() => versionStore.list(DOCUMENT_ID));
  const [currentDigest, setCurrentDigest] = useState('');
  const [now, setNow] = useState(() => Date.now());
  const [audit, dispatch] = useReducer(auditReducer, initialAuditState);
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

  const handleChange = (next: string) => {
    setText(next);
    setDirty(true);
  };

  const handleCapture = async () => {
    const snapshot = await createSnapshot(text, currentVersionId);
    const version = versionStore.capture(DOCUMENT_ID, { digest: snapshot.digest, text });
    refreshVersions();
    setCurrentVersionId(version.id);
    setDirty(false);
  };

  const handleRestore = (id: string) => {
    const restored = versionStore.restore(DOCUMENT_ID, id);
    if (restored === null) return;
    setText(restored);
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
  const replaceText = (next: string) => {
    const hasUserText = text.trim().length > 0 && dirty;
    if (hasUserText && !window.confirm('Replace the current editor content with the imported text?')) {
      return false;
    }
    setText(next);
    setDirty(true);
    setPane('editor');
    return true;
  };

  const handleUseImported = (document: ImportedDocument) => {
    if (replaceText(document.full_text)) setImportState(initialImportState);
  };

  const handleStartBlank = () => {
    if (replaceText('')) setImportState(initialImportState);
  };

  const handleRunAudit = async () => {
    const snapshot = await createSnapshot(text, currentVersionId);
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
      <EditorColumn
        text={text}
        dirty={dirty}
        onChange={handleChange}
        onCapture={() => void handleCapture()}
      />
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