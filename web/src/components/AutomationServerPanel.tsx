/**
 * Server-side automation panel: template → variables (AI) → values → downstream dispatch.
 *
 * The workbench's other areas are browser-local snapshots; this one talks to
 * `/automation/templates*`, `/automation/connectors` and `/automation/dispatches`, so a template and
 * its confirmed variables are shared across users, and the send is a real HTTP call (allow-listed).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, explainError } from '../api/errors';
import { AiWaitBox } from './AiWaitBox';
import { useElapsedMs } from './useElapsedMs';
import { parseContract, type OpenApiContract } from '../automation/specContract';
import { suggestMappings } from '../automation/specContract';
import { automationFlow, type AutomationStepId } from '../automation/flow';
import { parseFieldLines } from '../automation/fieldSpec';
import {
  registryClient,
  type Connector,
  type DispatchPreview,
  type DispatchReceipt,
  type DocumentTemplateBinding,
  type PreparedPayload,
  type RegistryClient,
  type ServerTemplate,
  type TemplateSuggestion,
  type TemplateVariable,
} from '../api/automationRegistry';

export interface AutomationServerPanelProps {
  /** Current draft id; `null` means there is no server draft yet. */
  documentId: string | null;
  /** Current editor text, used when no server draft exists (and for previews). */
  text: string;
  /** Injected in tests. */
  client?: RegistryClient;
  onBusyChange?: (busy: boolean) => void;
}

const emptyConnector = {
  name: '',
  base_url: '',
  path: '/hooks/smart-edit',
  auth_kind: 'none' as Connector['auth_kind'],
  auth_header: 'X-Api-Key',
  secret_env: '',
};

/** `POST /trade/applications` → `{ method: 'POST', path: '/trade/applications' }`. */
const operationParts = (operationId: string): { method: string; path: string } => {
  const [method, ...rest] = operationId.split(' ');
  return { method: method ?? 'POST', path: rest.join(' ') };
};

