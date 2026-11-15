import { Fragment, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import { ApiError } from './api/errors';
import { createRun, createRunWithFiles, triggerStage } from './api/client';
import { acquireLock, createDocument, getDocument, getDraft, saveDraft, type DraftView, type LockView } from './api/documents';
import type { AssistantSelection } from './api/assistantTypes';
import type { ImportedDocument } from './api/types';
import { auditReducer, initialAuditState } from './auditMachine';
import { fieldChecksRan } from './auditView';
import { richToPlainText } from './rich/plainText';
import { plainTextToDocument, type RichDocument } from './rich/richDocument';
import { createSnapshot, digestText } from './snapshot';
import { versionStore, type VersionEntry } from './versionStore';
import { AssistantPanel } from './components/AssistantPanel';
import { DocumentActions } from './components/DocumentActions';
import { ImportReport, initialImportState, type ImportState } from './components/ImportReport';
import { RichEditor } from './components/RichEditor';
import { VersionPanel } from './components/VersionPanel';
import { useNarrowViewport } from './components/useViewport';

const DOCUMENT_ID = 'demo-document';
type PaneId = 'versions' | 'editor' | 'assistant';
type SaveState = 'local' | 'saving' | 'saved' | 'conflict' | 'error';

interface ConflictState {
  revision: number;
  sha256: string;
  server: DraftView | null;
}

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
  /** Which published template to audit against; empty means "rule bundle only" (design D18). */
  const [templateId, setTemplateId] = useState('');
  /** File-import round: what was uploaded and how it went (`document-import` D10). */
  const [importState, setImportState] = useState<ImportState>(initialImportState);
  /** Latest editor selection in projected text offsets; sent only when asking about a passage. */
  const [knowledgeSelection, setKnowledgeSelection] = useState<AssistantSelection | null>(null);
  /** A selection the editor handed to the Automation workbench (right-click or Alt+Shift+V). */
  const [pendingVariable, setPendingVariable] = useState<AssistantSelection | null>(null);
  /** Whether the rich editor started; variable actions are unavailable in the textarea fallback. */
  const [editorMode, setEditorMode] = useState<'rich' | 'fallback'>('rich');
  const [draft, setDraft] = useState<DraftView | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('local');
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const draftRef = useRef<DraftView | null>(null);
  const lockRef = useRef<LockView | null>(null);
  const richDocRef = useRef<RichDocument>(richDoc);
  const userEditedRef = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const aliveRef = useRef(true);

  // First load: the server draft is authoritative. If none exists, seed one from the editor.
  useEffect(() => {
    aliveRef.current = true;
    const load = async () => {
      try {
        let view: DraftView;
        try {
          view = await getDocument(DOCUMENT_ID);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            view = await createDocument({
              document_id: DOCUMENT_ID,
              title: 'Demand Guarantee',
              content: plainTextToDocument(''),
            });
          } else {
            throw error;
          }
        }
        const lockView = await acquireLock(view.document_id, view.draft_id);
        if (!aliveRef.current) return;
        draftRef.current = view;
        lockRef.current = lockView;
        setDraft(view);
        if (!userEditedRef.current) {
          setRichDoc(view.content);
          richDocRef.current = view.content;
          setDirty(false);
          setSaveState('saved');
        } else {
          // The operator typed before the draft arrived: never replace their content. Save it
          // against the revision we just loaded instead.
          scheduleSave(richDocRef.current);
        }
      } catch {
        if (aliveRef.current) setSaveState('local');
      }
    };
    void load();
    return () => {
      aliveRef.current = false;
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
    // The editor starts empty; a later local edit schedules its own save.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applySaveResult = (next: DraftView) => {
    draftRef.current = next;
    setDraft(next);
    setDirty(false);
    setSaveState('saved');
    setConflict(null);
    setRecoveryNotice(null);
  };

  const handleConflict = (error: ApiError, nextDoc: RichDocument, nextText: string) => {
    const detail = (error.detail ?? {}) as { current_revision?: number; content_sha256?: string };
    const state: ConflictState = {
      revision: detail.current_revision ?? 0,
      sha256: detail.content_sha256 ?? '',
      server: null,
    };
    setConflict(state);
    setSaveState('conflict');
    try {
      globalThis.localStorage?.setItem(
        `smart-edit:recovery:${DOCUMENT_ID}`,
        JSON.stringify({
          text: nextText,
          rich: nextDoc,
          at: new Date().toISOString(),
          serverRevision: state.revision,
          serverSha256: state.sha256,
        }),
      );
      setRecoveryNotice('A recovery draft is stored in this browser.');
    } catch {
      setRecoveryNotice('Could not store a recovery draft in this browser.');
    }
    const current = draftRef.current;
    if (current) {
      void getDraft(current.document_id, current.draft_id)
        .then((server) => {
          if (aliveRef.current) setConflict((previous) => (previous ? { ...previous, server } : previous));
        })
        .catch(() => undefined);
    }
  };

  const scheduleSave = (nextDoc: RichDocument) => {
    setDirty(true);
    setSaveState('saving');
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    const currentDraft = draftRef.current;
    const currentLock = lockRef.current;
    if (!currentDraft || !currentLock) {
      setSaveState('local');
      return;
    }
    const nextText = richToPlainText(nextDoc);
    saveTimer.current = window.setTimeout(() => {
      void saveDraft(
        currentDraft.document_id,
        currentDraft.draft_id,
        currentDraft.revision,
        {
          content: nextDoc,
          text: nextText,
          lockId: currentLock.lock_id,
          fencingToken: currentLock.fencing_token,
        },
      )
        .then((next) => {
          if (aliveRef.current) applySaveResult(next);
        })
        .catch((error) => {
          if (!aliveRef.current) return;
          if (error instanceof ApiError && error.status === 412) {
            handleConflict(error, nextDoc, nextText);
          } else {
            setSaveState('error');
          }
        });
    }, 2000);
  };

  const useServerVersion = async () => {
    let server = conflict?.server;
    const current = draftRef.current;
    if (!server && current) {
      try {
        server = await getDraft(current.document_id, current.draft_id);
      } catch {
        return;
      }
    }
    if (server) {
      richDocRef.current = server.content;
      setRichDoc(server.content);
      applySaveResult(server);
    }
    setConflict(null);
    setPane('editor');
  };

  const overwriteWithLocal = async () => {
    let server = conflict?.server;
    const current = draftRef.current;
    const currentLock = lockRef.current;
    if (!server && current) {
      try {
        server = await getDraft(current.document_id, current.draft_id);
      } catch {
        return;
      }
    }
    if (!server || !currentLock) return;
    try {
      const next = await saveDraft(server.document_id, server.draft_id, server.revision, {
        content: richDoc,
        text,
        lockId: currentLock.lock_id,
        fencingToken: currentLock.fencing_token,
      });
      if (!aliveRef.current) return;
      applySaveResult(next);
      setPane('editor');
    } catch {
      if (aliveRef.current) setSaveState('error');
    }
  };

  const keepLocalRecovery = () => {
    setConflict(null);
    setSaveState('local');
  };

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
    userEditedRef.current = true;
    richDocRef.current = next;
    setRichDoc(next);
    // A selection from the previous text no longer maps to the snapshot offsets.
    setKnowledgeSelection(null);
    scheduleSave(next);
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
    const next = versionStore.restoreRich(DOCUMENT_ID, id) ?? plainTextToDocument(restored);
    userEditedRef.current = true;
    richDocRef.current = next;
    setRichDoc(next);
    setCurrentVersionId(id);
    setPane('editor');
    scheduleSave(next);
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
  const replaceDocument = (
    next: RichDocument,
    options: { confirm?: boolean } = {},
  ) => {
    const { confirm = true } = options;
    const hasUserText = text.trim().length > 0 && dirty;
    if (confirm && hasUserText && !window.confirm('Replace the current editor content with the imported text?')) {
      return false;
    }
    setRichDoc(next);
    richDocRef.current = next;
    userEditedRef.current = true;
    setKnowledgeSelection(null);
    setPane('editor');
    scheduleSave(next);
    return true;
  };

  /** Template apply confirms inside the workbench; App only performs the replacement/autosave. */
  const handleApplyTemplate = (next: RichDocument) => {
    replaceDocument(next, { confirm: false });
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
      <RichEditor
        document={richDoc}
        onChange={handleDocumentChange}
        dirty={dirty}
        onSelection={setKnowledgeSelection}
        onMarkVariable={setPendingVariable}
        onModeChange={setEditorMode}
        saveState={saveState}
        conflict={conflict}
        recoveryNotice={recoveryNotice}
        onUseServer={useServerVersion}
        onOverwriteLocal={() => void overwriteWithLocal()}
        onKeepLocal={keepLocalRecovery}
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
        knowledge={{
          documentId: DOCUMENT_ID,
          digest: currentDigest,
          text,
          selection: knowledgeSelection,
        }}
        automation={{
          draft,
          document: richDoc,
          selection: knowledgeSelection,
          pendingVariable,
          digest: currentDigest,
          richEditorAvailable: editorMode === 'rich',
          onApplyTemplate: handleApplyTemplate,
          onChange: handleDocumentChange,
          onVariableHandled: () => setPendingVariable(null),
        }}
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
            {text.length} characters ·{' '}
            {draft ? `server draft rev ${draft.revision}` : 'server draft local-only'} ·{' '}
            history stored in this browser
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
        {narrow ? (
          panes[pane]
        ) : (
          [
            <Fragment key="versions">{panes.versions}</Fragment>,
            <Fragment key="editor">{panes.editor}</Fragment>,
            <Fragment key="assistant">{panes.assistant}</Fragment>,
          ]
        )}
      </div>
    </div>
  );
}