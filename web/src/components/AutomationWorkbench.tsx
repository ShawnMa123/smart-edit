/**
 * Automation workbench: two areas.
 *
 * `Automate` is the server path (`AutomationServerPanel`: templates, variables, dispatch, receipts).
 * `Sandbox` is browser-local: local templates, variable marking, and a payload preview whose body is
 * assembled by the server (`/automation/spec/build`) so the contract rules exist in exactly one place.
 * The sandbox never sends anything.
 */

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';

import type { AssistantSelection } from '../api/assistantTypes';
import type { DraftView } from '../api/documents';
import {
  buildPayload,
  defaultTemplateName,
  downstreamTemplates,
  matchDocument,
  suggestDefinition,
  type ApiTemplateSummary,
  type MappingCandidate,
} from '../automation/mockWorkbench';
import { describeCapture } from '../automation/templateCapture';
import { applyTemplate } from '../automation/templateApply';
import {
  buildPayload as buildContractPayload,
  parseContract,
  suggestMappings,
  type OpenApiContract,
  type OpenApiPayload,
} from '../automation/specContract';
import { downloadJson } from '../automation/payloadExport';
import {
  downstreamSystemStore,
  type DownstreamSystem,
  type DownstreamSystemInput,
  type DownstreamSystemStore,
} from '../automation/downstreamSystemStore';
import {
  MAX_TEMPLATES,
  automationTemplateStore,
  type TemplateRecord,
  type TemplateStore,
  type TemplateStoreIssue,
} from '../automation/templateStore';
import type { RichDocument } from '../rich/richDocument';
import { projectDocument } from '../rich/projection';
import { richToPlainText } from '../rich/plainText';
import { AutomationServerPanel } from './AutomationServerPanel';
import {
  collectVariables,
  replaceSelectionWithVariable,
  setVariableValue,
  variableDisplay,
  type VariableDefinition,
} from '../rich/variableOperations';

type Area = 'server' | 'sandbox';
type SandboxArea = 'template' | 'variables' | 'mapping';
type MappingSource = 'fixture' | 'openapi';

const AREAS: Array<[Area, string]> = [
  ['server', 'Automate'],
  ['sandbox', 'Sandbox'],
];

const SANDBOX_AREAS: Array<[SandboxArea, string]> = [
  ['template', 'Templates'],
  ['variables', 'Variables & fill'],
  ['mapping', 'Payload preview'],
];

const EXCERPT_LIMIT = 240;

/** Code-point-safe excerpt; never split an emoji in half. */
const excerptOf = (text: string): string => {
  if (!text.trim()) return '(no text content)';
  const chars = Array.from(text);
  return chars.length > EXCERPT_LIMIT ? `${chars.slice(0, EXCERPT_LIMIT).join('')}…` : text;
};

