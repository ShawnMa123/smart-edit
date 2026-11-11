/** Task 6.3 — assistant tabs, only the audit one implemented. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AssistantPanel } from './AssistantPanel';
import { initialAuditState } from '../auditMachine';

const renderPanel = () =>
  render(
    <AssistantPanel
      state={initialAuditState}
      currentDigest="digest-1"
      onRun={vi.fn()}
      onStopWaiting={vi.fn()}
    />,
  );

describe('AssistantPanel', () => {
  it('offers the implemented tabs and marks the others unimplemented', () => {
    renderPanel();

    expect(screen.getByRole('tab', { name: 'Rule audit' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Knowledge Q&A · not implemented/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Automation · not implemented/ })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Legal advice' })).toBeTruthy();
  });

  it('renders the audit panel by default', () => {
    renderPanel();

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
  });

  it('renders no sample answer for an unimplemented tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: /Knowledge Q&A · not implemented/ }));

    expect(screen.getByText(/Knowledge Q&A is not implemented in this build/i)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    // No fabricated answers, findings or citations: nothing from the audit rendering is present.
    expect(document.querySelectorAll('.finding')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /Run spec audit/i })).toBeNull();
  });

  it('returns to the audit panel from an unimplemented tab', async () => {
    renderPanel();

    await userEvent.click(screen.getByRole('tab', { name: /Knowledge Q&A · not implemented/ }));
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