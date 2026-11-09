/** Tasks 7.1-7.7 — the audit panel states. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AuditPanel, type AuditPanelProps } from './AuditPanel';
import type { AuditState } from '../auditMachine';
import { explainError } from '../api/errors';
import type { RunEnvelope } from '../api/types';
import type { Snapshot } from '../snapshot';
import {
  NO_PROVIDER_REASON,
  ambiguousTemplateEnvelope,
  auditedEnvelope,
  blockedAuditEnvelope,
  doneEnvelope,
  envelope,
  findingsEnvelope,
  noProviderEnvelope,
  stage,
  templatedEnvelope,
} from '../test/fixtures';

const snapshot = (digest = 'digest-1'): Snapshot => ({
  text: 'document',
  digest,
  versionId: null,
  capturedAt: '2026-11-08T09:00:00.000Z',
});

const renderPanel = (
  state: AuditState,
  currentDigest = 'digest-1',
  now = 0,
  extra: Partial<AuditPanelProps> = {},
) => {
  const onRun = vi.fn();
  const onStopWaiting = vi.fn();
  render(
    <AuditPanel
      {...extra}
      state={state}
      currentDigest={currentDigest}
      onRun={onRun}
      onStopWaiting={onStopWaiting}
      now={now}
    />,
  );
  return { onRun, onStopWaiting };
};

const providerEnvelope = () =>
  envelope({
    fields: doneEnvelope().fields,
    stages: [stage({ stage: 'parse' }), stage({ stage: 'extract' }), stage({ stage: 'normalize' })],
  });

describe('idle state (7.1)', () => {
  it('discloses the audit scope without opening anything', () => {
    renderPanel({ phase: 'idle' });

    expect(screen.getByText('What this audit checks')).toBeTruthy();
    expect(screen.getByText(/Not checked in this build/i)).toBeTruthy();
    expect(screen.getByText(/Semantic consistency checks/i)).toBeTruthy();
  });

  it('starts a run when asked', async () => {
    const { onRun } = renderPanel({ phase: 'idle' });

    await userEvent.click(screen.getByRole('button', { name: /Run spec audit/i }));

    expect(onRun).toHaveBeenCalled();
  });
});

describe('running state (7.2)', () => {
  it('shows the frozen snapshot, elapsed time and a wait-cancel', () => {
    renderPanel(
      { phase: 'running', snapshot: snapshot('abcdef1234567890'), startedAt: 1_000 },
      'digest-1',
      2_500,
    );

    expect(screen.getByText(/Fixed snapshot captured/i)).toBeTruthy();
    expect(screen.getByText('abcdef123456')).toBeTruthy();
    expect(screen.getByText(/1\.5s elapsed/)).toBeTruthy();
    expect(screen.getByText(/only stops waiting here/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Stop waiting/i })).toBeTruthy();
  });
});

describe('failed state (7.3)', () => {
  it('explains a refusal from its code and offers a retry', () => {
    renderPanel({
      phase: 'failed',
      failure: { code: 'REFUSED', message: 'missing prerequisite keys' },
      elapsedMs: 1_200,
      snapshot: snapshot(),
    });

    expect(screen.getByRole('alert').textContent).toContain(explainError('REFUSED'));
    expect(screen.getByText(/Code/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Run spec audit again/i })).toBeTruthy();
    expect(screen.queryByText(/No findings in the checks that ran/i)).toBeNull();
  });

  it('reports a timeout as a failure, with elapsed time', () => {
    renderPanel({
      phase: 'failed',
      failure: { code: 'TIMEOUT', message: 'request aborted after 120000 ms' },
      elapsedMs: 120_000,
      snapshot: snapshot(),
    });

    expect(screen.getByRole('alert').textContent).toContain('120 second limit');
    expect(screen.getByText(/120\.0s/)).toBeTruthy();
    expect(screen.queryByText(/Checks ran/i)).toBeNull();
  });
});

describe('report state (7.4)', () => {
  it('renders the stage strip, checks, counts and the audited digest', () => {
    renderPanel({
      phase: 'report',
      envelope: doneEnvelope(),
      snapshot: snapshot('abcdef1234567890'),
      completedAt: 2_000,
    });

    expect(screen.getAllByText('Done')).toHaveLength(3);
    expect(screen.getAllByText(/fixture:fixtures\/llm\/extract_sample\.json/).length).toBeGreaterThan(0);
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByText('Not found in source')).toBeTruthy();
    expect(screen.getByText('Inferred · needs confirmation')).toBeTruthy();
    expect(screen.getByText('not_in_source')).toBeTruthy();
    expect(screen.getByText('value_truncated')).toBeTruthy();
    expect(screen.getAllByText('abcdef123456').length).toBeGreaterThan(0);
    expect(screen.getByText(/No findings does not mean the document is compliant/i)).toBeTruthy();
  });

  it('never labels a clean run as a pass', () => {
    renderPanel({
      phase: 'report',
      envelope: doneEnvelope(),
      snapshot: snapshot(),
      completedAt: 2_000,
    });

    expect(screen.getByText(/No findings in the checks that ran/i)).toBeTruthy();
    expect(screen.queryByText(/^pass$/i)).toBeNull();
  });

  it('lists findings with severity, evidence and field keys', () => {
    renderPanel({
      phase: 'report',
      envelope: findingsEnvelope(),
      snapshot: snapshot(),
      completedAt: 2_000,
    });

    expect(screen.getByText(/N-001/)).toBeTruthy();
    expect(screen.getByText('Warning')).toBeTruthy();
    expect(screen.getByText('Critical')).toBeTruthy();
    expect(screen.getAllByText(/evidence:/).length).toBeGreaterThan(0);
    expect(screen.getByText(/fields: applicant_name/)).toBeTruthy();
  });

  it('reports a failed extraction as "did not run" with no defect list', () => {
    renderPanel({
      phase: 'report',
      envelope: noProviderEnvelope(),
      snapshot: snapshot(),
      completedAt: 2_000,
    });

    expect(screen.getByRole('alert').textContent).toContain('Field checks did not run');
    expect(screen.getByRole('alert').textContent).toContain(NO_PROVIDER_REASON);
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('does not treat a partial extraction as a completed check', () => {
    renderPanel({
      phase: 'report',
      envelope: envelope({
        fields: doneEnvelope().fields,
        stages: [
          stage({ stage: 'parse' }),
          stage({ stage: 'extract', status: 'partial', reason: '1 batch(es) failed' }),
          stage({ stage: 'normalize' }),
        ],
      }),
      snapshot: snapshot(),
      completedAt: 2_000,
    });

    expect(screen.getAllByRole('alert')[0].textContent).toContain('Field checks did not run');
    expect(screen.queryByRole('table')).toBeNull();
  });
});

describe('stale state (7.5)', () => {
  it('marks the report stale but keeps its findings readable', () => {
    renderPanel(
      { phase: 'report', envelope: findingsEnvelope(), snapshot: snapshot('digest-1'), completedAt: 2_000 },
      'a-different-current-digest',
    );

    const alerts = screen.getAllByRole('alert').map((node) => node.textContent ?? '');
    expect(alerts.some((text) => text.includes('Report is stale'))).toBe(true);
    expect(alerts.some((text) => text.includes('cannot be used for approval'))).toBe(true);
    expect(screen.getByText(/N-001/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Re-audit current snapshot/i })).toBeTruthy();
  });
});

describe('fixture banner (7.6)', () => {
  it('names the fixture used for the candidates', () => {
    renderPanel({
      phase: 'report',
      envelope: doneEnvelope(),
      snapshot: snapshot(),
      completedAt: 2_000,
    });

    expect(screen.getByText('Fixture-backed run')).toBeTruthy();
    expect(screen.getByText(/not from a model provider/i)).toBeTruthy();
  });

  it('stays quiet for a provider-backed run', () => {
    renderPanel({
      phase: 'report',
      envelope: providerEnvelope(),
      snapshot: snapshot(),
      completedAt: 2_000,
    });

    expect(screen.queryByText('Fixture-backed run')).toBeNull();
  });
});

describe('rule audit block (agent-audit verification)', () => {
  const reportState = (envelopeValue: ReturnType<typeof auditedEnvelope>) => ({
    phase: 'report' as const,
    envelope: envelopeValue,
    snapshot: snapshot(),
    completedAt: 2_000,
  });

  it('says the rule audit did not run when there is no report', () => {
    renderPanel(reportState(doneEnvelope()));

    expect(screen.getByText('Rule audit did not run')).toBeTruthy();
    expect(screen.queryByText(/planned checks assessed/i)).toBeNull();
  });

  it('shows the plan, the assessed count and the coverage ratio', () => {
    renderPanel(reportState(auditedEnvelope()));

    expect(screen.getByText(/33 of 51 planned checks assessed/)).toBeTruthy();
    expect(screen.getByText(/ratio 0\.647/)).toBeTruthy();
    expect(screen.getByText('No findings reported')).toBeTruthy();
    expect(screen.getByText(/guarantee-core v1\.0\.0/)).toBeTruthy();
  });

  it('never renders an unasked gate as allowed', () => {
    renderPanel(reportState(auditedEnvelope()));

    expect(screen.getByText('Not asked')).toBeTruthy();
    expect(screen.getByText(/nothing is allowed/i)).toBeTruthy();
    expect(screen.queryByText('Allowed')).toBeNull();
  });

  it('lists the audited findings with their gate type and blocks the gate', () => {
    renderPanel(reportState(blockedAuditEnvelope()));

    expect(screen.getByText('Findings reported')).toBeTruthy();
    expect(screen.getByText('Blocked')).toBeTruthy();
    expect(screen.getByText(/start_approval · reasons hard_block/)).toBeTruthy();
    expect(screen.getByText(/B-001/)).toBeTruthy();
    expect(screen.getByText(/gate: hard_block/)).toBeTruthy();
    expect(screen.getByText(/→ start_approval, formal_export, handoff/)).toBeTruthy();
  });
});

describe('template block (agent-audit verification.audit.template)', () => {
  const reportState = (envelopeValue: ReturnType<typeof auditedEnvelope>) => ({
    phase: 'report' as const,
    envelope: envelopeValue,
    snapshot: snapshot(),
    completedAt: 2_000,
  });

  it('offers an optional template field before the run', async () => {
    const onTemplateChange = vi.fn();
    render(
      <AuditPanel
        state={{ phase: 'idle' }}
        currentDigest="digest-1"
        onRun={vi.fn()}
        onStopWaiting={vi.fn()}
        templateId=""
        onTemplateChange={onTemplateChange}
      />,
    );

    await userEvent.type(screen.getByLabelText('Customer template'), 'adidas');

    expect(onTemplateChange).toHaveBeenCalled();
  });

  it('says a synthetic pack is synthetic and counts its units', () => {
    renderPanel(reportState(templatedEnvelope()));

    expect(screen.getByText('Synthetic template · adidas-guarantee v1.0.0')).toBeTruthy();
    expect(screen.getByText(/not a real customer contract/)).toBeTruthy();
    expect(screen.getByText(/2 template units/)).toBeTruthy();
    expect(screen.getByText(/counterparty Adidas AG/)).toBeTruthy();
  });

  it('explains an ambiguous template instead of picking one', () => {
    renderPanel(reportState(ambiguousTemplateEnvelope()));

    expect(screen.getByText('Template could not be resolved')).toBeTruthy();
    expect(screen.getByText(/reason: ambiguous_template/)).toBeTruthy();
    expect(
      screen.getByText(/adidas-guarantee v1\.0\.0, adidas-guarantee-second v2\.0\.0/),
    ).toBeTruthy();
    expect(screen.queryByText(/Synthetic template/)).toBeNull();
  });
});

describe('gate and disposition controls (agent4 audit)', () => {
  const report = (envelopeValue: RunEnvelope) => ({
    phase: 'report' as const,
    envelope: envelopeValue,
    snapshot: snapshot(),
    completedAt: 2_000,
  });

  it('asks the selected operation', async () => {
    const onAskGate = vi.fn();
    renderPanel(report(auditedEnvelope()), 'digest-1', 0, { onAskGate });

    await userEvent.selectOptions(screen.getByLabelText('Gate operation'), 'save_draft');
    await userEvent.click(screen.getByTestId('gate-ask'));

    expect(onAskGate).toHaveBeenCalledWith('save_draft');
  });

  it('refuses to reject a critical finding without a reason', async () => {
    const onDispose = vi.fn();
    renderPanel(report(findingsEnvelope()), 'digest-1', 0, { onDispose });

    await userEvent.click(screen.getByRole('button', { name: 'Reject N-002' }));

    expect(onDispose).not.toHaveBeenCalled();
    expect(screen.getByTestId('gate-action-error').textContent).toContain(
      'A reason is required',
    );

    await userEvent.type(screen.getByLabelText('Reason for N-002'), 'vendor will resend');
    await userEvent.click(screen.getByRole('button', { name: 'Reject N-002' }));

    expect(onDispose).toHaveBeenCalledWith(
      'N-002',
      'rejected',
      'vendor will resend',
      'start_approval',
    );
  });
});

describe('accessibility (7.7)', () => {
  it('gives every status chip a text label', () => {
    const { container } = render(
      <AuditPanel
        state={{ phase: 'report', envelope: findingsEnvelope(), snapshot: snapshot(), completedAt: 1 }}
        currentDigest="digest-1"
        onRun={vi.fn()}
        onStopWaiting={vi.fn()}
      />,
    );

    const chips = Array.from(container.querySelectorAll('.status'));
    expect(chips.length).toBeGreaterThan(0);
    for (const chip of chips) {
      expect((chip.textContent ?? '').trim().length).toBeGreaterThan(0);
    }
  });
});