/** Deterministic, locale-independent display of a captured timestamp. */
const formatCapturedAt = (iso: string): string => {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)}`;
};

const recordSourceLabel = (template: TemplateRecord): string =>
  template.source.kind === 'imported'
    ? `Imported · ${template.source.provenance}${template.source.note ? ` · ${template.source.note}` : ''}`
    : 'Edited in this browser';

const systemFailureMessage = (reason: string): string => {
  switch (reason) {
    case 'invalid_name':
      return 'Enter a downstream system name.';
    case 'invalid_url':
      return 'Enter an http(s) base URL.';
    case 'invalid_auth':
      return 'Choose a supported auth type.';
    case 'spec_too_large':
      return 'The OpenAPI spec is larger than 512 KB.';
    case 'limit':
      return 'At most 10 downstream systems are supported.';
    case 'not_found':
      return 'That downstream system no longer exists.';
    default:
      return 'The downstream system could not be saved.';
  }
};

export interface AutomationWorkbenchProps {
  draft: DraftView | null;
  document: RichDocument;
  /** Latest single-block editor selection (projected offsets). */
  selection: AssistantSelection | null;
  /** A selection the editor already handed to the workbench through right-click. */
  pendingVariable: AssistantSelection | null;
  /** Current document digest, shown as the payload preview binding. */
  digest?: string;
  /** False when the editor fell back to a textarea: variable actions are unavailable. */
  richEditorAvailable?: boolean;
  /** Test seam: a store backed by a specific `Storage` (reload/persistence tests). */
  templateStore?: TemplateStore;
  /** Test seam for downstream systems. */
  downstreamStore?: DownstreamSystemStore;
  /** Apply a template snapshot to the editor (App owns the replacement/autosave path). */
  onApplyTemplate?: (document: RichDocument) => void;
  /** Which tab opens first; `Automate` (server) unless a test asks for the sandbox. */
  initialArea?: 'server' | 'sandbox';
  onChange: (document: RichDocument) => void;
  onVariableHandled: () => void;
}

export function AutomationWorkbench({
  draft,
  document,
  selection,
  pendingVariable,
  digest,
  richEditorAvailable = true,
  templateStore = automationTemplateStore,
  downstreamStore = downstreamSystemStore,
  onApplyTemplate,
  initialArea = 'server',
  onChange,
  onVariableHandled,
}: AutomationWorkbenchProps) {
  const [area, setArea] = useState<Area>(initialArea);
  const [sandboxArea, setSandboxArea] = useState<SandboxArea>('template');
  const [templates, setTemplates] = useState<TemplateRecord[]>(() => templateStore.list());
  const [templateIssue, setTemplateIssue] = useState<TemplateStoreIssue | null>(() =>
    templateStore.issue(),
  );
  const [templateName, setTemplateName] = useState(defaultTemplateName);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [renamingTemplate, setRenamingTemplate] = useState<{ id: string; name: string } | null>(
    null,
  );
  const [deletingTemplateId, setDeletingTemplateId] = useState<string | null>(null);
  const [applyingTemplateId, setApplyingTemplateId] = useState<string | null>(null);
  const [saveTemplateId, setSaveTemplateId] = useState<string | null>(null);
  const [updatingTemplateId, setUpdatingTemplateId] = useState<string | null>(null);
  const templateListRef = useRef<HTMLUListElement | null>(null);
  const [selectedVariableId, setSelectedVariableId] = useState<string | null>(null);
  const [fillValue, setFillValue] = useState('');
  /** Session registry: lets a deleted required variable be reported instead of vanishing silently. */
  const [knownVariables, setKnownVariables] = useState<
    Array<{ variableId: string; label: string; required: boolean }>
  >([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [definition, setDefinition] = useState<VariableDefinition>(suggestDefinition(''));
  const [notice, setNotice] = useState<string | null>(null);
  const [mappingTemplateId, setMappingTemplateId] = useState(downstreamTemplates[0]?.id ?? '');
  const [candidates, setCandidates] = useState<MappingCandidate[]>([]);
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [mappingSource, setMappingSource] = useState<MappingSource>('fixture');
  const [systems, setSystems] = useState<DownstreamSystem[]>(() => downstreamStore.list());
  const [systemIssue, setSystemIssue] = useState<ReturnType<DownstreamSystemStore['issue']>>(() =>
    downstreamStore.issue(),
  );
  const [selectedSystemId, setSelectedSystemId] = useState<string | null>(null);
  const [systemsOpen, setSystemsOpen] = useState(false);
  const [systemDraft, setSystemDraft] = useState<
    (DownstreamSystemInput & { id?: string }) | null
  >(null);
  const [systemError, setSystemError] = useState<string | null>(null);
  const [deletingSystemId, setDeletingSystemId] = useState<string | null>(null);
  const [openApiOperationId, setOpenApiOperationId] = useState<string | null>(null);
  const [openApiMappings, setOpenApiMappings] = useState<Record<string, string>>({});
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const labelRef = useRef<HTMLInputElement | null>(null);

  const variables = useMemo(() => collectVariables(document), [document]);
  const selectedVariable =
    variables.find((item) => item.variableId === selectedVariableId) ?? null;
  const mappingTemplate: ApiTemplateSummary | undefined = downstreamTemplates.find(
    (item) => item.id === mappingTemplateId,
  );
  const canMarkVariable = Boolean(draft) && richEditorAvailable && Boolean(selection);
  const missingRequired = knownVariables.filter(
    (known) => known.required && !variables.some((variable) => variable.variableId === known.variableId),
  );
  const capturePreview = useMemo(
    () =>
      describeCapture({
        document,
        draftRevision: draft?.revision ?? null,
        name: templateName,
        templates,
        nextVersion: templateStore.nextVersion(),
      }),
    [document, draft?.revision, templateName, templates, templateStore],
  );
  const selectedTemplate = templates.find((item) => item.id === selectedTemplateId) ?? null;
  const selectedTemplateExcerpt = selectedTemplate
    ? excerptOf(projectDocument(selectedTemplate.rich).text)
    : null;
  const hasContent = useMemo(() => projectDocument(document).text.trim().length > 0, [document]);
  const saveTargetTemplate =
    templates.find((template) => template.id === saveTemplateId) ?? templates[0] ?? null;

  useEffect(() => {
    if (!pendingVariable) return;
    setDefinition(suggestDefinition(pendingVariable.selectedText));
    setDialogOpen(true);
  }, [pendingVariable]);

  useEffect(() => {
    if (dialogOpen) labelRef.current?.focus();
  }, [dialogOpen]);

  const closeDialog = () => {
    setDialogOpen(false);
    onVariableHandled();
  };

  const refreshTemplates = () => {
    setTemplates(templateStore.list());
    setTemplateIssue(templateStore.issue());
  };

  const captureTemplate = () => {
    if (!capturePreview.canCapture) {
      setNotice(capturePreview.nameError ?? 'A template needs document content.');
      return;
    }
    const result = templateStore.capture({
      name: capturePreview.name,
      document,
      source: capturePreview.source,
      revision: capturePreview.boundRevision,
      charCount: capturePreview.charCount,
      variables: capturePreview.variables,
    });
    if (!result.ok) {
      setNotice('Enter a template name before saving.');
      return;
    }
    refreshTemplates();
    setSelectedTemplateId(result.record.id);
    setTemplateName(defaultTemplateName);
    setNotice(
      result.persisted
        ? `Saved "${result.record.name}" (${result.record.version}) in this browser — not on the server.`
        : `"${result.record.name}" is session only — browser storage failed.`,
    );
  };

  const startRenameTemplate = (template: TemplateRecord) => {
    setRenamingTemplate({ id: template.id, name: template.name });
    setDeletingTemplateId(null);
    setApplyingTemplateId(null);
  };

  const cancelRenameTemplate = () => setRenamingTemplate(null);

  const submitRenameTemplate = () => {
    if (!renamingTemplate) return;
    const result = templateStore.rename(renamingTemplate.id, renamingTemplate.name);
    if (!result.ok) {
      setNotice(
        result.reason === 'blank_name'
          ? 'Enter a template name before saving.'
          : 'That template no longer exists.',
      );
      if (result.reason === 'not_found') {
        setRenamingTemplate(null);
        refreshTemplates();
      }
      return;
    }
    refreshTemplates();
    setRenamingTemplate(null);
    setNotice(
      result.persisted
        ? `Renamed to "${result.record.name}".`
        : 'Renamed in this session only — browser storage failed.',
    );
  };

  const confirmDeleteTemplate = (template: TemplateRecord) => {
    const removed = templateStore.remove(template.id);
    refreshTemplates();
    if (selectedTemplateId === template.id) setSelectedTemplateId(null);
    setDeletingTemplateId(null);
    setNotice(
      removed ? `Deleted "${template.name}" from this browser.` : 'That template no longer exists.',
    );
    templateListRef.current?.focus();
  };

  const applySelectedTemplate = (template: TemplateRecord) => {
    if (!onApplyTemplate) return;
    const applied = applyTemplate(template);
    setKnownVariables((current) => {
      const next = [...current];
      for (const variable of applied.variables) {
        if (!next.some((item) => item.variableId === variable.variableId)) {
          next.push(variable);
        }
      }
      return next;
    });
    onApplyTemplate(applied.document);
    setApplyingTemplateId(null);
    setNotice(
      `Applied "${template.name}" (${template.version}) to the editor — continue editing there.`,
    );
  };

  const updateTemplateFromDocument = (template: TemplateRecord) => {
    const result = templateStore.update(template.id, {
      document,
      source: capturePreview.source,
      revision: capturePreview.boundRevision,
      charCount: capturePreview.charCount,
      variables: capturePreview.variables,
    });
    if (!result.ok) {
      setNotice('That template no longer exists.');
      setUpdatingTemplateId(null);
      refreshTemplates();
      return;
    }
    refreshTemplates();
    setSelectedTemplateId(result.record.id);
    setSaveTemplateId(result.record.id);
    setUpdatingTemplateId(null);
    setNotice(
      result.persisted
        ? `Updated "${result.record.name}" to ${result.record.version} in this browser.`
        : `Updated "${result.record.name}" in this session only — browser storage failed.`,
    );
  };

  const openVariableDialog = () => {
    const target = pendingVariable ?? selection;
    if (!richEditorAvailable) {
      setNotice('The rich editor is unavailable; variable creation needs the rich editor.');
      return;
    }
    if (!target) {
      setNotice('Select a non-empty single paragraph/heading first.');
      return;
    }
    setDefinition(suggestDefinition(target.selectedText));
    setDialogOpen(true);
  };

  const confirmVariable = () => {
    const target = pendingVariable ?? selection;
    if (!target) {
      setNotice('Select a non-empty single paragraph/heading first.');
      return;
    }
    try {
      const next = replaceSelectionWithVariable(document, target, definition);
      const created = collectVariables(next).find(
        (variable) => variable.label === (definition.label.trim() || 'variable'),
      );
      onChange(next);
      setDialogOpen(false);
      onVariableHandled();
      if (created) {
        setKnownVariables((current) => [
          ...current,
          { variableId: created.variableId, label: created.label, required: created.required },
        ]);
      }
      setSelectedVariableId(created?.variableId ?? null);
      setArea('sandbox');
      setSandboxArea('variables');
      setNotice(`Marked "${definition.label || 'variable'}" as a variable.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  };

  const fillVariable = () => {
    if (!selectedVariable || !richEditorAvailable) return;
    onChange(setVariableValue(document, selectedVariable.variableId, fillValue));
    setNotice(
      `Filled ${selectedVariable.occurrences.length} occurrence(s) of ${selectedVariable.label}; same-named ordinary text was not changed.`,
    );
  };

  const runMapping = () => {
    if (!mappingTemplate) return;
    setCandidates(matchDocument(document, mappingTemplate));
    setDecisions({});
    setNotice('Matched the mock downstream template; the payload has not been sent.');
  };

  const selectMappingTemplate = (id: string) => {
    setMappingTemplateId(id);
    setCandidates([]);
    setDecisions({});
  };

  const setDecision = (fieldId: string, value: string) => {
    setDecisions((current) => ({ ...current, [fieldId]: value }));
  };

  const refreshSystems = () => {
    setSystems(downstreamStore.list());
    setSystemIssue(downstreamStore.issue());
  };

  const startNewSystem = () => {
    setSystemDraft({
      name: '',
      baseUrl: '',
      environment: 'sandbox',
      enabled: true,
      auth: { type: 'bearer' },
      specText: '',
    });
    setSystemError(null);
    setDeletingSystemId(null);
    setSystemsOpen(true);
  };

  const startEditSystem = (system: DownstreamSystem) => {
    setSystemDraft({
      id: system.id,
      name: system.name,
      baseUrl: system.baseUrl,
      environment: system.environment,
      enabled: system.enabled,
      auth: { ...system.auth },
      specText: system.specText,
    });
    setSystemError(null);
    setDeletingSystemId(null);
    setSystemsOpen(true);
  };

  const cancelSystemForm = () => {
    setSystemDraft(null);
    setSystemError(null);
  };

  const saveSystem = async () => {
    if (!systemDraft) return;
    if (systemDraft.specText.trim()) {
      const parsed = await parseContract(systemDraft.specText);
      if (!parsed.ok) {
        setSystemError(parsed.error);
        return;
      }
    }
    const input: DownstreamSystemInput = {
      name: systemDraft.name,
      baseUrl: systemDraft.baseUrl,
      environment: systemDraft.environment,
      enabled: systemDraft.enabled,
      auth: systemDraft.auth,
      specText: systemDraft.specText,
    };
    const result = systemDraft.id
      ? downstreamStore.update(systemDraft.id, input)
      : downstreamStore.create(input);
    if (!result.ok) {
      setSystemError(systemFailureMessage(result.reason));
      return;
    }
    refreshSystems();
    setSelectedSystemId(result.record.id);
    setSystemDraft(null);
    setSystemError(null);
    setNotice(
      result.persisted
        ? `Saved "${result.record.name}" in this browser.`
        : `"${result.record.name}" is session only — browser storage failed.`,
    );
  };

  const confirmDeleteSystem = (system: DownstreamSystem) => {
    const removed = downstreamStore.remove(system.id);
    refreshSystems();
    if (selectedSystemId === system.id) {
      setSelectedSystemId(null);
      setOpenApiOperationId(null);
      setOpenApiMappings({});
    }
    setDeletingSystemId(null);
    setNotice(
      removed ? `Deleted "${system.name}" from this browser.` : 'That system no longer exists.',
    );
  };

  const selectOpenApiOperation = (id: string) => {
    const operation = openApiContract?.operations.find((item) => item.id === id) ?? null;
    setOpenApiOperationId(operation?.id ?? null);
    setOpenApiMappings(operation ? suggestMappings(operation.fields, mappingVariables) : {});
  };

  const downloadOpenApiPayload = () => {
    if (!openApiOperation || !openApiPayload?.ready) return;
    const filename = downloadJson(openApiOperation, openApiPayload.payload);
    setNotice(`Downloaded ${filename} — not sent to the downstream API.`);
  };

  const payload = mappingTemplate
    ? buildPayload(mappingTemplate, decisions, {
        templateVersion: mappingTemplate.version,
        documentDigest: digest || 'digest-unavailable',
      })
    : null;

  const mappingVariables = useMemo(
    () =>
      variables.map((variable) => ({
        variableId: variable.variableId,
        label: variable.label,
        displayValue: variable.displayValue,
      })),
    [variables],
  );
  const selectedSystem = systems.find((system) => system.id === selectedSystemId) ?? null;
  // Parsing runs on the server (`/automation/spec/parse`): the registry and this preview share one
  // implementation of the OpenAPI subset.
  const [systemContract, setSystemContract] = useState<OpenApiContract | null>(null);
  const [systemSpecError, setSystemSpecError] = useState<string | null>(null);
  useEffect(() => {
    const specText = selectedSystem?.specText ?? '';
    if (!specText.trim()) {
      setSystemContract(null);
      setSystemSpecError(
        selectedSystem ? 'No OpenAPI spec attached. Edit the system to add one.' : null,
      );
      return;
    }
    let cancelled = false;
    void parseContract(specText).then((parsed) => {
      if (cancelled) return;
      if (parsed.ok) {
        setSystemContract(parsed.contract);
        setSystemSpecError(null);
      } else {
        setSystemContract(null);
        setSystemSpecError(parsed.error);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedSystem?.id, selectedSystem?.specText]);
  const openApiContract = systemContract;
  const openApiError = systemSpecError;
  const openApiOperation =
    openApiContract?.operations.find((operation) => operation.id === openApiOperationId) ?? null;
  const [openApiPayload, setOpenApiPayload] = useState<OpenApiPayload | null>(null);
  useEffect(() => {
    if (!selectedSystem || !openApiOperation) {
      setOpenApiPayload(null);
      return;
    }
    let document: Record<string, unknown>;
    try {
      document = JSON.parse(selectedSystem.specText) as Record<string, unknown>;
    } catch {
      setOpenApiPayload(null);
      return;
    }
    let cancelled = false;
    void buildContractPayload(document, openApiOperation, openApiMappings, mappingVariables)
      .then((result) => {
        if (!cancelled) setOpenApiPayload(result);
      })
      .catch(() => {
        if (!cancelled) setOpenApiPayload(null);
      });
    return () => {
      cancelled = true;
    };
    // Depend on stable identities only: a fresh array each render would loop the effect.
  }, [selectedSystem?.id, selectedSystem?.specText, openApiOperationId, openApiMappings, mappingVariables]);

  useEffect(() => {
    if (selectedSystemId && systems.some((system) => system.id === selectedSystemId)) return;
    const initial =
      systems.find((system) => system.enabled && system.specText.trim()) ?? systems[0] ?? null;
    setSelectedSystemId(initial?.id ?? null);
  }, [systems, selectedSystemId]);

  useEffect(() => {
    const system = systems.find((item) => item.id === selectedSystemId) ?? null;
    if (!system || !system.specText.trim()) {
      setOpenApiOperationId(null);
      setOpenApiMappings({});
      return;
    }
    let cancelled = false;
    void parseContract(system.specText).then((parsed) => {
      if (cancelled) return;
      const first = parsed.ok
        ? parsed.contract.operations.find((operation) => operation.available) ?? null
        : null;
      setOpenApiOperationId(first?.id ?? null);
      setOpenApiMappings(first ? suggestMappings(first.fields, mappingVariables) : {});
    });
    // `mappingVariables` is intentionally read at selection time; depending on it would reset
    // mappings whenever a variable value changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => {
      cancelled = true;
    };
  }, [selectedSystemId, systems]);

  const confirmedRequired =
    mappingTemplate?.fields.filter(
      (field) => field.required && Boolean(decisions[field.fieldId]?.trim()),
    ).length ?? 0;
  const requiredCount = mappingTemplate?.fields.filter((field) => field.required).length ?? 0;

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (
      event.key !== 'ArrowRight' &&
      event.key !== 'ArrowLeft' &&
      event.key !== 'Home' &&
      event.key !== 'End'
    ) {
      return;
    }
    event.preventDefault();
    const last = AREAS.length - 1;
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? last
          : event.key === 'ArrowRight'
            ? (index + 1) % AREAS.length
            : (index - 1 + AREAS.length) % AREAS.length;
    setArea(AREAS[next][0]);
    tabRefs.current[next]?.focus();
  };

  return (
    <section className="automation-workbench" aria-label="Automation workbench">
      <div className="row">
        <h2>Automation</h2>
        <span className="muted tiny">server registry + local sandbox</span>
      </div>
      <p className="notice tiny" data-testid="automation-boundary">
        <strong>Automate</strong> is the real path: templates and confirmed variables persist on the
        server, Doubao suggests variables, the request body follows the downstream contract, and
        dispatch makes one allow-listed HTTP call with a replayable receipt. <strong>Sandbox</strong>{' '}
        is a browser-local playground (localStorage, no network). Still not implemented: compare,
        rewrite and voice.
      </p>
      {!draft ? (
        <p className="muted tiny" data-testid="no-draft">
          No server draft — workbench actions are disabled.
        </p>
      ) : null}
      <p className="muted tiny" data-testid="workbench-context">
        Draft rev {draft?.revision ?? '—'} ·{' '}
        {digest ? `document ${digest.slice(0, 12)}` : 'digest pending'} · {variables.length}{' '}
        variable(s) · {templates.length} captured template(s) in this session
      </p>
      {notice ? (
        <p className="tiny" role="status" aria-live="polite" data-testid="workbench-status">
          {notice}
        </p>
      ) : null}

      <div
        className="assistant-tabs"
        role="tablist"
        aria-label="Automation areas"
        aria-orientation="horizontal"
      >
        {AREAS.map(([id, label], index) => (
          <button
            key={id}
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            id={`automation-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={area === id}
            aria-controls={`automation-panel-${id}`}
            tabIndex={area === id ? 0 : -1}
            onClick={() => setArea(id)}
            onKeyDown={(event) => onTabKeyDown(event, index)}
          >
            {label}
          </button>
        ))}
      </div>

      {area === 'sandbox' ? (
        <div className="sandbox-bar" data-testid="sandbox-bar">
          <p className="notice tiny">
            <strong>Sandbox — nothing leaves this browser.</strong> Templates live in{' '}
            <code>localStorage</code>, the preview is built locally, and there is no send here. Use{' '}
            <strong>Automate</strong> to persist templates, call the downstream and keep receipts.
          </p>
          <div className="row" role="tablist" aria-label="Sandbox areas">
            {SANDBOX_AREAS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={sandboxArea === id}
                onClick={() => setSandboxArea(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {area === 'sandbox' && sandboxArea === 'template' ? (
        <div
          role="tabpanel"
          id="automation-panel-template"
          aria-labelledby="automation-tab-template"
        >
          <p className="muted tiny">
            Capture the current imported or edited document as a template. Inspect it, rename it or
            delete it here; the content stays a snapshot even after the editor changes.
          </p>
          <p className="tiny" data-testid="template-boundary">
            <strong>Saved in this browser — not on the server.</strong> Up to {MAX_TEMPLATES}{' '}
            templates · oldest removed first.
          </p>
          {templateIssue === 'unreadable' ? (
            <p className="notice notice--warn tiny" data-testid="template-storage-issue">
              Stored templates could not be read; new captures will still work in this session.
            </p>
          ) : null}
          {templateIssue === 'unavailable' ? (
            <p className="notice notice--warn tiny" data-testid="template-storage-issue">
              Browser storage is unavailable. Captures stay in this session and are lost on reload.
            </p>
          ) : null}

          <div className="template-capture" data-testid="template-capture">
            <label className="tiny">
              Template name
              <input
                aria-label="Template name"
                value={templateName}
                maxLength={80}
                onChange={(event) => setTemplateName(event.target.value)}
              />
            </label>
            <dl className="tiny" data-testid="capture-preview">
              <div>
                <dt>Source</dt>
                <dd>
                  {capturePreview.sourceLabel}
                  {capturePreview.provenanceNote
                    ? ` · ${capturePreview.provenanceNote}`
                    : ''}
                </dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>{capturePreview.revisionLabel}</dd>
              </div>
              <div>
                <dt>Content</dt>
                <dd>
                  {capturePreview.charCount} characters · {capturePreview.variables.length}{' '}
                  variable(s)
                </dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{capturePreview.nextVersion}</dd>
              </div>
              {capturePreview.variables.length ? (
                <div>
                  <dt>Variables</dt>
                  <dd>
                    {capturePreview.variables
                      .map(
                        (variable) =>
                          `${variable.label} (${variable.valueType}${
                            variable.required ? ', required' : ''
                          })`,
                      )
                      .join(', ')}
                  </dd>
                </div>
              ) : null}
            </dl>
            {capturePreview.duplicate ? (
              <p className="notice tiny" data-testid="duplicate-warning">
                <strong>“{capturePreview.duplicate.name}” already exists.</strong> Saving adds{' '}
                {capturePreview.nextVersion}; the existing template is not overwritten.
              </p>
            ) : null}
            {capturePreview.nameError ? (
              <p className="tiny" data-testid="template-name-error">
                {capturePreview.nameError}
              </p>
            ) : null}
            {capturePreview.empty ? (
              <p className="muted tiny" data-testid="template-empty-document">
                A template needs document content. Import or type something first.
              </p>
            ) : null}
            <button type="button" onClick={captureTemplate} disabled={!capturePreview.canCapture}>
              Save as template
            </button>
          </div>
          <ul
            className="template-list"
            data-testid="template-list"
            aria-label="Captured templates"
            ref={templateListRef}
            tabIndex={-1}
          >
            {templates.length === 0 ? (
              <li className="muted" data-testid="template-empty">
                No templates yet. Capturing the current document adds one here.
              </li>
            ) : null}
            {templates.map((template) => (
              <li key={template.id}>
                <button
                  type="button"
                  data-testid="template-item"
                  aria-pressed={selectedTemplateId === template.id}
                  aria-label={`${template.name} · ${template.version}`}
                  onClick={() => {
                    setSelectedTemplateId(template.id);
                    setDeletingTemplateId(null);
                    setApplyingTemplateId(null);
                  }}
                >
                  <strong>{template.name}</strong> <span>{template.version}</span>
                  <span className="muted tiny">
                    {' '}
                    · {recordSourceLabel(template)} · {template.charCount} characters ·{' '}
                    {template.variables.length} variable(s) · {formatCapturedAt(template.capturedAt)}
                  </span>
                  {!template.persisted ? (
                    <span className="tiny"> · Session only — browser storage failed</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
          {selectedTemplate ? (
            <div className="notice tiny" data-testid="template-detail">
              <div className="row">
                <h3>{selectedTemplate.name}</h3>
                <span className="muted tiny">{selectedTemplate.version}</span>
              </div>
              <p className="muted tiny">
                {recordSourceLabel(selectedTemplate)} · captured{' '}
                {formatCapturedAt(selectedTemplate.capturedAt)} · {selectedTemplate.charCount}{' '}
                characters ·{' '}
                {selectedTemplate.boundRevision === null
                  ? 'Captured without a server draft'
                  : `Captured at revision ${selectedTemplate.boundRevision}`}
              </p>
              {selectedTemplate.variables.length ? (
                <p className="tiny">
                  Variables:{' '}
                  {selectedTemplate.variables
                    .map(
                      (variable) =>
                        `${variable.label} (${variable.valueType}${
                          variable.required ? ', required' : ''
                        })`,
                    )
                    .join(', ')}
                </p>
              ) : null}
              <div
                className="version-actions"
                onKeyDown={(event) => {
                  if (event.key !== 'Escape') return;
                  if (renamingTemplate) {
                    event.preventDefault();
                    cancelRenameTemplate();
                  } else if (deletingTemplateId === selectedTemplate.id) {
                    event.preventDefault();
                    setDeletingTemplateId(null);
                  } else if (applyingTemplateId === selectedTemplate.id) {
                    event.preventDefault();
                    setApplyingTemplateId(null);
                  }
                }}
              >
                {onApplyTemplate ? (
                  applyingTemplateId === selectedTemplate.id ? (
                    <div className="version-actions">
                      <p className="tiny" role="status" aria-live="polite">
                        Replace the current document with “{selectedTemplate.name}” (
                        {selectedTemplate.version})? The current content will be replaced.
                      </p>
                      <button
                        type="button"
                        autoFocus
                        onClick={() => applySelectedTemplate(selectedTemplate)}
                      >
                        Replace document
                      </button>
                      <button type="button" onClick={() => setApplyingTemplateId(null)}>
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      disabled={!richEditorAvailable}
                      title={
                        richEditorAvailable
                          ? 'Apply this template to the editor'
                          : 'Applying a rich template needs the rich editor'
                      }
                      onClick={() => {
                        if (hasContent) {
                          setApplyingTemplateId(selectedTemplate.id);
                        } else {
                          applySelectedTemplate(selectedTemplate);
                        }
                      }}
                    >
                      Apply to editor
                    </button>
                  )
                ) : null}
                {!richEditorAvailable ? (
                  <p className="muted tiny" data-testid="apply-fallback">
                    Applying a rich template needs the rich editor.
                  </p>
                ) : null}
                {renamingTemplate?.id === selectedTemplate.id ? (
                  <div className="version-actions">
                    <label className="tiny">
                      Rename template
                      <input
                        aria-label="Rename template"
                        value={renamingTemplate.name}
                        maxLength={80}
                        autoFocus
                        onChange={(event) =>
                          setRenamingTemplate({ ...renamingTemplate, name: event.target.value })
                        }
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault();
                            submitRenameTemplate();
                          }
                        }}
                      />
                    </label>
                    <button type="button" onClick={submitRenameTemplate}>
                      Save name
                    </button>
                    <button type="button" onClick={cancelRenameTemplate}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button type="button" onClick={() => startRenameTemplate(selectedTemplate)}>
                    Rename
                  </button>
                )}
                {deletingTemplateId === selectedTemplate.id ? (
                  <div className="version-actions">
                    <p className="tiny" role="status" aria-live="polite">
                      Delete “{selectedTemplate.name}” from this browser?
                    </p>
                    <button type="button" autoFocus onClick={() => confirmDeleteTemplate(selectedTemplate)}>
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setDeletingTemplateId(null)}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button type="button" onClick={() => setDeletingTemplateId(selectedTemplate.id)}>
                    Delete
                  </button>
                )}
              </div>
              <p className="tiny">
                <strong>Captured content</strong>
              </p>
              <p className="tiny" data-testid="template-excerpt">
                {selectedTemplateExcerpt}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
      {area === 'sandbox' && sandboxArea === 'variables' ? (
        <div
          role="tabpanel"
          id="automation-panel-variables"
          aria-labelledby="automation-tab-variables"
        >
          <p className="muted tiny">
            Select text in the editor, then use right-click or the button below. Occurrences are
            updated together; same-named ordinary text is not changed.
          </p>
          {!richEditorAvailable ? (
            <p className="notice notice--warn tiny" data-testid="fallback-variables">
              The rich editor is unavailable, so variable creation and fill are disabled. Variable
              placeholders appear as <code>{'{{label}}'}</code> in the textarea.
            </p>
          ) : null}
          <button
            type="button"
            onClick={openVariableDialog}
            disabled={!canMarkVariable}
            title={
              richEditorAvailable
                ? selection
                  ? 'Mark the selected text as a variable'
                  : 'Select text in one paragraph/heading first'
                : 'Variable editing needs the rich editor'
            }
          >
            Mark selection as variable
          </button>
          {richEditorAvailable && !selection ? (
            <p className="muted tiny" data-testid="selection-hint">
              Mark as variable needs a non-empty selection inside one paragraph or heading.
            </p>
          ) : null}
          {missingRequired.length ? (
            <p className="notice notice--warn tiny" data-testid="missing-required">
              Required variable(s) deleted from the document:{' '}
              {missingRequired.map((known) => known.label).join(', ')}. They are reported as
              missing, not silently dropped.
            </p>
          ) : null}
          <div
            className="template-save"
            data-testid="save-to-template"
            onKeyDown={(event) => {
              if (event.key === 'Escape' && updatingTemplateId) {
                event.preventDefault();
                setUpdatingTemplateId(null);
              }
            }}
          >
            <label className="tiny">
              Save document to template
              <select
                aria-label="Template to update"
                value={saveTargetTemplate?.id ?? ''}
                disabled={!templates.length || !hasContent}
                onChange={(event) => setSaveTemplateId(event.target.value)}
              >
                {templates.length === 0 ? (
                  <option value="">No templates yet</option>
                ) : (
                  templates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name} · {template.version}
                    </option>
                  ))
                )}
              </select>
            </label>
            {updatingTemplateId && saveTargetTemplate ? (
              <div className="version-actions">
                <p className="tiny" role="status" aria-live="polite">
                  Update “{saveTargetTemplate.name}” from {saveTargetTemplate.version} to{' '}
                  {templateStore.nextVersion()}? The previous snapshot will be replaced.
                </p>
                <button
                  type="button"
                  autoFocus
                  onClick={() => updateTemplateFromDocument(saveTargetTemplate)}
                >
                  Update template
                </button>
                <button type="button" onClick={() => setUpdatingTemplateId(null)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                disabled={!saveTargetTemplate || !hasContent}
                onClick={() => {
                  if (saveTargetTemplate) setUpdatingTemplateId(saveTargetTemplate.id);
                }}
              >
                Save to template
              </button>
            )}
            {templates.length === 0 ? (
              <p className="muted tiny">No template yet — capture one in Template first.</p>
            ) : null}
            {!hasContent ? (
              <p className="muted tiny">A template needs document content.</p>
            ) : null}
          </div>
          <ul className="tiny" data-testid="variable-list">
            {variables.length === 0 ? (
              <li>No variables yet. Mark a selection to create one.</li>
            ) : null}
            {variables.map((variable) => (
              <li key={variable.variableId}>
                <button
                  type="button"
                  aria-pressed={selectedVariableId === variable.variableId}
                  onClick={() => {
                    setSelectedVariableId(variable.variableId);
                    setFillValue(variable.displayValue ?? '');
                  }}
                >
                  {variable.label} · {variable.valueType}
                  {variable.required ? ' · required' : ' · optional'} ·{' '}
                  {variable.occurrences.length} occurrence(s)
                </button>
              </li>
            ))}
          </ul>
          {selectedVariable ? (
            <div className="notice tiny" data-testid="variable-detail">
              <p>
                Current: {selectedVariable.displayValue ?? `{{${selectedVariable.label}}}`} · type{' '}
                {selectedVariable.valueType} · {selectedVariable.required ? 'required' : 'optional'}
              </p>
              <ul data-testid="occurrence-list">
                {selectedVariable.occurrences.map((occurrence) => (
                  <li key={occurrence.occurrenceId}>
                    {occurrence.nodeId} · {occurrence.start}–{occurrence.end} ·{' '}
                    {variableDisplay({
                      type: 'variableReference',
                      attrs: {
                        variableId: selectedVariable.variableId,
                        label: selectedVariable.label,
                        valueType: selectedVariable.valueType,
                        required: selectedVariable.required,
                        displayValue: selectedVariable.displayValue,
                        occurrenceId: occurrence.occurrenceId,
                      },
                    })}{' '}
                    → {fillValue.trim() || '{{empty}}'}
                  </li>
                ))}
              </ul>
              <label className="tiny">
                New value
                <input
                  aria-label="Variable value"
                  value={fillValue}
                  onChange={(event) => setFillValue(event.target.value)}
                  disabled={!richEditorAvailable}
                />
              </label>
              <button type="button" onClick={fillVariable} disabled={!richEditorAvailable}>
                Fill all occurrences
              </button>
              <p className="tiny">
                Preview: {selectedVariable.occurrences.length} occurrence(s) will change from{' '}
                {selectedVariable.displayValue ?? `{{${selectedVariable.label}}}`} to{' '}
                {fillValue.trim() || '{{empty}}'}. Nothing is saved to the server.
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      {area === 'sandbox' && sandboxArea === 'mapping' ? (
        <div
          role="tabpanel"
          id="automation-panel-mapping"
          aria-labelledby="automation-tab-mapping"
        >
          <label className="tiny">
            Downstream source
            <select
              aria-label="Downstream source"
              value={mappingSource}
              onChange={(event) => setMappingSource(event.target.value as MappingSource)}
            >
              <option value="fixture">Synthetic fixture</option>
              <option value="openapi">OpenAPI JSON</option>
            </select>
          </label>
          {mappingSource === 'fixture' ? (
            <div data-testid="fixture-mapping">
              <p className="muted tiny">
                Choose a mock downstream API template. Matching is deterministic; nothing is sent
                to an external system.
              </p>
          <label className="tiny">
            Downstream template
            <select
              aria-label="Downstream template"
              value={mappingTemplateId}
              onChange={(event) => selectMappingTemplate(event.target.value)}
            >
              {downstreamTemplates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name} · {template.version}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={runMapping} disabled={!draft || !mappingTemplate}>
            Match document
          </button>
          {mappingTemplate ? (
            <p className="tiny" data-testid="mapping-coverage">
              Coverage: {confirmedRequired}/{requiredCount} required field(s) confirmed ·{' '}
              {candidates.length
                ? `${candidates.filter((item) => item.status === 'missing').length} missing · ${
                    candidates.filter((item) => item.status === 'ambiguous').length
                  } ambiguous`
                : 'not matched yet'}
            </p>
          ) : (
            <p className="muted tiny">No mock downstream templates available.</p>
          )}
          <ul className="tiny" data-testid="mapping-fields">
            {mappingTemplate?.fields.map((field) => {
              const candidate = candidates.find((item) => item.fieldId === field.fieldId);
              const status = candidate?.status ?? 'unmapped';
              const decision = decisions[field.fieldId] ?? '';
              const confirmed = candidate?.value != null && decision === candidate.value;
              return (
                <li key={field.fieldId}>
                  <strong>{field.label}</strong> · {field.required ? 'required' : 'optional'} ·
                  status: {status}
                  {field.type === 'enum' && field.options
                    ? ` · options ${field.options.join(' / ')}`
                    : ''}
                  {candidate?.evidence ? <div>evidence: {candidate.evidence}</div> : null}
                  <div>{candidate?.reason ?? 'Not matched yet.'}</div>
                  {candidate?.status === 'matched' && candidate.value ? (
                    <button
                      type="button"
                      onClick={() => setDecision(field.fieldId, candidate.value ?? '')}
                    >
                      {confirmed ? `Confirmed ${candidate.value}` : `Confirm ${candidate.value}`}
                    </button>
                  ) : null}
                  {field.type === 'enum' && field.options && candidate ? (
                    <label className="tiny">
                      {field.label} value
                      <select
                        aria-label={`${field.label} value`}
                        value={decision}
                        onChange={(event) => setDecision(field.fieldId, event.target.value)}
                      >
                        <option value="">Unresolved</option>
                        {field.options.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  {field.required && !decision ? (
                    <div className="muted">Not confirmed — stays out of the payload.</div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {payload ? (
            <div className="notice tiny" data-testid="payload-preview" data-state={payload.state}>
              <div>
                Payload preview ·{' '}
                {payload.state === 'ready'
                  ? 'ready'
                  : `mapping_not_ready (missing ${payload.missing.join(', ')})`}{' '}
                · <strong>Not sent</strong>
              </div>
              <div className="muted tiny">
                Bound to mock template {payload.templateVersion} · document digest{' '}
                {payload.documentDigest.slice(0, 12)}
              </div>
              <pre>{JSON.stringify(payload.payload, null, 2)}</pre>
            </div>
          ) : null}
            </div>
          ) : (
            <div data-testid="openapi-mapping">
              <p className="muted tiny">
                OpenAPI 3.x JSON is parsed locally from the selected system. YAML, Swagger 2.0,
                external refs and oneOf/anyOf are not supported.
              </p>
              <label className="tiny">
                Downstream system
                <select
                  aria-label="Downstream system"
                  value={selectedSystemId ?? ''}
                  onChange={(event) => setSelectedSystemId(event.target.value || null)}
                >
                  <option value="">Choose a system</option>
                  {systems.map((system) => (
                    <option key={system.id} value={system.id}>
                      {system.name} · {system.environment}
                      {system.enabled ? '' : ' · disabled'}
                    </option>
                  ))}
                </select>
              </label>
              <div className="version-actions">
                <button type="button" onClick={() => setSystemsOpen((open) => !open)}>
                  {systemsOpen ? 'Hide systems' : 'Manage systems'}
                </button>
                <span className="muted tiny">Saved in this browser — not on the server.</span>
              </div>
              {systemIssue ? (
                <p className="notice notice--warn tiny" data-testid="system-issue">
                  {systemIssue === 'unreadable'
                    ? 'Stored downstream systems could not be read; only valid entries are shown.'
                    : 'Browser storage is unavailable; system changes stay in this session only.'}
                </p>
              ) : null}
              {selectedSystem ? (
                <p className="tiny" data-testid="system-detail">
                  {selectedSystem.baseUrl} · {selectedSystem.environment} ·{' '}
                  {selectedSystem.enabled ? 'enabled' : 'disabled'} · auth{' '}
                  {selectedSystem.auth.type}
                  {selectedSystem.auth.hint ? ` (${selectedSystem.auth.hint})` : ''} · spec updated{' '}
                  {formatCapturedAt(selectedSystem.specUpdatedAt)}
                </p>
              ) : (
                <p className="muted tiny" data-testid="no-system">
                  No downstream system selected; create or select one first.
                </p>
              )}
              {systemsOpen ? (
                <div
                  className="notice tiny"
                  data-testid="system-manager"
                  onKeyDown={(event) => {
                    if (event.key !== 'Escape') return;
                    if (systemDraft) {
                      event.preventDefault();
                      cancelSystemForm();
                    } else if (deletingSystemId) {
                      event.preventDefault();
                      setDeletingSystemId(null);
                    }
                  }}
                >
                  <h3>Downstream systems</h3>
                  <ul className="tiny" data-testid="system-list">
                    {systems.length === 0 ? <li>No systems yet.</li> : null}
                    {systems.map((system) => (
                      <li key={system.id}>
                        <strong>{system.name}</strong> · {system.environment} ·{' '}
                        {system.enabled ? 'enabled' : 'disabled'} · {system.baseUrl}
                        <button type="button" onClick={() => startEditSystem(system)}>
                          Edit
                        </button>
                        {deletingSystemId === system.id ? (
                          <>
                            <span role="status" aria-live="polite">
                              Delete “{system.name}” from this browser?
                            </span>
                            <button type="button" onClick={() => confirmDeleteSystem(system)}>
                              Confirm delete
                            </button>
                            <button type="button" onClick={() => setDeletingSystemId(null)}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button type="button" onClick={() => setDeletingSystemId(system.id)}>
                            Delete
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                  <button type="button" onClick={startNewSystem}>
                    New system
                  </button>
                  {systemDraft ? (
                    <div data-testid="system-form">
                      <label className="tiny">
                        Name
                        <input
                          aria-label="System name"
                          value={systemDraft.name}
                          onChange={(event) =>
                            setSystemDraft({ ...systemDraft, name: event.target.value })
                          }
                        />
                      </label>
                      <label className="tiny">
                        Base URL
                        <input
                          aria-label="Base URL"
                          value={systemDraft.baseUrl}
                          onChange={(event) =>
                            setSystemDraft({ ...systemDraft, baseUrl: event.target.value })
                          }
                        />
                      </label>
                      <label className="tiny">
                        Environment
                        <select
                          aria-label="Environment"
                          value={systemDraft.environment}
                          onChange={(event) =>
                            setSystemDraft({
                              ...systemDraft,
                              environment: event.target.value as DownstreamSystem['environment'],
                            })
                          }
                        >
                          <option value="sandbox">sandbox</option>
                          <option value="production">production</option>
                        </select>
                      </label>
                      <label className="tiny">
                        <input
                          type="checkbox"
                          aria-label="Enabled"
                          checked={systemDraft.enabled}
                          onChange={(event) =>
                            setSystemDraft({ ...systemDraft, enabled: event.target.checked })
                          }
                        />{' '}
                        Enabled
                      </label>
                      <label className="tiny">
                        Auth type
                        <select
                          aria-label="Auth type"
                          value={systemDraft.auth.type}
                          onChange={(event) =>
                            setSystemDraft({
                              ...systemDraft,
                              auth: {
                                ...systemDraft.auth,
                                type: event.target.value as DownstreamSystem['auth']['type'],
                              },
                            })
                          }
                        >
                          <option value="none">none</option>
                          <option value="api_key">api_key</option>
                          <option value="bearer">bearer</option>
                        </select>
                      </label>
                      <label className="tiny">
                        Auth hint (no secret)
                        <input
                          aria-label="Auth hint"
                          maxLength={80}
                          value={systemDraft.auth.hint ?? ''}
                          onChange={(event) =>
                            setSystemDraft({
                              ...systemDraft,
                              auth: { ...systemDraft.auth, hint: event.target.value },
                            })
                          }
                        />
                      </label>
                      <label className="tiny">
                        System OpenAPI file
                        <input
                          type="file"
                          accept=".json,application/json"
                          aria-label="System OpenAPI file"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (!file) return;
                            void file.text().then((text) =>
                              setSystemDraft((current) =>
                                current ? { ...current, specText: text } : current,
                              ),
                            );
                          }}
                        />
                      </label>
                      <label className="tiny">
                        System OpenAPI JSON
                        <textarea
                          aria-label="System OpenAPI JSON"
                          rows={6}
                          value={systemDraft.specText}
                          onChange={(event) =>
                            setSystemDraft({ ...systemDraft, specText: event.target.value })
                          }
                        />
                      </label>
                      {systemError ? (
                        <p className="notice notice--bad tiny" role="alert" data-testid="system-error">
                          {systemError}
                        </p>
                      ) : null}
                      <div className="version-actions">
                        <button type="button" onClick={() => void saveSystem()}>
                          Save system
                        </button>
                        <button type="button" onClick={cancelSystemForm}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
              {openApiError ? (
                <p className="notice notice--bad tiny" role="alert" data-testid="openapi-error">
                  {openApiError}
                </p>
              ) : null}
              {openApiContract ? (
                <p className="tiny" data-testid="openapi-title">
                  {openApiContract.title} · {openApiContract.version} ·{' '}
                  {openApiContract.operations.length} operation(s)
                </p>
              ) : null}
              {openApiContract ? (
                <label className="tiny">
                  Operation
                  <select
                    aria-label="OpenAPI operation"
                    value={openApiOperationId ?? ''}
                    onChange={(event) => selectOpenApiOperation(event.target.value)}
                  >
                    <option value="">Choose an operation</option>
                    {openApiContract.operations.map((operation) => (
                      <option key={operation.id} value={operation.id} disabled={!operation.available}>
                        {operation.method} {operation.path}
                        {operation.operationId ? ` · ${operation.operationId}` : ''}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {openApiOperation ? (
                <>
                  <p className="tiny" data-testid="openapi-operation">
                    {openApiOperation.method} {openApiOperation.path}
                    {openApiOperation.operationId ? ` · ${openApiOperation.operationId}` : ''}
                  </p>
                  <ul className="tiny" data-testid="openapi-fields">
                    {openApiOperation.fields.map((field) => {
                      const mapping = openApiMappings[field.path] ?? '';
                      const issue = openApiPayload?.issues.find((item) => item.path === field.path);
                      return (
                        <li key={field.path}>
                          <strong>{field.path}</strong> · {field.type} ·{' '}
                          {field.required ? 'required' : 'optional'}
                          {field.enumValues ? ` · enum ${field.enumValues.join(' / ')}` : ''}
                          {field.unsupported ? (
                            <div className="muted">{field.unsupported}</div>
                          ) : (
                            <label className="tiny">
                              Variable
                              <select
                                aria-label={`Map ${field.path}`}
                                value={mapping}
                                onChange={(event) =>
                                  setOpenApiMappings((current) => ({
                                    ...current,
                                    [field.path]: event.target.value,
                                  }))
                                }
                              >
                                <option value="">Not mapped</option>
                                {variables.map((variable) => (
                                  <option key={variable.variableId} value={variable.variableId}>
                                    {variable.label} ({variable.valueType})
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                          {issue ? (
                            <div className="notice notice--warn tiny">{issue.message}</div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                  {openApiOperation.warnings.length ? (
                    <ul className="tiny muted" data-testid="openapi-warnings">
                      {openApiOperation.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  ) : null}
                  {openApiPayload ? (
                    <div
                      className="notice tiny"
                      data-testid="openapi-payload"
                      data-state={openApiPayload.ready ? 'ready' : 'not_ready'}
                    >
                      <div>
                        OpenAPI request preview ·{' '}
                        {openApiPayload.ready
                          ? 'ready'
                          : `not_ready${
                              openApiPayload.missing.length
                                ? ` (missing ${openApiPayload.missing.join(', ')})`
                                : ''
                            }`}{' '}
                        · <strong>Not sent</strong>
                      </div>
                      <pre>{JSON.stringify(openApiPayload.payload, null, 2)}</pre>
                      {openApiPayload.issues.length ? (
                        <ul className="tiny">
                          {openApiPayload.issues.map((issue) => (
                            <li key={`${issue.path}:${issue.reason}`}>
                              {issue.path}: {issue.message}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <button
                        type="button"
                        disabled={!openApiPayload.ready}
                        onClick={downloadOpenApiPayload}
                      >
                        Download JSON
                      </button>
                    </div>
                  ) : null}
                  <p className="muted tiny" data-testid="send-unavailable">
                    Sandbox previews only — use <strong>Automate</strong> to dispatch for real
                    (allow-listed host, receipt recorded).
                  </p>
                </>
              ) : null}
            </div>
          )}
        </div>
      ) : null}

      {area === 'server' ? (
        <div role="tabpanel" id="automation-panel-server" aria-labelledby="automation-tab-server">
          <AutomationServerPanel
            documentId={draft?.document_id ?? null}
            text={richToPlainText(document)}
          />
        </div>
      ) : null}

      {dialogOpen ? (
        <div
          className="notice"
          role="dialog"
          aria-modal="true"
          aria-label="Variable definition"
          data-testid="variable-dialog"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              closeDialog();
            }
          }}
        >
          <h3>Mark selection as variable</h3>
          <p className="muted tiny">
            The selected text becomes the initial value. Clear it later to show the{' '}
            <code>{'{{label}}'}</code> placeholder.
          </p>
          <label className="tiny">
            Label
            <input
              ref={labelRef}
              aria-label="Variable label"
              value={definition.label}
              onChange={(event) => setDefinition({ ...definition, label: event.target.value })}
            />
          </label>
          <label className="tiny">
            Type
            <select
              aria-label="Variable type"
              value={definition.valueType}
              onChange={(event) =>
                setDefinition({
                  ...definition,
                  valueType: event.target.value as VariableDefinition['valueType'],
                })
              }
            >
              <option value="string">string</option>
              <option value="amount">amount</option>
              <option value="date">date</option>
              <option value="currency">currency</option>
            </select>
          </label>
          <label className="tiny">
            <input
              type="checkbox"
              checked={definition.required}
              onChange={(event) => setDefinition({ ...definition, required: event.target.checked })}
            />{' '}
            Required before submit
          </label>
          <div className="version-actions">
            <button type="button" onClick={confirmVariable}>
              Create variable
            </button>
            <button type="button" onClick={closeDialog}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}