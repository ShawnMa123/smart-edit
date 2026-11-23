/** Automation rules API: template kind → downstream, trigger and trust level (shadow by default). */

import { request, type RegistryOptions } from './automationRegistry';

export type RuleMode = 'shadow' | 'needs_review' | 'auto_send';
export type RuleTrigger = 'final_approval' | 'manual';

export interface AutomationRule {
  rule_id: string;
  name: string;
  department_id: string | null;
  template_name: string;
  connector_id: string;
  connector_name: string | null;
  trigger: RuleTrigger;
  mode: RuleMode;
  required: boolean;
  priority: number;
  enabled: boolean;
  disabled_at: string | null;
  warnings: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface RuleInput {
  name: string;
  template_name: string;
  connector_id: string;
  trigger?: RuleTrigger;
  mode?: RuleMode;
  required?: boolean;
  priority?: number;
  enabled?: boolean;
}

export interface RuleDryRun {
  rule_id: string;
  template_id: string;
  template_name: string;
  connector_id: string;
  mode: RuleMode;
  url: string;
  method: string;
  would_send: Record<string, unknown>;
  issues: Array<{ path: string; reason: string; message: string }>;
  refusal: string | null;
}

export function listRules(options: RegistryOptions = {}): Promise<{ items: AutomationRule[] }> {
  return request('/rules', { method: 'GET' }, options);
}

export function createRule(input: RuleInput, options: RegistryOptions = {}): Promise<AutomationRule> {
  return request(
    '/rules',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function updateRule(
  ruleId: string,
  patch: Partial<RuleInput>,
  options: RegistryOptions = {},
): Promise<AutomationRule> {
  return request(
    `/rules/${encodeURIComponent(ruleId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    },
    options,
  );
}

export function setRuleMode(
  ruleId: string,
  mode: RuleMode,
  options: RegistryOptions = {},
): Promise<AutomationRule> {
  return request(
    `/rules/${encodeURIComponent(ruleId)}/mode`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    },
    options,
  );
}

export function deleteRule(ruleId: string, options: RegistryOptions = {}): Promise<void> {
  return request(`/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' }, options);
}

export function dryRunRule(
  ruleId: string,
  documentId: string,
  options: RegistryOptions = {},
): Promise<RuleDryRun> {
  return request(
    `/rules/${encodeURIComponent(ruleId)}/dry-run`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_id: documentId }),
    },
    options,
  );
}

export interface RulesClient {
  listRules: typeof listRules;
  createRule: typeof createRule;
  updateRule: typeof updateRule;
  setRuleMode: typeof setRuleMode;
  deleteRule: typeof deleteRule;
  dryRunRule: typeof dryRunRule;
}

export const rulesClient: RulesClient = {
  listRules,
  createRule,
  updateRule,
  setRuleMode,
  deleteRule,
  dryRunRule,
};