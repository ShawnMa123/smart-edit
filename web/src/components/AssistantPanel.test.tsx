/** Assistant tabs: knowledge, automation and legal are all wired; audit stays the default. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AssistantPanel } from './AssistantPanel';
import { initialAuditState } from '../auditMachine';

const knowledge = { documentId: 'doc-1', digest: 'a'.repeat(64), text: '保函文本' };
const automation = {
  draft: null,
  document: { type: 'doc' as const, content: [] },
  selection: null,
  pendingVariable: null,
  onChange: vi.fn(),
  onVariableHandled: vi.fn(),
};
const legal = { documentId: 'doc-1' };

const renderPanel = () =>
  render(
    <AssistantPanel
      state={initialAuditState}
      currentDigest="digest-1"
      onRun={vi.fn()}
      onStopWaiting={vi.fn()}
      knowledge={knowledge}
      automation={automation}
      legal={legal}
    />,
  );

describe('AssistantPanel', () => {
  it('offers audit, knowledge, fixture-only automation and legal tabs', () => {
    renderPanel();

    expect(screen.getByRole('tab', { name: 'Rule audit' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Knowledge Q&A' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Automation · fixture only/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Legal advice' })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: /Legal advice · not implemented/ })).toBeNull();
  });

  it('shows short visible labels with the build status as a separate tag', () => {
    renderPanel();

    const automation = screen.getByRole('tab', { name: /Automation · fixture only/ });
    expect(automation.textContent).toContain('Automation');
    expect(automation.textContent).toContain('Fixture only');
    // The visible label is short: no dotted status suffix inside the label itself.
    expect(automation.textContent).not.toContain('·');
    expect(automation.querySelector('.tab-status')?.getAttribute('aria-hidden')).toBe('true');

    const legal = screen.getByRole('tab', { name: 'Legal advice' });
    expect(legal.textContent).toContain('Legal');
    expect(legal.textContent).toContain('Full');

    const audit = screen.getByRole('tab', { name: 'Rule audit' });
    expect(audit.textContent).toContain('Audit');
    expect(audit.textContent).toContain('Full');
  });

  it('renders the audit panel by default', () => {
    renderPanel();

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
  });

  it('renders the knowledge Q&A surface for the knowledge tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Knowledge Q&A' }));

    expect(screen.getByLabelText('Knowledge question')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeTruthy();
    expect(screen.getByText(/Fixture-backed/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Run spec audit/i })).toBeNull();
  });

  it('renders the fixture-only automation workbench, not a generic placeholder', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: /Automation · fixture only/ }));

    expect(screen.getByRole('tab', { name: 'Template' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Variables & Fill' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Downstream Mapping' })).toBeTruthy();
    expect(screen.getByTestId('automation-boundary').textContent).toContain('Fixture-backed');
    expect(screen.getByTestId('automation-boundary').textContent).toContain('Not implemented');
    expect(screen.queryByText(/Automation is not implemented in this build/i)).toBeNull();
  });

  it('renders the legal advice surface for the legal tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));

    expect(screen.getByLabelText('Legal question')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeTruthy();
    expect(screen.getByText(/仅供参考/)).toBeTruthy();
    expect(screen.queryByText(/Legal advice is not implemented in this build/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /Run spec audit/i })).toBeNull();
  });

  it('returns to the audit panel from the legal tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Rule audit' }));

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
  });

  it('states that the assistant does not approve', () => {
    renderPanel();

    expect(screen.getByText(/does not approve or submit/i)).toBeTruthy();
  });
});
