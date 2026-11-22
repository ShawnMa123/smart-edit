/** Bank Ops rules: template kind → downstream, with an explicit trust tier (shadow by default). */

import { useEffect, useState } from 'react';

import {
  rulesClient,
  type AutomationRule,
  type RuleDryRun,
  type RuleMode,
  type RulesClient,
} from '../api/automationRules';
import { ApiError, explainError } from '../api/errors';
import { registryClient, type RegistryClient } from '../api/automationRegistry';

export interface AutomationRulesPanelProps {
  /** Documents are the only dry-run input: what would this rule send for this document? */
  documentId: string | null;
  client?: RulesClient;
  registry?: RegistryClient;
}

const MODES: Array<[RuleMode, string]> = [
  ['shadow', 'Shadow (record only)'],
  ['needs_review', 'Needs review'],
  ['auto_send', 'Auto send'],
];

const WARNING_LABELS: Record<string, string> = {
  duplicate_connector: 'This downstream is configured twice for the template',
  template_missing: 'The template no longer exists',
  connector_missing: 'The downstream connector is gone or disabled',
};

export function AutomationRulesPanel({
  documentId,
  client = rulesClient,
  registry = registryClient,
}: AutomationRulesPanelProps) {
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [templates, setTemplates] = useState<Array<{ name: string }>>([]);
  const [connectors, setConnectors] = useState<Array<{ connector_id: string; name: string }>>([]);
  const [form, setForm] = useState({
    name: '',
    template_name: '',
    connector_id: '',
    mode: 'shadow' as RuleMode,
    required: true,
    priority: 100,
  });
  const [dryRun, setDryRun] = useState<RuleDryRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async <T,>(work: () => Promise<T>, message?: string): Promise<T | null> => {
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
  };

  const refresh = async () => {
    const [page, templatePage, connectorPage] = await Promise.all([
      client.listRules(),
      registry.listTemplates(),
      registry.listConnectors(),
    ]);
    setRules(page.items);
    setTemplates(templatePage.items);
    setConnectors(connectorPage.items);
    setForm((current) => ({
      ...current,
      template_name: current.template_name || templatePage.items[0]?.name || '',
      connector_id: current.connector_id || connectorPage.items[0]?.connector_id || '',
    }));
  };

  useEffect(() => {
    void run(refresh).catch((failure) => setError(String(failure)));
    // The rule list is refreshed when the panel opens; actions call `refresh` explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    const created = await run(
      () =>
        client.createRule({
          name: form.name.trim() || `${form.template_name} rule`,
          template_name: form.template_name,
          connector_id: form.connector_id,
          mode: form.mode,
          required: form.required,
          priority: form.priority,
        }),
      'Rule saved. New rules stay in shadow until you raise the tier.',
    );
    if (!created) return;
    setForm((current) => ({ ...current, name: '' }));
    await run(refresh);
  };

  const changeMode = async (rule: AutomationRule, mode: RuleMode) => {
    const updated = await run(
      () => client.setRuleMode(rule.rule_id, mode),
      `Rule "${rule.name}" is now ${mode}.`,
    );
    if (!updated) return;
    await run(refresh);
  };

  const toggle = async (rule: AutomationRule) => {
    const updated = await run(
      () => client.updateRule(rule.rule_id, { enabled: !rule.enabled }),
      rule.enabled ? 'Rule paused.' : 'Rule resumed.',
    );
    if (!updated) return;
    await run(refresh);
  };

  const remove = async (rule: AutomationRule) => {
    await run(() => client.deleteRule(rule.rule_id), 'Rule disabled.');
    await run(refresh);
  };

  const preview = async (rule: AutomationRule) => {
    if (!documentId) return;
    const result = await run(() => client.dryRunRule(rule.rule_id, documentId));
    if (result) setDryRun(result);
  };

  return (
    <div className="automation-server" aria-label="Automation rules" data-testid="automation-rules">
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

      <p className="tiny muted">
        A rule pairs one template kind with one downstream. New rules start in <strong>shadow</strong>:
        they compute the request but never call out until you raise the tier.
      </p>

      <div className="legal-section" aria-label="New rule">
        <h3>New rule</h3>
        <div className="row">
          <input
            aria-label="Rule name"
            placeholder="Rule name"
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
          />
          <select
            aria-label="Rule template"
            value={form.template_name}
            onChange={(event) =>
              setForm((current) => ({ ...current, template_name: event.target.value }))
            }
          >
            {templates.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Rule connector"
            value={form.connector_id}
            onChange={(event) =>
              setForm((current) => ({ ...current, connector_id: event.target.value }))
            }
          >
            {connectors.map((item) => (
              <option key={item.connector_id} value={item.connector_id}>
                {item.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Rule mode"
            value={form.mode}
            onChange={(event) =>
              setForm((current) => ({ ...current, mode: event.target.value as RuleMode }))
            }
          >
            {MODES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="primary"
            onClick={() => void save()}
            disabled={busy || !form.template_name || !form.connector_id}
            data-testid="save-rule"
          >
            Save rule
          </button>
        </div>
      </div>

      <div className="legal-section" aria-label="Rules">
        <h3>Rules</h3>
        {rules.length === 0 ? <p className="tiny muted">No rules yet.</p> : null}
        {rules.map((rule) => (
          <div key={rule.rule_id} className="legal-finding" data-testid={`rule-${rule.rule_id}`}>
            <div className="row">
              <strong className="tiny">{rule.name}</strong>
              <span className="tag tag--muted">{rule.template_name}</span>
              <span className="tag tag--muted">
                → {rule.connector_name ?? rule.connector_id}
              </span>
              <span
                className={`tag tag--${
                  rule.mode === 'auto_send' ? 'ok' : rule.mode === 'needs_review' ? 'warn' : 'muted'
                }`}
              >
                {rule.mode}
              </span>
              {rule.required ? <span className="tag tag--muted">required</span> : null}
              {!rule.enabled ? <span className="tag tag--bad">paused</span> : null}
            </div>
            {rule.warnings.length ? (
              <ul className="tiny" data-testid={`rule-warnings-${rule.rule_id}`}>
                {rule.warnings.map((warning) => (
                  <li key={warning}>{WARNING_LABELS[warning] ?? warning}</li>
                ))}
              </ul>
            ) : null}
            <div className="row">
              <select
                aria-label={`Tier for ${rule.name}`}
                value={rule.mode}
                onChange={(event) => void changeMode(rule, event.target.value as RuleMode)}
                disabled={busy || !rule.enabled}
              >
                {MODES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void preview(rule)}
                disabled={busy || !documentId}
              >
                Dry-run on this document
              </button>
              <button type="button" onClick={() => void toggle(rule)} disabled={busy}>
                {rule.enabled ? 'Pause' : 'Resume'}
              </button>
              <button type="button" onClick={() => void remove(rule)} disabled={busy}>
                Disable
              </button>
            </div>
          </div>
        ))}
      </div>

      {dryRun ? (
        <div className="legal-findings" data-testid="rule-dry-run">
          <p className="tiny muted">
            {dryRun.method} {dryRun.url} · template {dryRun.template_name} · {dryRun.mode}
            {dryRun.refusal ? ` · refused: ${dryRun.refusal}` : ''}
          </p>
          <pre className="tiny" aria-label="Rule dry-run body">
            {JSON.stringify(dryRun.would_send, null, 2)}
          </pre>
          {dryRun.issues.length ? (
            <ul className="tiny">
              {dryRun.issues.map((issue) => (
                <li key={`${issue.path}:${issue.reason}`}>
                  <code>{issue.path}</code> — {issue.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}