/** Bank Ops rules panel: list, tier change, shadow default and dry-run. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AutomationRulesPanel } from './AutomationRulesPanel';
import type { AutomationRule } from '../api/automationRules';
import type { RegistryClient } from '../api/automationRegistry';

const rule: AutomationRule = {
  rule_id: 'rule_1',
  name: 'Trade intake',
  department_id: null,
  template_name: 'Demand guarantee',
  connector_id: 'con_1',
  connector_name: 'ERP',
  trigger: 'final_approval',
  mode: 'shadow',
  required: true,
  priority: 100,
  enabled: true,
  disabled_at: null,
  warnings: ['duplicate_connector'],
  created_by: 'usr_ops',
  created_at: '2026-11-22T00:00:00Z',
  updated_at: '2026-11-22T00:00:00Z',
};

const registry = {
  listTemplates: vi.fn().mockResolvedValue({
    items: [{ template_id: 'tpl_1', name: 'Demand guarantee', version: '1.0.0' }],
  }),
  listConnectors: vi.fn().mockResolvedValue({
    items: [{ connector_id: 'con_1', name: 'ERP' }],
  }),
} as unknown as RegistryClient;

const baseClient = () => ({
  listRules: vi.fn().mockResolvedValue({ items: [rule] }),
  createRule: vi.fn().mockResolvedValue(rule),
  updateRule: vi.fn().mockResolvedValue(rule),
  setRuleMode: vi.fn().mockResolvedValue({ ...rule, mode: 'needs_review' }),
  deleteRule: vi.fn().mockResolvedValue(undefined),
  dryRunRule: vi.fn().mockResolvedValue({
    rule_id: 'rule_1',
    template_id: 'tpl_1',
    template_name: 'Demand guarantee',
    connector_id: 'con_1',
    mode: 'shadow',
    url: 'https://erp.example.com/hooks/smart-edit',
    method: 'POST',
    would_send: { amount: 750000 },
    issues: [],
    refusal: null,
  }),
});

describe('AutomationRulesPanel', () => {
  it('lists rules with their tier and duplicate-downstream warning', async () => {
    render(
      <AutomationRulesPanel documentId="doc-1" client={baseClient()} registry={registry} />,
    );

    await waitFor(() => expect(screen.getByTestId('rule-rule_1')).toBeTruthy());
    expect(screen.getByTestId('rule-rule_1').textContent).toContain('shadow');
    expect(screen.getByTestId('rule-warnings-rule_1').textContent).toContain(
      'configured twice',
    );
  });

  it('creates a rule in shadow by default', async () => {
    const client = baseClient();
    render(<AutomationRulesPanel documentId="doc-1" client={client} registry={registry} />);

    await waitFor(() => expect(screen.getByTestId('save-rule')).toBeTruthy());
    await userEvent.click(screen.getByTestId('save-rule'));

    await waitFor(() =>
      expect(client.createRule).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: 'shadow',
          template_name: 'Demand guarantee',
          connector_id: 'con_1',
        }),
      ),
    );
  });

  it('changes the tier explicitly and previews a dry-run body', async () => {
    const client = baseClient();
    render(<AutomationRulesPanel documentId="doc-1" client={client} registry={registry} />);

    await waitFor(() => expect(screen.getByLabelText('Tier for Trade intake')).toBeTruthy());
    await userEvent.selectOptions(screen.getByLabelText('Tier for Trade intake'), 'needs_review');
    await waitFor(() => expect(client.setRuleMode).toHaveBeenCalledWith('rule_1', 'needs_review'));

    await userEvent.click(
      screen.getByRole('button', { name: 'Dry-run on this document' }),
    );
    await waitFor(() => expect(screen.getByTestId('rule-dry-run')).toBeTruthy());
    expect(screen.getByLabelText('Rule dry-run body').textContent).toContain('750000');
  });
});