export function AutomationServerPanel({
  documentId,
  text,
  client = registryClient,
  onBusyChange,
}: AutomationServerPanelProps) {
  const [templates, setTemplates] = useState<ServerTemplate[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [history, setHistory] = useState<DispatchReceipt[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Default the name from the draft's first line: reusing "Demand guarantee" for every draft produced
  // accidental 1.0.1 / 1.0.2 versions nobody could tell apart.
  const suggestedTemplateName = useMemo(() => {
    const first = text
      .split('\n')
      .map((line) => line.trim())
      .find((line) => line.length > 0);
    return (first ?? '').replace(/\s+/g, ' ').slice(0, 60) || 'Untitled template';
  }, [text]);
  const [name, setName] = useState(suggestedTemplateName);
  const [nameTouched, setNameTouched] = useState(false);
  useEffect(() => {
    if (!nameTouched) setName(suggestedTemplateName);
  }, [suggestedTemplateName, nameTouched]);
  const [suggestion, setSuggestion] = useState<TemplateSuggestion | null>(null);
  /** The Doubao call is its own wait state so the box only appears for the model step. */
  const [suggesting, setSuggesting] = useState(false);
  const suggestElapsed = useElapsedMs(suggesting);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [prepared, setPrepared] = useState<PreparedPayload | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [connectorForm, setConnectorForm] = useState({ ...emptyConnector });
  const [connectorId, setConnectorId] = useState<string>('');
  const [specText, setSpecText] = useState('');
  const [specContract, setSpecContract] = useState<OpenApiContract | null>(null);
  const [specOperation, setSpecOperation] = useState('');
  const [fieldsText, setFieldsText] = useState('');
  const [preview, setPreview] = useState<DispatchPreview | null>(null);
  const [editing, setEditing] = useState<{
    name: string;
    base_url: string;
    path: string;
    auth_kind: Connector['auth_kind'];
    auth_header: string;
    secret_env: string;
  } | null>(null);
  const [editSpecText, setEditSpecText] = useState('');
  const [editSpecContract, setEditSpecContract] = useState<OpenApiContract | null>(null);
  const [editOperation, setEditOperation] = useState('');
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');
  const [confirmDeleteTemplate, setConfirmDeleteTemplate] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<'all' | 'succeeded' | 'failed' | 'refused'>(
    'all',
  );
  const [wizard, setWizard] = useState(false);
  const [wizardSection, setWizardSection] = useState(1);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  // Template binding decides "same kind of document" for automatic rules.
  const [binding, setBinding] = useState<DocumentTemplateBinding | null>(null);
  const [bindTemplateId, setBindTemplateId] = useState('');
  // The editable mapping now lives in "3 · Downstream": review only shows the result.
  const [mappingOpen, setMappingOpen] = useState(false);
  // Connector/template pair whose stored mapping finished seeding, so Review can build the body.
  const [mappingReadyFor, setMappingReadyFor] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<DispatchReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => templates.find((item) => item.template_id === selectedId) ?? null,
    [templates, selectedId],
  );

  const selectedConnector = useMemo(
    () => connectors.find((item) => item.connector_id === connectorId) ?? null,
    [connectors, connectorId],
  );

  const unmappedRequired = useMemo(() => {
    if (!selectedConnector) return 0;
    return selectedConnector.request_fields.filter(
      (field) => field.required && !field.unsupported && !mapping[field.path],
    ).length;
  }, [selectedConnector, mapping]);

  const flow = useMemo(
    () =>
      automationFlow({
        hasTemplate: Boolean(selected),
        variableCount: selected?.variables.length ?? 0,
        hasConnector: Boolean(selectedConnector),
        hasSpec: Boolean(selectedConnector?.operation),
        unmappedRequired,
        prepared: Boolean(prepared),
        bodyIssues: prepared?.body_issues.length ?? 0,
        lastSendSucceeded: receipt?.status === 'succeeded',
      }),
    [selected, selectedConnector, unmappedRequired, prepared, receipt],
  );

  const templateNameRef = useRef<HTMLInputElement | null>(null);
  const detectRef = useRef<HTMLButtonElement | null>(null);
  const connectorRef = useRef<HTMLSelectElement | null>(null);
  const mappingRef = useRef<HTMLDivElement | null>(null);
  const valuesRef = useRef<HTMLDivElement | null>(null);
  const sendRef = useRef<HTMLButtonElement | null>(null);

  // Step-by-step mode shows one section at a time; the guide above still names the next action.
  const currentSection =
    flow.id === 'template' ? 1 : flow.id === 'fields' ? 2 : flow.id === 'target' ? 3 : 4;
  const showSection = (section: number) => !wizard || wizardSection === section;

  useEffect(() => {
    if (wizard) setWizardSection(currentSection);
    // Only jump when the mode is switched on; explicit Back/Next must not be undone.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wizard]);

  const goToStep = (step: AutomationStepId) => {
    const targets: Record<AutomationStepId, HTMLElement | null> = {
      template: templateNameRef.current,
      fields: detectRef.current,
      target: connectorRef.current,
      mapping: mappingRef.current,
      values: valuesRef.current,
      send: sendRef.current,
    };
    const reveal = (element: HTMLElement | null) => {
      if (!element) return;
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      (element as HTMLElement & { focus?: () => void }).focus?.();
    };
    if (step === 'mapping') {
      // The editor sits behind a disclosure in "3 · Downstream": open it before revealing it.
      setMappingOpen(true);
      window.setTimeout(() => reveal(mappingRef.current), 0);
      return;
    }
    reveal(targets[step]);
  };

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  const run = useCallback(
    async <T,>(work: () => Promise<T>, message?: string): Promise<T | null> => {
      setBusy(true);
      setError(null);
      try {
        const result = await work();
        if (message) setNotice(message);
        return result;
      } catch (failure) {
        setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const refresh = useCallback(async () => {
    const [templatePage, connectorPage, dispatchPage] = await Promise.all([
      client.listTemplates(),
      client.listConnectors(),
      client.listDispatches(10),
    ]);
    setTemplates(templatePage.items);
    setConnectors(connectorPage.items);
    setHistory(dispatchPage.items);
    setSelectedId((current) => current ?? templatePage.items[0]?.template_id ?? null);
    setConnectorId((current) => {
      if (current && connectorPage.items.some((item) => item.connector_id === current)) {
        return current;
      }
      return connectorPage.items[0]?.connector_id ?? '';
    });
  }, [client]);

  useEffect(() => {
    void refresh().catch((failure) => {
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
    });
  }, [refresh]);

  useEffect(() => {
    if (!documentId) {
      setBinding(null);
      setBindTemplateId('');
      return;
    }
    let alive = true;
    client
      .getDocumentTemplate(documentId)
      .then((next) => {
        if (!alive) return;
        setBinding(next);
        setBindTemplateId(next.template_id ?? '');
      })
      .catch(() => {
        if (alive) setBinding(null);
      });
    return () => {
      alive = false;
    };
  }, [documentId, client]);

  const connectorsRef = useRef(connectors);
  connectorsRef.current = connectors;
  const variablesRef = useRef<TemplateVariable[]>([]);
  variablesRef.current = selected?.variables ?? [];
  const seededForRef = useRef<string | null>(null);

  useEffect(() => {
    // Seed the mapping exactly once per (connector, template) pair. The pair mapping lives on the
    // server, so one connector can serve several templates without their mappings overwriting
    // each other; `configured=false` means "suggest by label".
    const connectorRow = connectors.find((item) => item.connector_id === connectorId);
    if (!connectorRow) return;
    const variableCount = variablesRef.current.length;
    // Without confirmed variables there is nothing to suggest; wait for them instead of caching an
    // empty mapping for this pair.
    if (variableCount === 0) return;
    const key = `${connectorRow.connector_id}:${selectedId ?? ''}:${variableCount}`;
    if (seededForRef.current === key) return;
    seededForRef.current = key;
    const fallback = () => {
      const stored = connectorRow.body_map ?? {};
      setMapping(
        Object.keys(stored).length
          ? stored
          : suggestMappings(
              connectorRow.request_fields.map((item) => ({
                path: item.path,
                type: item.type as 'string',
                required: item.required,
                unsupported: item.unsupported ?? undefined,
              })),
              variablesRef.current.map((item) => ({
                variableId: item.key,
                label: item.label,
                displayValue: item.sample_value ?? null,
              })),
            ),
      );
      setMappingReadyFor(key);
    };
    if (!selectedId) {
      fallback();
      return;
    }
    void client
      .readMapping(selectedId, connectorRow.connector_id)
      .then((pair) => {
        if (pair.configured) setMapping(pair.body_map);
        else fallback();
        setMappingReadyFor(key);
      })
      .catch(() => fallback());
  }, [connectorId, selectedId, connectors, client]);

  const applyEditSpec = async (source: string = editSpecText) => {
    const parsed = await parseContract(source);
    if (!parsed.ok) {
      setEditSpecContract(null);
      setError(parsed.error);
      return;
    }
    setError(null);
    setEditSpecText(source);
    setEditSpecContract(parsed.contract);
    const first =
      parsed.contract.operations.find((item) => item.available) ?? parsed.contract.operations[0];
    setEditOperation((current) => current || first?.id || '');
  };

  const startEdit = () => {
    if (!selectedConnector) return;
    setEditing({
      name: selectedConnector.name,
      base_url: selectedConnector.base_url,
      path: selectedConnector.path,
      auth_kind: selectedConnector.auth_kind,
      auth_header: selectedConnector.auth_header ?? 'X-Api-Key',
      secret_env: selectedConnector.secret_env ?? '',
    });
    setEditSpecText('');
    setEditSpecContract(null);
    setEditOperation(selectedConnector.operation ?? '');
    setConfirmDisable(false);
  };

  const loadStoredSpec = async () => {
    if (!selectedConnector) return;
    const stored = await run(() => client.readConnectorSpec(selectedConnector.connector_id));
    if (!stored) return;
    await applyEditSpec(JSON.stringify(stored.spec, null, 2));
  };

  const saveEdit = async () => {
    if (!selectedConnector || !editing) return;
    let spec: Record<string, unknown> | undefined;
    if (editSpecText.trim()) {
      try {
        spec = JSON.parse(editSpecText) as Record<string, unknown>;
      } catch {
        setError('The OpenAPI document is not valid JSON.');
        return;
      }
    }
    const updated = await run(
      () =>
        client.updateConnector(selectedConnector.connector_id, {
          name: editing.name.trim() || selectedConnector.name,
          base_url: editing.base_url.trim(),
          path: editing.path.trim() || '/',
          auth_kind: editing.auth_kind,
          auth_header: editing.auth_kind === 'header' ? editing.auth_header : undefined,
          secret_env: editing.auth_kind === 'none' ? undefined : editing.secret_env || undefined,
          ...(spec ? { spec, operation: editOperation || undefined } : {}),
        }),
      spec
        ? 'Connector updated — the field mapping was reset for the new contract.'
        : 'Connector updated.',
    );
    if (!updated) return;
    setConnectors((current) =>
      current.map((item) => (item.connector_id === updated.connector_id ? updated : item)),
    );
    setEditing(null);
    setEditSpecText('');
    setEditSpecContract(null);
    setPrepared(null);
  };

  const disableSelected = async () => {
    if (!selectedConnector) return;
    const disabled = await run(
      () => client.disableConnector(selectedConnector.connector_id),
      'Connector disabled — it no longer appears in the list.',
    );
    if (!disabled) return;
    setEditing(null);
    setConfirmDisable(false);
    setPrepared(null);
    await run(refresh);
  };

  useEffect(() => {
    setRenameDraft(selected?.name ?? '');
    setConfirmDeleteTemplate(false);
  }, [selected?.template_id, selected?.name]);

  const renameSelected = async () => {
    if (!selected) return;
    const next = renameDraft.trim();
    if (!next || next === selected.name) return;
    const updated = await run(
      () => client.renameTemplate(selected.template_id, next),
      'Template renamed.',
    );
    if (!updated) return;
    setTemplates((current) =>
      current.map((item) => (item.template_id === updated.template_id ? updated : item)),
    );
  };

  const duplicateSelected = async () => {
    if (!selected) return;
    const created = await run(
      () => client.duplicateTemplate(selected.template_id, `${selected.name} (copy)`),
      'Template duplicated.',
    );
    if (!created) return;
    setTemplates((current) => [created, ...current]);
    setSelectedId(created.template_id);
    setPrepared(null);
  };

  const deleteSelected = async () => {
    if (!selected) return;
    const done = await run(
      () => client.deleteTemplate(selected.template_id).then(() => true),
      'Template deleted.',
    );
    if (!done) return;
    setConfirmDeleteTemplate(false);
    setPrepared(null);
    setSelectedId(null);
    await run(refresh);
  };

  const bindDocument = async () => {
    if (!documentId || !bindTemplateId) return;
    const bound = await run(
      () => client.bindDocumentTemplate(documentId, bindTemplateId),
      'Document type bound to the selected template.',
    );
    if (!bound) return;
    setBinding(bound);
  };

  const saveTemplate = async () => {
    const created = await run(
      () =>
        client.createTemplate({
          name: name.trim() || 'Untitled template',
          text,
          source_kind: 'edited',
          document_id: documentId ?? undefined,
        }),
      'Template saved on the server.',
    );
    if (!created) return;
    setSelectedId(created.template_id);
    setSuggestion(null);
    setPrepared(null);
    await run(refresh);
  };

  const suggest = async () => {
    if (!selected) return;
    setSuggesting(true);
    try {
      const result = await run(
        () => client.suggestVariables(selected.template_id, true),
        'Variables suggested — review and confirm.',
      );
      if (!result) return;
      setSuggestion(result);
      setAccepted(Object.fromEntries(result.variables.map((item) => [item.key, true])));
      setPrepared(null);
    } finally {
      setSuggesting(false);
    }
  };

  const saveVariables = async () => {
    if (!selected || !suggestion) return;
    const chosen = suggestion.variables.filter((item) => accepted[item.key]);
    const saved = await run(
      () => client.saveVariables(selected.template_id, chosen),
      `${chosen.length} variables confirmed.`,
    );
    if (!saved) return;
    setTemplates((current) =>
      current.map((item) => (item.template_id === saved.template_id ? saved : item)),
    );
    setSuggestion(null);
  };

  const prepare = async () => {
    if (!selected) return;
    const result = await run(() =>
      client.preparePayload(selected.template_id, {
        document_id: documentId ?? undefined,
        text: documentId ? undefined : text,
        connector_id: connectorId || undefined,
      }),
    );
    if (!result) return;
    setPrepared(result);
    // Only a connector with a contract owns the mapping; otherwise keep the seeded suggestions.
    if (result.request_body) setMapping(result.body_mapping ?? {});
    setValues(
      Object.fromEntries(
        Object.entries(result.values)
          .filter(([, bound]) => bound.value !== null)
          .map(([key, bound]) => [key, bound.value as string]),
      ),
    );
  };

  // Switching template or downstream invalidates the previous review, preview and receipt.
  const autoPreparedFor = useRef<string | null>(null);
  useEffect(() => {
    setPrepared(null);
    setPreview(null);
    setReceipt(null);
    autoPreparedFor.current = null;
  }, [selectedId, connectorId]);

  // “4 · Review & send” is a review, not a form: as soon as the template, the downstream and the
  // pair's stored mapping are ready, the values are filled from the draft automatically. The user
  // only checks them and decides whether to preview or send.
  useEffect(() => {
    const variableCount = selected?.variables.length ?? 0;
    if (!selected || variableCount === 0 || !connectorId) return;
    const pairKey = `${connectorId}:${selected.template_id}:${variableCount}`;
    if (mappingReadyFor !== pairKey) return;
    const key = `${pairKey}:${documentId ?? 'current-text'}`;
    if (autoPreparedFor.current === key) return;
    autoPreparedFor.current = key;
    void prepare();
  }, [selected, connectorId, documentId, mappingReadyFor, prepare]);

  // A preview only describes the values it was built from, so editing a value invalidates it.
  useEffect(() => {
    setPreview(null);
  }, [values]);

  const applySpec = async (source: string = specText) => {
    const parsed = await parseContract(source);
    if (!parsed.ok) {
      setSpecContract(null);
      setSpecOperation('');
      setError(parsed.error);
      return;
    }
    setError(null);
    setSpecText(source);
    setSpecContract(parsed.contract);
    const first =
      parsed.contract.operations.find((item) => item.available) ?? parsed.contract.operations[0];
    setSpecOperation(first?.id ?? '');
  };

  const importSpecFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 512 * 1024) {
      setError('The OpenAPI document is larger than 512 KB.');
      return;
    }
    try {
      await applySpec(await file.text());
    } catch {
      setError('The file could not be read as text.');
    }
  };

  const saveMapping = async () => {
    if (!selectedConnector) return;
    const saved = await run(
      () => client.saveMapping(selectedConnector.connector_id, mapping, selected?.template_id),
      'Request-body mapping saved.',
    );
    if (!saved) return;
    setConnectors((current) =>
      current.map((item) => (item.connector_id === saved.connector_id ? saved : item)),
    );
    // Rebuild the body with the mapping just saved, so the preview and Send stay in sync.
    await prepare();
  };

  const addConnector = async () => {
    let spec: Record<string, unknown> | undefined;
    if (specText.trim()) {
      try {
        spec = JSON.parse(specText) as Record<string, unknown>;
      } catch {
        setError('The OpenAPI document is not valid JSON.');
        return;
      }
    }
    let fields: Array<{ path: string; type: string; required: boolean }> | undefined;
    if (!spec && fieldsText.trim()) {
      const parsedFields = parseFieldLines(fieldsText);
      if (parsedFields.errors.length) {
        setError(`Custom fields: ${parsedFields.errors.join(' · ')}`);
        return;
      }
      fields = parsedFields.fields;
    }
    const parts = specOperation ? operationParts(specOperation) : null;
    const created = await run(
      () =>
        client.createConnector({
          name: connectorForm.name.trim() || 'Downstream system',
          base_url: connectorForm.base_url.trim(),
          path: parts?.path || connectorForm.path.trim() || '/',
          method: (parts?.method as 'POST' | 'PUT' | 'PATCH' | undefined) ?? 'POST',
          auth_kind: connectorForm.auth_kind,
          auth_header:
            connectorForm.auth_kind === 'header' ? connectorForm.auth_header : undefined,
          secret_env:
            connectorForm.auth_kind === 'none' ? undefined : connectorForm.secret_env || undefined,
          spec,
          operation: specOperation || undefined,
          fields,
        }),
      'Connector saved.',
    );
    if (!created) return;
    setConnectorId(created.connector_id);
    setConnectorForm({ ...emptyConnector });
    setSpecText('');
    setSpecContract(null);
    setSpecOperation('');
    setFieldsText('');
    setPrepared(null);
    await run(refresh);
    setNotice(
      created.operation
        ? 'Connector saved and selected — the request-body mapping below is pre-filled; the guide above shows the next step.'
        : 'Connector saved and selected — the guide above shows the next step.',
    );
    if (created.operation) setMappingOpen(true);
    window.setTimeout(() => {
      (created.operation ? mappingRef.current : valuesRef.current)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }, 250);
  };

  const resetMapping = async () => {
    if (!selected || !selectedConnector) return;
    const suggestions = suggestMappings(
      selectedConnector.request_fields.map((item) => ({
        path: item.path,
        type: item.type as 'string',
        required: item.required,
        unsupported: item.unsupported ?? undefined,
      })),
      variables.map((item) => ({
        variableId: item.key,
        label: item.label,
        displayValue: item.sample_value ?? null,
      })),
    );
    setMapping(suggestions);
    const saved = await run(
      () => client.saveMapping(selectedConnector.connector_id, suggestions, selected.template_id),
      'Mapping reset to the label-based suggestions.',
    );
    if (!saved) return;
    setConnectors((current) =>
      current.map((item) => (item.connector_id === saved.connector_id ? saved : item)),
    );
    // Rebuild the review with the suggestions just saved.
    await prepare();
  };

  const previewRequest = async () => {
    if (!selected || !connectorId) return;
    const payload = Object.fromEntries(
      Object.entries(values).filter(([, value]) => value.trim() !== ''),
    );
    const result = await run(() =>
      client.previewDispatch({
        template_id: selected.template_id,
        connector_id: connectorId,
        document_id: documentId ?? undefined,
        values: payload,
      }),
    );
    if (result) setPreview(result);
  };

  const send = async () => {
    if (!selected || !connectorId) return;
    const result = await run(
      () =>
        client.dispatch({
          template_id: selected.template_id,
          connector_id: connectorId,
          document_id: documentId ?? undefined,
          values: Object.fromEntries(
            Object.entries(values).filter(([, value]) => value.trim() !== ''),
          ),
          idempotency_key: `${selected.template_id}:${connectorId}:${Date.now()}`,
        }),
      'Dispatch completed.',
    );
    if (!result) return;
    setReceipt(result);
    await run(refresh);
  };

  const variables = selected?.variables ?? [];
  const suggestedRows = suggestion?.variables ?? [];

  return (
    <div className="automation-server" aria-label="Server automation">
      {notice ? (
        <p className="tiny" role="status" aria-live="polite">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="notice notice--bad tiny" role="alert">
          {error}
        </p>
      ) : null}

      <div className="automation-next" data-testid="automation-next" data-tour="automation-next">
        <div className="row">
          <span className="tag tag--muted">
            Step {flow.index}/{flow.total}
          </span>
          <strong className="tiny">{flow.title}</strong>
          <button
            type="button"
            className="tiny"
            onClick={() => goToStep(flow.id)}
            data-testid="automation-next-go"
            data-tour="automation-next-go"
          >
            Show me
          </button>
        </div>
        <p className="tiny muted">{flow.detail}</p>
        <div className="row">
          <label className="tiny">
            <input
              type="checkbox"
              checked={wizard}
              onChange={(event) => setWizard(event.target.checked)}
              aria-label="Step-by-step mode"
            />{' '}
            Step-by-step
          </label>
          {wizard ? (
            <>
              <button
                type="button"
                className="tiny"
                onClick={() => setWizardSection((section) => Math.max(1, section - 1))}
                disabled={wizardSection <= 1}
              >
                Back
              </button>
              <span className="tiny muted">
                Section {wizardSection}/4
              </span>
              <button
                type="button"
                className="tiny"
                onClick={() => setWizardSection((section) => Math.min(4, section + 1))}
                disabled={wizardSection >= 4}
              >
                Next
              </button>
            </>
          ) : null}
        </div>
        {selectedConnector ? (
          <p className="tiny muted" data-testid="automation-target">
            Target: {selectedConnector.name} · {selectedConnector.base_url}
            {selectedConnector.schema_kind === 'fields'
              ? ` · custom fields (${selectedConnector.request_fields.length})`
              : selectedConnector.operation
                ? ` · ${selectedConnector.operation}`
                : ' · flat payload (no contract)'}
          </p>
        ) : null}
        <ol className="automation-steps" aria-label="Setup progress">
          {flow.steps.map((step) => (
            <li
              key={step.id}
              className={`automation-step automation-step--${step.state}`}
              aria-current={step.state === 'current' ? 'step' : undefined}
            >
              <span aria-hidden="true">
                {step.state === 'done' ? '✓' : step.state === 'current' ? '●' : '○'}
              </span>{' '}
              {step.label}
            </li>
          ))}
        </ol>
      </div>

      {showSection(1) ? (
      <section className="legal-section" aria-label="Server templates" data-tour="automation-template">
        <h3>1 · Template (server)</h3>
        <div className="row">
          <input
            aria-label="Template name"
            ref={templateNameRef}
            data-tour="automation-template-name"
            value={name}
            onChange={(event) => {
              setNameTouched(true);
              setName(event.target.value);
            }}
            placeholder="Template name"
          />
          <button
            type="button"
            className="primary"
            onClick={() => void saveTemplate()}
            disabled={busy || !text.trim()}
            data-tour="automation-save-template"
          >
            Save current draft as template
          </button>
        </div>
        {templates.some((item) => item.name === name.trim()) ? (
          <p className="tiny muted" data-testid="template-version-note">
            “{name.trim()}” already exists — saving adds a new version.
          </p>
        ) : null}
        {selected ? (
          <div className="row" data-testid="template-manage">
            <input
              aria-label="Rename template"
              value={renameDraft}
              onChange={(event) => setRenameDraft(event.target.value)}
            />
            <button type="button" onClick={() => void renameSelected()} disabled={busy}>
              Rename
            </button>
            <button type="button" onClick={() => void duplicateSelected()} disabled={busy}>
              Duplicate
            </button>
            {confirmDeleteTemplate ? (
              <>
                <span className="tiny">Delete “{selected.name}”?</span>
                <button type="button" onClick={() => void deleteSelected()} disabled={busy}>
                  Yes, delete
                </button>
                <button type="button" onClick={() => setConfirmDeleteTemplate(false)}>
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmDeleteTemplate(true)}
                disabled={busy}
              >
                Delete
              </button>
            )}
          </div>
        ) : null}
        {documentId ? (
          <div className="row tiny" data-testid="document-template-binding" data-tour="automation-bind">
            <span className="tiny muted">Document type:</span>
            <strong className="tiny" data-testid="document-template-name">
              {binding?.template_name ?? 'not bound'}
            </strong>
            <select
              aria-label="Document template"
              value={bindTemplateId}
              onChange={(event) => setBindTemplateId(event.target.value)}
            >
              <option value="">(choose a template)</option>
              {templates.map((item) => (
                <option key={item.template_id} value={item.template_id}>
                  {item.name} v{item.version}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void bindDocument()}
              disabled={busy || !bindTemplateId}
              data-testid="bind-document-template"
            >
              Bind
            </button>
            <span className={`tag tag--${binding?.template_name ? 'muted' : 'warn'}`}>
              {binding?.template_name ? 'bound' : 'not bound'}
            </span>
          </div>
        ) : null}
        {templates.length === 0 ? (
          <p className="tiny muted">No server template yet. Save the current draft to start.</p>
        ) : (
          <div
            role="radiogroup"
            aria-label="Server templates"
            className="legal-suggestions"
            data-tour="automation-template-list"
          >
            {templates.map((item) => (
              <button
                key={item.template_id}
                type="button"
                role="radio"
                aria-checked={item.template_id === selectedId}
                onClick={() => {
                  setSelectedId(item.template_id);
                  setSuggestion(null);
                  setPrepared(null);
                }}
              >
                {item.name} v{item.version} · {item.variables.length} vars
              </button>
            ))}
          </div>
        )}
      </section>
      ) : null}

      {selected && showSection(2) ? (
        <section className="legal-section" aria-label="Variables" data-tour="automation-variables">
          <h3>2 · Fields</h3>
          <p className="tiny muted" data-tour="automation-variable-summary">
              {variables.length
                ? `${variables.length} confirmed: ${variables.map((item) => item.label).join(', ')}`
                : 'No confirmed variables yet.'}
          </p>
          <div className="row">
            <button
              type="button"
              onClick={() => void suggest()}
              disabled={busy}
              ref={detectRef}
              data-tour="automation-find-variables"
            >
              Find variables with AI
            </button>
            {suggestion ? (
              <button
                type="button"
                className="primary"
                onClick={() => void saveVariables()}
                disabled={busy}
                data-tour="automation-confirm-variables"
              >
                Confirm {Object.values(accepted).filter(Boolean).length} variables
              </button>
            ) : null}
          </div>
          {suggesting ? (
            <AiWaitBox
              testId="automation-suggest-wait"
              title="Doubao is reading the template"
              message="Looking for fields that carry a verbatim quote…"
              hint="Nothing is saved until you confirm; the model never sends by itself."
              elapsedMs={suggestElapsed}
            />
          ) : null}
          {suggestion ? (
            <div className="legal-findings" data-tour="automation-suggestions">
              <p className="tiny muted">
                suggested by: {suggestion.suggested_by}
                {suggestion.model ? ` · ${suggestion.model}` : ''}
                {suggestion.warnings.length ? ` · ${suggestion.warnings.join(' · ')}` : ''}
              </p>
              {suggestedRows.map((item) => (
                <label key={item.key} className="row tiny">
                  <input
                    type="checkbox"
                    checked={Boolean(accepted[item.key])}
                    onChange={(event) =>
                      setAccepted((current) => ({ ...current, [item.key]: event.target.checked }))
                    }
                  />
                  <strong>{item.label}</strong>
                  <code>{item.key}</code>
                  <span className="tag tag--muted">{item.value_type}</span>
                  {item.quote ? (
                    <span className="tiny muted">“{item.quote.slice(0, 80)}”</span>
                  ) : null}
                  {item.source === 'llm' ? <span className="tag tag--warn">AI</span> : null}
                </label>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {showSection(3) ? (
      <section className="legal-section" aria-label="Downstream connector" data-tour="automation-downstream">
        <h3>3 · Downstream</h3>
        {connectors.length ? (
          <label className="tiny">
            Connector{' '}
            <select
              aria-label="Downstream connector"
              ref={connectorRef}
              data-tour="automation-connector-select"
              value={connectorId}
              onChange={(event) => {
                const nextId = event.target.value;
                setConnectorId(nextId);
                setMapping(
                  connectors.find((item) => item.connector_id === nextId)?.body_map ?? {},
                );
                setPrepared(null);
              }}
            >
              {connectors.map((item) => (
                <option key={item.connector_id} value={item.connector_id}>
                  {item.name} · {item.base_url}
                  {item.auth_kind !== 'none' && !item.secret_configured ? ' (secret missing)' : ''}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="tiny muted">
            No connector yet. Add one below; the host must be allow-listed on the server.
          </p>
        )}
        {selected && variables.length && selectedConnector?.operation ? (
          // The mapping is setup, not review: it stays in "3 · Downstream" behind a disclosure.
          <details className="tiny" data-testid="mapping-editor" data-tour="automation-mapping-details" open={mappingOpen}>
            <summary
              onClick={(event) => {
                event.preventDefault();
                setMappingOpen((current) => !current);
              }}
            >
              Field mapping ·{' '}
              {unmappedRequired
                ? `${unmappedRequired} required field${unmappedRequired > 1 ? 's' : ''} unmapped`
                : 'all required fields mapped'}
            </summary>
            <div
              className="legal-findings"
              aria-label="Field mapping"
              data-testid="mapping-fields"
              ref={mappingRef}
            >
              <p className="tiny muted" data-testid="spec-operation">
                {selectedConnector.spec_title} {selectedConnector.spec_version} ·{' '}
                {selectedConnector.operation} ·{' '}
                {selectedConnector.content_type ?? 'application/json'}
              </p>
              {selectedConnector.request_fields.map((field) => {
                const issue = prepared?.body_issues.find((item) => item.path === field.path);
                return (
                  <label key={field.path} className="row tiny">
                    <code>{field.path}</code>
                    <span className="tag tag--muted">{field.type}</span>
                    {field.required ? <span className="tag tag--warn">required</span> : null}
                    {field.unsupported ? (
                      <span className="tag tag--bad">{field.unsupported}</span>
                    ) : null}
                    {issue ? (
                      <span className="tag tag--bad" title={issue.message}>
                        {issue.reason}
                      </span>
                    ) : null}
                    <select
                      aria-label={`Variable for ${field.path}`}
                      value={mapping[field.path] ?? ''}
                      disabled={Boolean(field.unsupported)}
                      onChange={(event) =>
                        setMapping((current) => {
                          const next = { ...current };
                          if (event.target.value) next[field.path] = event.target.value;
                          else delete next[field.path];
                          return next;
                        })
                      }
                    >
                      <option value="">(not sent)</option>
                      {variables.map((item) => (
                        <option key={item.key} value={item.key}>
                          {item.label} · {item.key}
                        </option>
                      ))}
                    </select>
                  </label>
                );
              })}
              <div className="row">
                <button type="button" onClick={() => void saveMapping()} disabled={busy}>
                  Save mapping
                </button>
                <button
                  type="button"
                  onClick={() => void resetMapping()}
                  disabled={busy}
                  data-testid="reset-mapping"
                  data-tour="automation-reset-mapping"
                  title="Replace this pair's mapping with the label-based suggestions"
                >
                  Reset to suggestions
                </button>
              </div>
              {selectedConnector.spec_warnings.length ? (
                <span className="tiny muted">{selectedConnector.spec_warnings.join(' · ')}</span>
              ) : null}
            </div>
          </details>
        ) : null}
        {selectedConnector?.spec_error ? (
          <p className="notice notice--bad tiny" role="alert">
            {selectedConnector.spec_error}
          </p>
        ) : null}
        {selectedConnector ? (
          <div className="row">
            <button type="button" onClick={startEdit} disabled={busy}>
              Edit connector
            </button>
            {confirmDisable ? (
              <>
                <span className="tiny">Disable this connector?</span>
                <button type="button" onClick={() => void disableSelected()} disabled={busy}>
                  Yes, disable
                </button>
                <button type="button" onClick={() => setConfirmDisable(false)}>
                  Cancel
                </button>
              </>
            ) : (
              <button type="button" onClick={() => setConfirmDisable(true)} disabled={busy}>
                Disable connector
              </button>
            )}
          </div>
        ) : null}
        {editing ? (
          <div className="legal-section" aria-label="Edit connector" data-testid="connector-edit">
            <input
              aria-label="Edit connector name"
              value={editing.name}
              onChange={(event) =>
                setEditing((current) => (current ? { ...current, name: event.target.value } : current))
              }
            />
            <input
              aria-label="Edit connector base URL"
              value={editing.base_url}
              onChange={(event) =>
                setEditing((current) =>
                  current ? { ...current, base_url: event.target.value } : current,
                )
              }
            />
            <input
              aria-label="Edit connector path"
              value={editing.path}
              onChange={(event) =>
                setEditing((current) => (current ? { ...current, path: event.target.value } : current))
              }
            />
            <select
              aria-label="Edit connector auth"
              value={editing.auth_kind}
              onChange={(event) =>
                setEditing((current) =>
                  current
                    ? { ...current, auth_kind: event.target.value as Connector['auth_kind'] }
                    : current,
                )
              }
            >
              <option value="none">No auth</option>
              <option value="bearer">Bearer token</option>
              <option value="header">Custom header</option>
            </select>
            {editing.auth_kind !== 'none' ? (
              <>
                {editing.auth_kind === 'header' ? (
                  <input
                    aria-label="Edit connector auth header"
                    value={editing.auth_header}
                    onChange={(event) =>
                      setEditing((current) =>
                        current ? { ...current, auth_header: event.target.value } : current,
                      )
                    }
                  />
                ) : null}
                <input
                  aria-label="Edit connector secret env"
                  placeholder="ENV_VAR_HOLDING_THE_TOKEN"
                  value={editing.secret_env}
                  onChange={(event) =>
                    setEditing((current) =>
                      current ? { ...current, secret_env: event.target.value } : current,
                    )
                  }
                />
              </>
            ) : null}
            <div className="row">
              <button type="button" onClick={() => void loadStoredSpec()} disabled={busy}>
                Load saved spec
              </button>
              <input
                type="file"
                accept=".json,application/json"
                aria-label="Replace OpenAPI spec file"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  event.target.value = '';
                  if (file) void applyEditSpec(await file.text());
                }}
              />
              <button
                type="button"
                onClick={() => void applyEditSpec()}
                disabled={busy || !editSpecText.trim()}
              >
                Parse spec
              </button>
              {editSpecContract ? (
                <span className="tiny muted">
                  {editSpecContract.title} {editSpecContract.version}
                </span>
              ) : null}
            </div>
            <textarea
              aria-label="Edit connector OpenAPI spec"
              rows={4}
              placeholder="Paste a replacement OpenAPI 3.x JSON (leave empty to keep the current one)"
              value={editSpecText}
              onChange={(event) => setEditSpecText(event.target.value)}
            />
            {editSpecContract ? (
              <select
                aria-label="Edit connector operation"
                value={editOperation}
                onChange={(event) => setEditOperation(event.target.value)}
              >
                {editSpecContract.operations.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.available}>
                    {item.id}
                    {item.available ? '' : ' (no JSON body)'}
                  </option>
                ))}
              </select>
            ) : null}
            <div className="row">
              <button type="button" className="primary" onClick={() => void saveEdit()} disabled={busy}>
                Save changes
              </button>
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </div>
          </div>
        ) : null}
        <details className="tiny" data-tour="automation-add-connector">
          <summary>Add connector</summary>
          <div className="legal-section">
            <input
              aria-label="Connector name"
              placeholder="Name"
              value={connectorForm.name}
              onChange={(event) =>
                setConnectorForm((current) => ({ ...current, name: event.target.value }))
              }
            />
            <input
              aria-label="Connector base URL"
              placeholder="https://erp.example.com"
              value={connectorForm.base_url}
              onChange={(event) =>
                setConnectorForm((current) => ({ ...current, base_url: event.target.value }))
              }
            />
            <input
              aria-label="Connector path"
              placeholder="/hooks/smart-edit"
              value={connectorForm.path}
              onChange={(event) =>
                setConnectorForm((current) => ({ ...current, path: event.target.value }))
              }
            />
            <select
              aria-label="Connector auth"
              value={connectorForm.auth_kind}
              onChange={(event) =>
                setConnectorForm((current) => ({
                  ...current,
                  auth_kind: event.target.value as Connector['auth_kind'],
                }))
              }
            >
              <option value="none">No auth</option>
              <option value="bearer">Bearer token</option>
              <option value="header">Custom header</option>
            </select>
            {connectorForm.auth_kind !== 'none' ? (
              <input
                aria-label="Connector secret env"
                placeholder="ENV_VAR_HOLDING_THE_TOKEN"
                value={connectorForm.secret_env}
                onChange={(event) =>
                  setConnectorForm((current) => ({ ...current, secret_env: event.target.value }))
                }
              />
            ) : null}
            <label className="tiny">
              OpenAPI spec (JSON, optional)
              <textarea
                aria-label="Connector OpenAPI spec"
                rows={4}
                placeholder="Paste the downstream system's OpenAPI 3.x JSON"
                value={specText}
                onChange={(event) => setSpecText(event.target.value)}
              />
            </label>
            <label className="tiny">
              Or custom fields (one per line: `path: type`, `*` = required)
              <textarea
                aria-label="Connector custom fields"
                rows={3}
                placeholder={'amount: number *\nbeneficiary.name: string *\nnote: string'}
                value={fieldsText}
                onChange={(event) => setFieldsText(event.target.value)}
              />
            </label>
            <div className="row">
              <input
                type="file"
                accept=".json,application/json"
                aria-label="Import OpenAPI spec file"
                onChange={(event) => {
                  void importSpecFile(event.target.files?.[0]);
                  event.target.value = '';
                }}
              />
              <button
                type="button"
                onClick={() => void applySpec()}
                disabled={busy || !specText.trim()}
              >
                Parse spec
              </button>
              {specContract ? (
                <span className="tiny muted">
                  {specContract.title} {specContract.version}
                </span>
              ) : null}
            </div>
            <p className="tiny muted">
              Where to get it: the provider&rsquo;s <code>/openapi.json</code> or{' '}
              <code>/v3/api-docs</code> (Spring), Swagger Editor &ldquo;Download JSON&rdquo;, an Apigee /
              Azure API Management export, or the partner&rsquo;s API docs. Swagger 2.0 and YAML are
              rejected on purpose — convert them to OpenAPI 3.x JSON.
            </p>
            {specContract ? (
              <select
                aria-label="Connector operation"
                value={specOperation}
                onChange={(event) => setSpecOperation(event.target.value)}
              >
                {specContract.operations.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.available}>
                    {item.id}
                    {item.available ? '' : ' (no JSON body)'}
                  </option>
                ))}
              </select>
            ) : null}
            <button type="button" onClick={() => void addConnector()} disabled={busy}>
              Save connector
            </button>
          </div>
        </details>
      </section>
      ) : null}

      {showSection(4) ? (
      <section className="legal-section" aria-label="Review and send" data-tour="automation-review">
        <h3>4 · Review &amp; send</h3>
        {selected ? (
          <p className="tiny muted" data-testid="review-target" data-tour="automation-review-target">
            {selected.name} v{selected.version} → {selectedConnector?.name ?? 'no downstream yet'}
            {selectedConnector?.operation
              ? ` · ${selectedConnector.operation} · ${
                  selectedConnector.content_type ?? 'application/json'
                }`
              : ''}
          </p>
        ) : null}
        {selected && selectedConnector?.operation ? (
          <div
            className="legal-findings"
            aria-label="Request body mapping"
            data-testid="spec-mapping"
            data-tour="automation-review-body"
          >
            <ul className="tiny" aria-label="Mapping summary">
              {selectedConnector.request_fields.map((field) => {
                const mappedKey =
                  prepared?.body_mapping?.[field.path] ?? mapping[field.path] ?? '';
                const variable = variables.find((item) => item.key === mappedKey);
                const issue = prepared?.body_issues.find((item) => item.path === field.path);
                return (
                  <li key={field.path} data-testid={`review-field-${field.path}`}>
                    <code>{field.path}</code>
                    {variable ? (
                      <>
                        {' ← '}
                        {variable.label} <span className="tiny muted">({variable.key})</span>
                      </>
                    ) : (
                      <>
                        {' '}
                        <span className="tag tag--warn">not sent</span>
                      </>
                    )}
                    {issue ? (
                      <span className="tag tag--bad" title={issue.message}>
                        {issue.reason}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            {unmappedRequired ? (
              <p className="tiny muted" data-testid="review-unmapped">
                {unmappedRequired} required field{unmappedRequired > 1 ? 's are' : ' is'} unmapped
                — fix it under 3 · Downstream → Field mapping.
              </p>
            ) : null}
          </div>
        ) : null}
        {selected && variables.length ? (
          <>
            <div data-testid="review-values" ref={valuesRef}>
              {prepared ? (
                <div className="legal-findings">
                  <p className="tiny muted">
                    bound {Object.values(prepared.values).filter((item) => item.value).length}/
                    {variables.length}
                    {prepared.missing_required.length
                      ? ` · missing required: ${prepared.missing_required.join(', ')}`
                      : ''}
                  </p>
                  {variables.map((item) => (
                    <label key={item.key} className="row tiny">
                      <span className="tiny muted">{item.label}</span>
                      <input
                        aria-label={`Value for ${item.label}`}
                        value={values[item.key] ?? ''}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [item.key]: event.target.value }))
                        }
                        placeholder={item.required ? 'required' : 'optional'}
                      />
                      <span className="tag tag--muted">
                        {prepared.values[item.key]?.source ?? 'missing'}
                      </span>
                    </label>
                  ))}
                  <pre className="tiny" aria-label="Payload preview" data-tour="automation-payload-preview">
                    {JSON.stringify(prepared.request_body ?? prepared.payload, null, 2)}
                  </pre>
                  {prepared.request_body ? (
                    <p className="tiny muted" data-testid="spec-body-note">
                      Body follows the downstream OpenAPI operation
                      {selectedConnector?.operation ? ` · ${selectedConnector.operation}` : ''}
                      {prepared.content_type ? ` · ${prepared.content_type}` : ''}
                    </p>
                  ) : null}
                  {prepared.body_issues.length ? (
                    <ul className="tiny" data-testid="spec-body-issues">
                      {prepared.body_issues.map((issue) => (
                        <li key={`${issue.path}:${issue.reason}`}>
                          <code>{issue.path}</code> — {issue.message}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : (
                <p className="tiny muted" data-testid="review-pending">
                  Filling the values from the draft…
                </p>
              )}
            </div>
            <div className="row">
              <button
                type="button"
                onClick={() => void previewRequest()}
                disabled={busy || !connectorId || !prepared}
                data-testid="preview-request"
                data-tour="automation-preview-request"
              >
                Preview request
              </button>
              <button
                type="button"
                className="primary"
                ref={sendRef}
                onClick={() => void send()}
                disabled={busy || !connectorId || !prepared || prepared.body_issues.length > 0}
                data-testid="send"
                data-tour="automation-send"
              >
                Send
              </button>
            </div>
          {preview ? (
            <div className="legal-findings" data-testid="request-preview" data-tour="automation-request-preview">
              <p className="tiny muted">
                {preview.method} {preview.url}
                {preview.schema_kind ? ` · ${preview.schema_kind}` : ''}
                {preview.refusal ? ` · refused: ${preview.refusal}` : ''}
              </p>
              <ul className="tiny">
                {Object.entries(preview.headers).map(([name, value]) => (
                  <li key={name}>
                    <code>{name}</code>: {value}
                  </li>
                ))}
              </ul>
              <pre className="tiny" aria-label="Preview body">
                {JSON.stringify(preview.body, null, 2)}
              </pre>
              {preview.issues.length ? (
                <ul className="tiny" data-testid="preview-issues">
                  {preview.issues.map((issue) => (
                    <li key={`${issue.path}:${issue.reason}`}>
                      <code>{issue.path}</code> — {issue.message}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          {prepared && !flow.canSend ? (
            <p className="tiny muted" data-testid="send-blocked">
              {prepared.body_issues.length
                ? `Send is blocked: ${prepared.body_issues
                    .map((issue) => issue.path)
                    .join(', ')} still ${prepared.body_issues.length > 1 ? 'need' : 'needs'} a value.`
                : 'Send is blocked until the steps above are complete.'}
            </p>
          ) : null}
          </>
        ) : (
          <p className="tiny muted">Confirm the fields in 2 · Fields to review the request.</p>
        )}
        {receipt ? (
          <div className="legal-finding" aria-label="Dispatch receipt">
            <div className="row">
              <span className={`tag tag--${receipt.status === 'succeeded' ? 'ok' : 'bad'}`}>
                {receipt.status}
              </span>
              <span className="tiny muted">
                {receipt.status_code ?? '—'} · {receipt.latency_ms ?? '—'} ms ·{' '}
                {receipt.dispatch_id}
              </span>
            </div>
            {receipt.response_excerpt ? (
              <pre className="tiny">{receipt.response_excerpt.slice(0, 400)}</pre>
            ) : null}
            {receipt.error_code ? <p className="tiny muted">error: {receipt.error_code}</p> : null}
          </div>
        ) : null}
        {history.length ? (
          <details className="tiny muted" data-testid="dispatch-history-wrap" data-tour="automation-history-details">
            <summary>Recent dispatches ({history.length})</summary>
            <p>
              <select
                aria-label="Receipt filter"
                value={historyFilter}
                onChange={(event) =>
                  setHistoryFilter(event.target.value as typeof historyFilter)
                }
              >
                <option value="all">All</option>
                <option value="succeeded">Succeeded</option>
                <option value="failed">Failed</option>
                <option value="refused">Refused</option>
              </select>
            </p>
            <ul data-testid="dispatch-history">
              {history
                .filter((item) => historyFilter === 'all' || item.status === historyFilter)
                .map((item) => (
                  <li key={item.dispatch_id}>
                    {item.status} · {item.status_code ?? '—'} · {item.latency_ms ?? '—'} ms ·{' '}
                    {item.created_at}
                  </li>
                ))}
            </ul>
          </details>
        ) : null}
      </section>
      ) : null}
    </div>
  );
}