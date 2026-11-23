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
  it('offers audit, knowledge, server automation and legal tabs', () => {
    renderPanel();

    expect(screen.getByRole('tab', { name: 'Rule audit' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Knowledge Q&A' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Automation · server/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Legal advice' })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: /Legal advice · not implemented/ })).toBeNull();
  });

  it('hides the Automation tab for roles without automation.view', () => {
    render(
      <AssistantPanel
        state={initialAuditState}
        currentDigest="digest-1"
        onRun={vi.fn()}
        onStopWaiting={vi.fn()}
        knowledge={knowledge}
        automation={automation}
        legal={legal}
        canUseAutomation={false}
      />,
    );

    expect(screen.queryByRole('tab', { name: /Automation/ })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Rule audit' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Knowledge Q&A' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Legal advice' })).toBeTruthy();
  });

  it('shows short visible labels with the build status as a separate tag', () => {
    renderPanel();

    const automation = screen.getByRole('tab', { name: /Automation · server/ });
    expect(automation.textContent).toContain('Automation');
    expect(automation.textContent).toContain('Server');
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

  it('marks the tab as working while its audit runs', () => {
    render(
      <AssistantPanel
        state={{
          phase: 'running',
          snapshot: { text: '', digest: 'd'.repeat(64), versionId: null, capturedAt: '' },
          startedAt: 0,
        }}
        currentDigest="digest-1"
        onRun={vi.fn()}
        onStopWaiting={vi.fn()}
        knowledge={knowledge}
        automation={automation}
        legal={legal}
      />,
    );

    const audit = screen.getByRole('tab', { name: 'Rule audit · working' });
    expect(audit.getAttribute('aria-busy')).toBe('true');
    expect(audit.textContent).toContain('Working');
    expect(screen.getByTestId('ai-wait')).toBeTruthy();
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
    expect(screen.getByText(/Fixture-backed: answers use synthetic demo sources/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Run spec audit/i })).toBeNull();
  });

  it('renders the automation workbench with Automate first, not a generic placeholder', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: /Automation · server/ }));

    expect(screen.getByRole('tab', { name: 'Automate' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Sandbox' })).toBeTruthy();
    expect(screen.getByTestId('automation-boundary').textContent).toContain('Automate');
    expect(screen.getByTestId('automation-boundary').textContent).toContain('Still not implemented');
    expect(screen.queryByText(/Automation is not implemented in this build/i)).toBeNull();
  });

  it('renders the legal advice surface for the legal tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));

    expect(screen.getByLabelText('Legal question')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeTruthy();
    expect(screen.getByText(/Advisory only/)).toBeTruthy();
    expect(screen.queryByText(/Legal advice is not implemented in this build/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /Run spec audit/i })).toBeNull();
  });

  it('switches to the document check with a scan action', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));

    expect(screen.getByRole('button', { name: 'Scan document' })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /Use web search/i })).toBeTruthy();
    expect(screen.getByTestId('legal-scan-target')).toBeTruthy();
    expect(screen.queryByLabelText('Legal question')).toBeNull();
  });

  it('returns to the audit panel from the legal tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Rule audit' }));

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
  });

  it('renders the legal panel with no verdict when no check has run', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));

    expect(screen.getByTestId('legal-panel')).toBeTruthy();
    expect(screen.getByText(/No legal check has run on this run/i)).toBeTruthy();
    expect(screen.getByText(/Not a legal opinion/i)).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: /Run legal check/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('enables the legal trigger when a document is available', async () => {
    const onRunLegal = vi.fn();
    render(
      <AssistantPanel
        state={initialAuditState}
        currentDigest="digest-1"
        onRun={vi.fn()}
        onStopWaiting={vi.fn()}
        legalState={{ phase: 'idle' }}
        canRunLegal
        onRunLegal={onRunLegal}
      />,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));
    await userEvent.click(screen.getByRole('button', { name: /Run legal check/i }));

    expect(onRunLegal).toHaveBeenCalledTimes(1);
  });

  it('states that the assistant does not approve', () => {
    renderPanel();

    expect(screen.getByText(/does not approve or submit/i)).toBeTruthy();
  });
});
