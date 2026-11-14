/** Task 5.3 — assistant tabs: knowledge is wired, automation/legal stay labelled. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AssistantPanel } from './AssistantPanel';
import { initialAuditState } from '../auditMachine';

const knowledge = { documentId: 'doc-1', digest: 'a'.repeat(64), text: '保函文本' };

const renderPanel = () =>
  render(
    <AssistantPanel
      state={initialAuditState}
      currentDigest="digest-1"
      onRun={vi.fn()}
      onStopWaiting={vi.fn()}
      knowledge={knowledge}
    />,
  );

describe('AssistantPanel', () => {
  it('offers the audit and knowledge tabs and marks only automation/legal unimplemented', () => {
    renderPanel();

    expect(screen.getByRole('tab', { name: 'Rule audit' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Knowledge Q&A' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Automation · not implemented/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Legal advice · not implemented/ })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: /Knowledge Q&A · not implemented/ })).toBeNull();
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

  it('renders no sample answer for an unimplemented tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: /Automation · not implemented/ }));

    expect(screen.getByText(/Automation is not implemented in this build/i)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(document.querySelectorAll('.finding')).toHaveLength(0);
    expect(screen.queryByLabelText('Knowledge question')).toBeNull();
    expect(screen.queryByRole('button', { name: /Run spec audit/i })).toBeNull();
  });

  it('returns to the audit panel from an unimplemented tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: /Legal advice · not implemented/ }));
    await userEvent.click(screen.getByRole('tab', { name: 'Rule audit' }));

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
  });

  it('states that the assistant does not approve', () => {
    renderPanel();

    expect(screen.getByText(/does not approve or submit/i)).toBeTruthy();
  });
});