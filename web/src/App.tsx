import { Fragment, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import { ApiError } from './api/errors';
import { createRun, createRunWithFiles, triggerStage } from './api/client';
import {
  acquireLock,
  createDocument,
  getDocument,
  getDraft,
  listDocuments,
  releaseLock,
  saveDraft,
  type DocumentSummary,
  type DraftView,
  type LockView,
} from './api/documents';
import type { AssistantSelection } from './api/assistantTypes';
import type { ImportedDocument } from './api/types';
import { auditReducer, initialAuditState } from './auditMachine';
import { auditSummary, fieldChecksRan } from './auditView';
import { richToPlainText } from './rich/plainText';
import { plainTextToDocument, type RichDocument } from './rich/richDocument';
import { createSnapshot, digestText } from './snapshot';
import { versionStore, type VersionEntry } from './versionStore';
import { activityStore, type ActivityEntry, type ActivityInput } from './workspace/activityStore';
import { demoUser, seedDemoState, type DemoActivity, type DemoComment, type DemoState, type DemoUserId } from './demo/demoData';
import { readDemoMode, writeDemoMode } from './demo/demoMode';
import { demoStore } from './demo/demoStore';
import { confirmHandoff, decideApproval, startApproval, type DemoDecision } from './demo/demoApproval';
import { AssistantPanel } from './components/AssistantPanel';
import { ActivityPanel } from './components/ActivityPanel';
import { DocumentHead, EnvironmentStrip, TopBar } from './components/AppShell';
import { DocumentActions } from './components/DocumentActions';
import { ImportReport, initialImportState, type ImportState } from './components/ImportReport';
import { NotificationPanel } from './components/NotificationPanel';
import { DemoActivityPanel } from './components/DemoActivityPanel';
import { DemoNotificationPanel } from './components/DemoNotificationPanel';
import { DemoApprovalDialog } from './components/DemoApprovalDialog';
import { DemoCommentsDialog } from './components/DemoCommentsDialog';
import { DemoIdentityDialog } from './components/DemoIdentityDialog';
import { DemoPeopleDialog } from './components/DemoPeopleDialog';
import { RichEditor } from './components/RichEditor';
import { VersionPanel } from './components/VersionPanel';
import { VersionCompareDialog } from './components/VersionCompareDialog';
import { WorkspaceDialog } from './components/WorkspaceDialog';
import { WorkspaceRail } from './components/WorkspaceRail';
import { useNarrowViewport } from './components/useViewport';
import {
  MODULE_LABELS,
  MODULE_TITLES,
  RAIL_ENTRIES,
  type WorkspaceModule,
  type WorkspaceNavTarget,
} from './workspace/workspaceModules';
import {
  UnavailableModuleDialog,
  type UnavailableModule,
} from './components/UnavailableModuleDialog';
import { ImplementationMap } from './components/ImplementationMap';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import type { AuthStatus } from './auth/AuthProvider';
import type { AuthProfile } from './api/identityTypes';
import { LoginPage } from './components/LoginPage';
import { PeoplePanel } from './components/PeoplePanel';
import { ActivityFeed } from './components/ActivityFeed';
import { DeveloperPanel } from './components/DeveloperPanel';
import { InviteAcceptPage } from './components/InviteAcceptPage';
import { ApprovalPanel } from './components/ApprovalPanel';
import { loadApprovalCounts } from './domain/approvalCounts';
import { ApprovalStatusBanner } from './components/ApprovalStatusBanner';
import { SubmitVersionDialog } from './components/SubmitVersionDialog';
import { ToastProvider, useToast } from './components/ToastProvider';
import type { SubmissionSummary } from './api/approvalTypes';

const DEFAULT_DOCUMENT_ID = 'demo-document';
/** Applicant status refresh (`approval-ui-polish` D4); terminal statuses stop the document poll. */
const POLL_INTERVAL_MS = 10_000;
type PaneId = 'versions' | 'editor' | 'assistant';
type SaveState = 'local' | 'saving' | 'saved' | 'conflict' | 'error';

const DEMO_MODULE_TITLES: Partial<Record<WorkspaceModule, string>> = {
  identity: 'Demo identity',
  people: 'Organisation & members',
  approval: 'Approval workflow',
  comments: 'Comments',
  activity: 'Activity',
  inbox: 'Inbox',
};

/** Titles used once PG identity is active (the real modules replace the demo/empty states). */
const AUTH_MODULE_TITLES: Partial<Record<WorkspaceModule, string>> = {
  identity: 'Your account',
  people: 'Organisation & members',
  approval: 'Approvals',
  developer: 'Developer',
  activity: 'Activity',
};

interface ConflictState {
  revision: number;
  sha256: string;
  server: DraftView | null;
}

export interface AppProps {
  /** Test seam: start the auth provider from a known state instead of probing on mount. */
  authStatus?: AuthStatus;
  authProfile?: AuthProfile | null;
  autoProbe?: boolean;
}

export function App({ authStatus, authProfile, autoProbe }: AppProps = {}) {
  return (
    <AuthProvider initialStatus={authStatus} initialProfile={authProfile} autoProbe={autoProbe}>
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </AuthProvider>
  );
}

function AppContent() {
  const auth = useAuth();
  const toast = useToast();
  const workspaceId = auth.workspaceId;
  const authenticatedOrgId =
    auth.status === 'authenticated' ? auth.profile?.active_org?.org_id ?? null : null;
  const authPermissions = auth.profile?.permissions ?? [];
  const authPermissionsKey = authPermissions.join(',');
  // Automation is a Bank Operations back office. Demo/unavailable auth has no server profile to gate
  // on, so it keeps the tab; an authenticated session needs `automation.view`.
  const canUseAutomation =
    auth.status !== 'authenticated' || authPermissions.includes('automation.view');
  const inviteMatch = window.location.pathname.match(/^\/invites\/([^/]+)$/);
  const inviteToken = inviteMatch ? decodeURIComponent(inviteMatch[1]) : null;
  useEffect(() => {
    if (auth.status === 'authenticated' && window.location.pathname === '/login') {
      window.history.replaceState({}, '', '/');
    }
  }, [auth.status]);
  const narrow = useNarrowViewport();
  const [pane, setPane] = useState<PaneId>('editor');
  const [activeModule, setActiveModule] = useState<WorkspaceModule | null>(null);
  /**
   * The open document. The editor is not pinned to the demo document anymore: an applicant can keep
   * several documents, and the Approvals tab can open any of them.
   */
  const [activeDocumentId, setActiveDocumentId] = useState(DEFAULT_DOCUMENT_ID);
  /** Forces a reload even when the target document is already open (Open must always respond). */
  const [documentReloadToken, setDocumentReloadToken] = useState(0);
  const [documentList, setDocumentList] = useState<DocumentSummary[]>([]);
  const announceOpenRef = useRef(false);
  const [moduleMenuOpen, setModuleMenuOpen] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [comparePair, setComparePair] = useState<[string, string] | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>(() => activityStore.list(activeDocumentId));
  const [activityAvailable, setActivityAvailable] = useState(() => activityStore.available());
  const [demoMode, setDemoMode] = useState(() => readDemoMode());
  const [demoPersistence, setDemoPersistence] = useState(() => demoStore.available());
  const [demoState, setDemoState] = useState<DemoState>(() => demoStore.read() ?? seedDemoState());
  /** The editor owns a rich document; everything downstream reads its projection (D2/D3). */
  const [richDoc, setRichDoc] = useState<RichDocument>(() => plainTextToDocument(''));
  const text = useMemo(() => richToPlainText(richDoc), [richDoc]);
  const [dirty, setDirty] = useState(false);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [versions, setVersions] = useState<VersionEntry[]>(() => versionStore.list(activeDocumentId));
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
  /** Server-aggregated top-bar counts; `null` until the first authenticated load. */
  const [serverCounts, setServerCounts] = useState<{
    approval: number;
    activityUnread: number;
  } | null>(null);
  /** Whether this session actually holds the edit lock (design D5: unknown is its own word). */
  const [lockHeld, setLockHeld] = useState(false);
  const [lockNotice, setLockNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('local');
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const draftRef = useRef<DraftView | null>(null);
  const lockRef = useRef<LockView | null>(null);
  const richDocRef = useRef<RichDocument>(richDoc);
  const userEditedRef = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const aliveRef = useRef(true);
  /**
   * The document load must re-run when the authenticated user/organisation changes: the workspace
   * mounts before `/auth/me` answers, so a single mount-time load would 401 on the login screen and
   * leave an empty editor after signing in (and an empty autosave could then wipe the server draft).
   */
  const loadedAuthKeyRef = useRef<string>('');
  const authLoadKey =
    auth.status === 'loading' || auth.status === 'unauthenticated'
      ? null
      : `${auth.profile?.user.user_id ?? 'anonymous'}:${auth.workspaceId}:${activeDocumentId}:${documentReloadToken}`;

  // First load: the server draft is authoritative. If none exists, seed one from the editor.
  useEffect(() => {
    if (authLoadKey === null) return; // wait until /auth/me has answered
    aliveRef.current = true;
    if (loadedAuthKeyRef.current !== authLoadKey) {
      loadedAuthKeyRef.current = authLoadKey;
      // A different document/account/org starts from the server draft, never from the previous
      // session's editor state.
      userEditedRef.current = false;
      draftRef.current = null;
      lockRef.current = null;
      setDraft(null);
      setLockHeld(false);
      setLockNotice(null);
      const blank = plainTextToDocument('');
      richDocRef.current = blank;
      setRichDoc(blank);
      setDirty(false);
      setSaveState('local');
      setConflict(null);
      setKnowledgeSelection(null);
      setVersions(versionStore.list(activeDocumentId));
      setActivity(activityStore.list(activeDocumentId));
    }
    const load = async () => {
      try {
        let view: DraftView;
        try {
          view = await getDocument(activeDocumentId);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            view = await createDocument({
              document_id: activeDocumentId,
              title: 'Demand Guarantee',
              content: plainTextToDocument(''),
            });
          } else {
            throw error;
          }
        }
        const lockView = await acquireLock(view.document_id, view.draft_id).catch((error) => {
          // Reviewers can read a document without holding the edit lock; show the content read-only
          // instead of failing the whole load (Applicant / First / Second Approver testing).
          if (error instanceof ApiError && (error.status === 403 || error.status === 409)) {
            return null;
          }
          throw error;
        });
        if (!aliveRef.current) return;
        if (!lockView) {
          draftRef.current = view;
          lockRef.current = null;
          setDraft(view);
          setLockHeld(false);
          setLockNotice(
            view.submission_status && view.submission_status !== 'draft'
              ? 'This submitted version is read-only until it is returned or approved.'
              : 'Read-only: this role cannot edit or lock the document.',
          );
          setRichDoc(view.content);
          richDocRef.current = view.content;
          setDirty(false);
          setSaveState('local');
          if (announceOpenRef.current) {
            announceOpenRef.current = false;
            toast.success(`Opened “${view.title ?? 'document'}”`);
          }
          return;
        }
        draftRef.current = view;
        lockRef.current = lockView;
        setDraft(view);
        setLockHeld(true);
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
        if (announceOpenRef.current) {
          announceOpenRef.current = false;
          toast.success(`Opened “${view.title ?? 'document'}”`);
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
  }, [authLoadKey]);

  // Header switcher: every document the caller may open, refreshed after create/open.
  useEffect(() => {
    if (auth.status !== 'authenticated') return;
    let cancelled = false;
    void (async () => {
      try {
        const items = await listDocuments();
        if (!cancelled) setDocumentList(items);
      } catch {
        if (!cancelled) setDocumentList([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.status, auth.profile?.user.user_id, activeDocumentId, documentReloadToken]);

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
        `smart-edit:recovery:${activeDocumentId}`,
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
    recordActivity({
      kind: 'conflict',
      action: 'Save conflict',
      detail: 'Recovery draft kept in this browser',
      notifiable: true,
    });
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
          if (aliveRef.current) {
            applySaveResult(next);
            if (userEditedRef.current) {
              recordActivity({
                kind: 'save',
                action: 'Draft saved',
                detail: `Draft revision ${next.revision} saved`,
                notifiable: false,
              });
            }
          }
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

  // Authenticated sessions share one 10s timer for top-bar counts and the pending submission
// (`approval-status-ui` D4/D5). Hidden pages pause; terminal statuses stop the document refresh.
  useEffect(() => {
    if (!authenticatedOrgId) {
      setServerCounts(null);
      return;
    }
    let alive = true;
    const refreshCounts = () => {
      void loadApprovalCounts(authenticatedOrgId, authPermissions).then((counts) => {
        if (alive) setServerCounts(counts);
      });
    };
    const refreshSubmission = () => {
      void getDocument(activeDocumentId)
        .then((fresh) => {
          if (!alive || !aliveRef.current) return;
          draftRef.current = fresh;
          setDraft(fresh);
          // Pending/approved submissions are read-only, so replacing the editor content is safe
          // only while this session holds no lock and the operator has not typed locally.
          if (!lockRef.current && !userEditedRef.current) {
            richDocRef.current = fresh.content;
            setRichDoc(fresh.content);
          }
        })
        .catch(() => undefined);
    };
    const tick = () => {
      if (globalThis.document?.visibilityState === 'hidden') return;
      refreshCounts();
      const status = draftRef.current?.submission_status;
      if (status === 'pending_first' || status === 'pending_second') refreshSubmission();
    };
    refreshCounts();
    const timer = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
    // `authPermissions` is captured by key; the array identity changes with the profile object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authPermissionsKey, authenticatedOrgId]);

  const refreshVersions = () => setVersions(versionStore.list(activeDocumentId));

  // `legal-document-risk-scan`: a finding's anchor is a top-level block index, so "jump to clause"
  // only has to focus the editor and let it place the caret in that block.
  const [focusBlock, setFocusBlock] = useState<number | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const handleJumpToBlock = (blockIndex: number) => {
    setPane('editor');
    setFocusBlock(blockIndex);
    setFocusToken((value) => value + 1);
  };

  const recordActivity = (input: ActivityInput) => {
    activityStore.record(activeDocumentId, input);
    setActivity(activityStore.list(activeDocumentId));
    setActivityAvailable(activityStore.available());
  };

  /** Every edit arrives as a document; the projected text is derived, never typed twice. */
  const handleDocumentChange = (next: RichDocument) => {
    if (next === richDoc) return;
    const nextText = richToPlainText(next);
    const serverText = draftRef.current?.text ?? '';
    if (!userEditedRef.current && nextText.trim() === '' && serverText.trim() !== '') {
      // The editor can emit its empty initial document before the server draft is applied. Treating
      // that as an edit used to autosave an empty body over a non-empty draft.
      return;
    }
    userEditedRef.current = true;
    richDocRef.current = next;
    setRichDoc(next);
    // A selection from the previous text no longer maps to the snapshot offsets.
    setKnowledgeSelection(null);
    scheduleSave(next);
  };

  const handleCapture = async () => {
    const snapshot = await createSnapshot(text, currentVersionId);
    const version = versionStore.capture(activeDocumentId, {
      digest: snapshot.digest,
      text,
      rich: richDoc,
    });
    refreshVersions();
    setCurrentVersionId(version.id);
    setDirty(false);
    recordActivity({
      kind: 'capture',
      action: 'Version captured',
      detail: `${version.label} captured`,
      notifiable: true,
    });
  };

  const handleRestore = (id: string) => {
    const restored = versionStore.restore(activeDocumentId, id);
    if (restored === null) return;
    // Older entries have no rich document: they come back as paragraphs of the same text.
    const next = versionStore.restoreRich(activeDocumentId, id) ?? plainTextToDocument(restored);
    userEditedRef.current = true;
    richDocRef.current = next;
    setRichDoc(next);
    setCurrentVersionId(id);
    setPane('editor');
    scheduleSave(next);
    recordActivity({
      kind: 'restore',
      action: 'Version restored',
      detail: `${versions.find((version) => version.id === id)?.label ?? 'Version'} loaded as draft`,
      notifiable: false,
    });
  };

  const handleClear = () => {
    versionStore.clear(activeDocumentId);
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
      recordActivity({
        kind: 'import',
        action: 'Import complete',
        detail: `Parsed ${parsed.documents?.length ?? 0} file(s)`,
        notifiable: true,
      });
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? { code: error.code, message: error.message }
          : { code: 'NETWORK', message: String(error) };
      setImportState({ phase: 'failed', documents: [], failure });
      recordActivity({
        kind: 'import',
        action: 'Import failed',
        detail: `Import failed: ${failure.code}`,
        notifiable: true,
      });
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
    if (replaceDocument(next, { confirm: false })) {
      recordActivity({
        kind: 'template',
        action: 'Template applied',
        detail: 'Template applied to the editor',
        notifiable: true,
      });
    }
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
    recordActivity({
      kind: 'audit',
      action: 'Audit started',
      detail: 'Audit started',
      notifiable: false,
    });
    try {
      const created = await createRun(snapshot.text);
      // The audit only runs on values, never on placeholders: with no provider `normalize` still
      // reports `done` while every field is a placeholder, so the guard is `extract` **and** `normalize`.
      //
      // Pass the template to `normalize` too: `normalize` backfills `extract`, and a template may name
      // the extraction profile (change D7). Without this the page could never reach the deterministic
      // path — it would always extract with the fixture/LLM before the audit even starts.
      const template = templateId.trim() || undefined;
      const normalized = await triggerStage(created.thread_id, 'normalize', { template });
      const report = fieldChecksRan(normalized)
        ? await triggerStage(created.thread_id, 'audit', { template })
        : normalized;
      dispatch({ type: 'succeed', envelope: report, at: Date.now() });
      const summary = auditSummary(report);
      recordActivity({
        kind: 'audit',
        action: 'Audit completed',
        detail: `Audit completed: ${summary.findings.length} finding(s)`,
        notifiable: true,
      });
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? { code: error.code, message: error.message, detail: error.detail }
          : { code: 'NETWORK', message: String(error) };
      dispatch({ type: 'fail', failure, at: Date.now() });
      recordActivity({
        kind: 'audit',
        action: 'Audit failed',
        detail: `Audit failed: ${failure.code}`,
        notifiable: true,
      });
    }
  };

  // "Stop waiting" only drops this client's interest: the reducer ignores the late response, so a
  // run that finishes afterwards can never be rendered as if it were still current.
  const handleStopWaiting = () => dispatch({ type: 'reset' });

  const facts = {
    documentId: draft?.document_id ?? activeDocumentId,
    title: draft?.title ?? 'Untitled document',
    versions: versions.length,
    characters: text.length,
    draftRevision: draft?.revision ?? null,
    draftSha256: draft?.content_sha256 ?? null,
    provenance: richDoc.provenance ?? null,
    lockLabel: lockHeld ? 'held by this session' : 'unknown',
  };

  const submissionStatus = draft?.submission_status ?? 'draft';
  /** Real approval state is only shown for an authenticated PG session (D8). */
  const realSubmission = auth.status === 'authenticated';
  const submissionReadOnly = ['pending_first', 'pending_second', 'approved'].includes(
    submissionStatus,
  );
  const submissionComment = draft?.submission?.latest_comment ?? null;

  const panes: Record<PaneId, JSX.Element> = {
    versions: (
      <VersionPanel
        versions={versions}
        currentVersionId={currentVersionId}
        onCapture={() => void handleCapture()}
        onRestore={handleRestore}
        onClear={handleClear}
        onCompare={(ids) => setComparePair(ids)}
        facts={{ documentId: facts.documentId, draftRevision: facts.draftRevision }}
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
        onReleaseLock={handleReleaseLock}
        onStartEditing={handleStartEditing}
        onSubmitVersion={handleSubmitVersion}
        lockNotice={lockNotice}
        submissionStatus={submissionStatus}
        submissionComment={submissionComment}
        readOnly={submissionReadOnly}
        documentId={facts.documentId}
        versions={facts.versions}
        draftRevision={facts.draftRevision}
        lockHeld={lockHeld}
        focusBlock={focusBlock}
        focusToken={focusToken}
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
        canUseAutomation={canUseAutomation}
        knowledge={{
          documentId: activeDocumentId,
          workspaceId,
          digest: currentDigest,
          text,
          selection: knowledgeSelection,
          // English-only baseline (interface-language): the demo corpus and the UI speak English.
          locale: 'en',
          onActivity: (kind, action, detail) =>
            recordActivity({ kind, action, detail, notifiable: true }),
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
        legal={{
          documentId: activeDocumentId,
          workspaceId,
          revision: facts.draftRevision,
          contentSha: draft?.content_sha256 ?? null,
          onJumpToBlock: handleJumpToBlock,
        }}
      />
    ),
  };

  const paneLabels: Record<PaneId, string> = {
    versions: 'Version history',
    editor: 'Document',
    assistant: 'AI assistant',
  };

  const railActive: WorkspaceNavTarget | null =
    activeModule && RAIL_ENTRIES.some((entry) => entry.id === activeModule)
      ? activeModule
      : pane === 'versions'
        ? 'versions'
        : pane === 'editor'
          ? 'document'
          : null;

  const openModule = (module: WorkspaceModule) => {
    setModuleMenuOpen(false);
    if (module === 'inbox') {
      if (demoMode) {
        handleDemoMarkAllRead();
      } else {
        activityStore.markAllRead(activeDocumentId);
        setActivity(activityStore.list(activeDocumentId));
        setActivityAvailable(activityStore.available());
      }
    }
    setActiveModule(module);
  };
  const closeModule = () => setActiveModule(null);

  const handleMarkAllRead = () => {
    activityStore.markAllRead(activeDocumentId);
    setActivity(activityStore.list(activeDocumentId));
    setActivityAvailable(activityStore.available());
  };

  const handleClearActivity = () => {
    activityStore.clear(activeDocumentId);
    setActivity([]);
    setActivityAvailable(activityStore.available());
  };

  const updateDemoState = (updater: (state: DemoState) => DemoState) => {
    setDemoState((previous) => {
      const next = updater(previous);
      demoStore.write(next);
      return next;
    });
  };

  const appendDemoActivity = (
    state: DemoState,
    actorId: DemoUserId,
    action: string,
    detail: string,
    notifiable: boolean,
  ): DemoState => {
    const entry: DemoActivity = {
      id: `demo-${Date.now()}-${state.activity.length}`,
      actorId,
      action,
      detail,
      at: new Date().toISOString(),
      read: false,
      notifiable,
    };
    return { ...state, activity: [entry, ...state.activity] };
  };

  const handleDemoSelectIdentity = (id: DemoUserId) =>
    updateDemoState((state) => ({ ...state, currentUserId: id }));

  const handleDemoInviteGuest = () =>
    updateDemoState((state) =>
      appendDemoActivity(
        { ...state, guestStatus: 'active' },
        state.currentUserId,
        'Guest invited',
        'Sample external counsel invited',
        true,
      ),
    );

  const handleDemoRevokeGuest = () =>
    updateDemoState((state) =>
      appendDemoActivity(
        { ...state, guestStatus: 'revoked' },
        state.currentUserId,
        'Guest revoked',
        'Sample external counsel access revoked',
        true,
      ),
    );

  const handleDemoStartApproval = () =>
    updateDemoState((state) => {
      const approval = startApproval(state.approval, state.currentUserId);
      if (approval === state.approval) return state;
      return appendDemoActivity(
        { ...state, approval },
        state.currentUserId,
        'Approval requested',
        'Sample approval requested',
        true,
      );
    });

  const handleDemoDecision = (decision: DemoDecision) =>
    updateDemoState((state) => {
      const approval = decideApproval(state.approval, state.currentUserId, decision);
      if (approval === state.approval) return state;
      return appendDemoActivity(
        { ...state, approval },
        state.currentUserId,
        decision === 'approved' ? 'Approval approved' : 'Approval rejected',
        `Sample approval ${decision}`,
        true,
      );
    });

  const handleDemoHandoff = () =>
    updateDemoState((state) => {
      const approval = confirmHandoff(state.approval);
      if (approval === state.approval) return state;
      return appendDemoActivity(
        { ...state, approval },
        state.currentUserId,
        'Sample handoff',
        'Simulated handoff receipt recorded',
        true,
      );
    });

  const handleDemoAddComment = (text: string, quote: string | null) =>
    updateDemoState((state) => {
      const comment: DemoComment = {
        id: `demo-comment-${Date.now()}-${state.comments.length}`,
        authorId: state.currentUserId,
        text,
        quote,
        version: state.approval.version,
        createdAt: new Date().toISOString(),
        resolved: false,
      };
      return appendDemoActivity(
        { ...state, comments: [comment, ...state.comments] },
        state.currentUserId,
        'Comment added',
        'Sample comment added',
        true,
      );
    });

  const handleDemoResolveComment = (id: string) =>
    updateDemoState((state) => ({
      ...state,
      comments: state.comments.map((comment) =>
        comment.id === id ? { ...comment, resolved: true } : comment,
      ),
    }));

  function handleDemoMarkAllRead() {
    updateDemoState((state) => ({
      ...state,
      activity: state.activity.map((entry) => ({ ...entry, read: true })),
    }));
  }

  async function handleReleaseLock() {
    const lock = lockRef.current;
    const current = draftRef.current;
    if (!lock || !current) {
      setLockNotice('There is no held edit lock to release.');
      return;
    }
    try {
      await releaseLock(current.document_id, lock.lock_id);
      lockRef.current = null;
      setLockHeld(false);
      setSaveState('local');
      setLockNotice(
        dirty
          ? 'Edit lock released. Unsaved content remains in this browser only.'
          : 'Edit lock released.',
      );
    } catch {
      setLockNotice('Could not release the edit lock. The lock is still held.');
    }
  }

  async function handleStartEditing() {
    if (submissionReadOnly) {
      setLockNotice('This submission is under approval; editing is disabled.');
      return;
    }
    const current = draftRef.current;
    if (!current || lockRef.current) {
      setLockNotice('Start editing needs a server draft and no active lock.');
      return;
    }
    try {
      const next = await acquireLock(current.document_id, current.draft_id);
      lockRef.current = next;
      setLockHeld(true);
      setLockNotice(null);
      setSaveState('saving');
      // Only persist pending local edits: acquiring a lock on a freshly loaded draft must not
      // rewrite it with an editor that has not received the server content yet.
      if (userEditedRef.current) {
        scheduleSave(richDocRef.current);
      } else {
        setSaveState('saved');
      }
    } catch {
      setLockNotice('Could not acquire the edit lock. Content remains local.');
    }
  }

  function handleSubmitVersion() {
    if (demoMode) {
      setModuleMenuOpen(false);
      setActiveModule('approval');
      return;
    }
    setSubmitOpen(true);
  }

  async function handleCaptureFromSubmit() {
    await handleCapture();
    setSubmitOpen(false);
  }

  async function handleSubmitted(submission: SubmissionSummary) {
    setSubmitOpen(false);
    lockRef.current = null;
    setLockHeld(false);
    setLockNotice(`Submitted for approval (${submission.status}).`);
    try {
      const fresh = await getDocument(activeDocumentId);
      draftRef.current = fresh;
      setDraft(fresh);
      setRichDoc(fresh.content);
      richDocRef.current = fresh.content;
      setDirty(false);
      setSaveState('saved');
    } catch {
      // The status banner still shows the submission; a later reload will refresh the snapshot.
    }
  }

  const handleRailOpen = (target: WorkspaceNavTarget) => {
    if (target === 'document') {
      // Modules render as a dialog over the workspace: switching the pane behind it is not enough.
      setActiveModule(null);
      setPane('editor');
    } else if (target === 'versions') {
      setActiveModule(null);
      setPane('versions');
    } else {
      openModule(target);
    }
  };

  /** Open one of the workspace's documents in the editor (Approvals -> Open document). */
  const openDocumentById = (documentId: string) => {
    setActiveModule(null);
    setPane('editor');
    setActiveDocumentId(documentId);
    // Always force a fresh load: opening the already-active document must still respond visibly.
    announceOpenRef.current = true;
    setDocumentReloadToken((token) => token + 1);
  };

  /** Create a fresh draft so the applicant can keep submitting after one document is under review. */
  const handleNewDocument = async () => {
    try {
      const created = await createDocument({
        title: 'Untitled document',
        content: plainTextToDocument(''),
      });
      setActiveModule(null);
      setActiveDocumentId(created.document_id);
      setPane('editor');
      setLockNotice(null);
    } catch (error) {
      setLockNotice(
        error instanceof ApiError ? error.message : 'The document could not be created.',
      );
    }
  };

  const canCreateDocument = auth.profile
    ? auth.profile.permissions.includes('document.create')
    : true;

  const isUnavailableModule = (module: WorkspaceModule): module is UnavailableModule =>
    (module === 'people' && !authenticatedOrgId) ||
    (module === 'identity' && !authenticatedOrgId) ||
    (module === 'approval' && !authenticatedOrgId) ||
    module === 'comments';

  const moduleBody = (module: WorkspaceModule) => {
    if (demoMode && module === 'identity') {
      return (
        <DemoIdentityDialog state={demoState} onSelect={handleDemoSelectIdentity} />
      );
    }
    if (demoMode && module === 'people') {
      return (
        <DemoPeopleDialog
          state={demoState}
          onInviteGuest={handleDemoInviteGuest}
          onRevokeGuest={handleDemoRevokeGuest}
        />
      );
    }
    if (demoMode && module === 'approval') {
      return (
        <DemoApprovalDialog
          approval={demoState.approval}
          currentUserId={demoState.currentUserId}
          onStart={handleDemoStartApproval}
          onDecide={handleDemoDecision}
          onHandoff={handleDemoHandoff}
        />
      );
    }
    if (demoMode && module === 'comments') {
      return (
        <DemoCommentsDialog
          state={demoState}
          quote={knowledgeSelection?.selectedText ?? null}
          onAdd={handleDemoAddComment}
          onResolve={handleDemoResolveComment}
        />
      );
    }
    if (module === 'approval' && authenticatedOrgId) {
      return (
        <ApprovalPanel
          orgId={authenticatedOrgId}
          documentId={activeDocumentId}
          activeDocumentId={activeDocumentId}
          permissions={auth.profile?.permissions ?? []}
          onOpenDocument={openDocumentById}
          onNewDocument={() => void handleNewDocument()}
        />
      );
    }
    if (module === 'identity' && authenticatedOrgId) {
      return (
        <div className="identity-panel">
          <p>
            <strong>{auth.profile?.user.display_name}</strong> · {auth.profile?.user.email}
          </p>
          <p className="tiny">Roles: {(auth.profile?.roles ?? []).join(', ') || 'member'}</p>
          <button type="button" onClick={() => void auth.logout()}>
            Sign out
          </button>
          <button type="button" onClick={() => void auth.logout()}>
            Sign out of all devices
          </button>
        </div>
      );
    }
    if (module === 'people' && authenticatedOrgId) {
      return <PeoplePanel orgId={authenticatedOrgId} />;
    }
    if (module === 'activity') {
      if (authenticatedOrgId) return <ActivityFeed orgId={authenticatedOrgId} />;
      return demoMode ? (
        <DemoActivityPanel state={demoState} onMarkAllRead={handleDemoMarkAllRead} />
      ) : (
        <ActivityPanel
          activity={activity}
          available={activityAvailable}
          onClear={handleClearActivity}
        />
      );
    }
    if (module === 'inbox') {
      return demoMode ? (
        <DemoNotificationPanel state={demoState} onMarkAllRead={handleDemoMarkAllRead} />
      ) : (
        <NotificationPanel activity={activity} onMarkAllRead={handleMarkAllRead} />
      );
    }
    if (module === 'developer') {
      if (authenticatedOrgId) return <DeveloperPanel orgId={authenticatedOrgId} />;
      return <ImplementationMap />;
    }
    if (isUnavailableModule(module)) {
      return <UnavailableModuleDialog module={module} />;
    }
    return null;
  };

  const realUnreadCount = activity.filter((entry) => entry.notifiable && !entry.read).length;
  const demoUnreadCount = demoState.activity.filter(
    (entry) => entry.notifiable && !entry.read,
  ).length;
  const demoIdentity = demoMode ? demoUser(demoState.currentUserId) : null;

  const toggleDemoMode = () => {
    const next = !demoMode;
    const persisted = writeDemoMode(next);
    if (next) {
      const stored = demoStore.read();
      const nextState = stored ?? seedDemoState();
      if (!stored) demoStore.write(nextState);
      setDemoState(nextState);
    }
    setDemoPersistence(persisted && demoStore.available());
    setDemoMode(next);
  };

  const resetDemoData = () => {
    setDemoState(demoStore.reset());
    setDemoPersistence(demoStore.available());
  };
  const compareBefore = comparePair
    ? versions.find((version) => version.id === comparePair[0])
    : undefined;
  const compareAfter = comparePair
    ? versions.find((version) => version.id === comparePair[1])
    : undefined;

  if (auth.status === 'unauthenticated' || window.location.pathname === '/login') {
    return <LoginPage />;
  }
  if (inviteToken) {
    if (auth.status === 'authenticated') {
      return <InviteAcceptPage token={inviteToken} />;
    }
    return (
      <main className="auth-page">
        <section className="auth-card">
          <h1>Invite link</h1>
          <p className="tiny">
            {auth.status === 'unavailable'
              ? 'Invites require SMART_EDIT_AUTH_MODE=pg; this server is running the local demo identity.'
              : 'Checking your session…'}
          </p>
        </section>
      </main>
    );
  }

  return (
    <div className="app">
      <TopBar
        onOpenModule={openModule}
        approvalCount={
          demoMode
            ? demoState.approval.status === 'IN_REVIEW'
              ? 1
              : 0
            : authenticatedOrgId
              ? serverCounts?.approval ?? 0
              : 0
        }
        activityUnread={
          demoMode
            ? demoUnreadCount
            : authenticatedOrgId
              ? serverCounts?.activityUnread ?? 0
              : realUnreadCount
        }
        unreadCount={demoMode ? demoUnreadCount : realUnreadCount}
        demoIdentity={demoIdentity}
        organizations={auth.profile?.organizations ?? []}
        activeOrgId={auth.profile?.active_org?.org_id ?? null}
        onSwitchOrg={(orgId) => void auth.switchOrg(orgId)}
        userLabel={auth.profile?.user.display_name ?? null}
        onLogout={() => void auth.logout()}
      />
      <EnvironmentStrip
        demoMode={demoMode}
        authenticated={auth.status === 'authenticated'}
        onToggleDemo={toggleDemoMode}
        onResetDemo={resetDemoData}
        demoStorageAvailable={demoPersistence}
      />
      <div className="shell">
        {narrow ? null : <WorkspaceRail active={railActive} onOpen={handleRailOpen} />}
        <main className="workspace">
          <DocumentHead
            facts={facts}
            submissionStatus={realSubmission ? submissionStatus : 'draft'}
            submission={realSubmission ? draft?.submission ?? null : null}
            actions={
              <DocumentActions
                onImport={(files) => void handleImport(files)}
                onComments={() => openModule('comments')}
                onNewDocument={() => void handleNewDocument()}
                canCreateDocument={canCreateDocument}
                documents={documentList}
                activeDocumentId={activeDocumentId}
                onOpenDocument={openDocumentById}
                onUnavailableAction={(action) => {
                  if (action.id === 'export') {
                    recordActivity({
                      kind: 'export-attempt',
                      action: 'Export unavailable',
                      detail: action.reason,
                      notifiable: false,
                    });
                  }
                }}
              />
            }
          />

          <ApprovalStatusBanner
            status={realSubmission ? submissionStatus : 'draft'}
            submission={realSubmission ? draft?.submission ?? null : null}
            onViewApproval={() => openModule('approval')}
          />

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
              <button
                type="button"
                aria-haspopup="menu"
                aria-expanded={moduleMenuOpen}
                onClick={() => setModuleMenuOpen((open) => !open)}
              >
                More
              </button>
              {moduleMenuOpen ? (
                <div className="pane-menu" role="menu" aria-label="More workspace modules">
                  {(Object.keys(MODULE_LABELS) as WorkspaceModule[]).map((module) => (
                    <button
                      key={module}
                      type="button"
                      role="menuitem"
                      onClick={() => openModule(module)}
                    >
                      {MODULE_LABELS[module]}
                    </button>
                  ))}
                </div>
              ) : null}
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
        </main>
      </div>

      {activeModule ? (
        <WorkspaceDialog
          title={
            demoMode
              ? DEMO_MODULE_TITLES[activeModule] ?? MODULE_TITLES[activeModule]
              : authenticatedOrgId
                ? AUTH_MODULE_TITLES[activeModule] ?? MODULE_TITLES[activeModule]
                : MODULE_TITLES[activeModule]
          }
          onClose={closeModule}
        >
          {moduleBody(activeModule)}
        </WorkspaceDialog>
      ) : null}

      {compareBefore && compareAfter ? (
        <VersionCompareDialog
          before={compareBefore}
          after={compareAfter}
          onClose={() => setComparePair(null)}
        />
      ) : null}

      {submitOpen && auth.status === 'authenticated' ? (
        <SubmitVersionDialog
          draft={draft}
          lock={lockRef.current}
          onClose={() => setSubmitOpen(false)}
          onSubmitted={(submission) => void handleSubmitted(submission)}
          onViewApproval={() => {
            setSubmitOpen(false);
            setActiveModule('approval');
          }}
        />
      ) : null}

      {submitOpen && auth.status !== 'authenticated' ? (
        <WorkspaceDialog
          title="Submit new version"
          onClose={() => setSubmitOpen(false)}
          footer={
            <>
              <button type="button" onClick={() => setSubmitOpen(false)}>
                Close
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => void handleCaptureFromSubmit()}
              >
                Capture browser-local version
              </button>
            </>
          }
        >
          <p className="notice notice--warn tiny">
            <strong>Shared version submission is not available in this build.</strong>
          </p>
          <p className="tiny">
            The document is not sent to a server, no approval is started and no receipt is produced.
            You can still capture a browser-local version for comparison.
          </p>
        </WorkspaceDialog>
      ) : null}
    </div>
  );
}