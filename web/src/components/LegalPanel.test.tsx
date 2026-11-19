/** LegalPanel: deterministic rule check renders the three fact-state outcomes. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { LegalPanel } from './LegalPanel';
import type { Finding, ReviewReport, ReviewRun } from '../api/legal';

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    finding_id: 'lf_1',
    check_id: 'check_demo_amount_required',
    method: 'deterministic',
    category: 'field',
    severity: 'Critical',
    gate_type: 'hard_block',
    target_operations: ['start_approval'],
    title: 'Missing amount',
    explanation: 'The synthetic template requires an amount before approval.',
    anchors: [],
    rule_refs: [{ rule_id: 'DEMO-AMOUNT-REQUIRED', version: '1' }],
    evidence_ids: [],
    applicability: {
      jurisdictions: [],
      assessment_date: '2026-11-20',
      conditions: [],
      limitations: ['Missing field has no text anchor'],
    },
    support_level: 'not_applicable',
    disposition: 'open',
    version: 1,
    ...overrides,
  };
}

function makeReport(overrides: Partial<ReviewReport> = {}): ReviewReport {
  return {
    report_id: 'rep_1',
    run_id: 'run_1',
    completion: 'complete',
    outcome: 'findings_present',
    findings: [makeFinding()],
    coverage: [
      {
        check_id: 'check_demo_amount_required',
        method: 'deterministic',
        scope_key: 'template',
        status: 'finding',
        rule_refs: [{ rule_id: 'DEMO-AMOUNT-REQUIRED', version: '1' }],
        reason_codes: ['rule_violated'],
        finding_ids: ['lf_1'],
        missing_facts: [],
      },
    ],
    limitations: [],
    ...overrides,
  };
}

function makeRun(): ReviewRun {
  return {
    run_id: 'run_1',
    status: 'succeeded',
    stage: 'done',
    created_at: '2026-11-20T00:00:00Z',
    deadline_at: '2026-11-20T00:02:00Z',
    report_id: 'rep_1',
    error: null,
    finished_at: '2026-11-20T00:00:01Z',
  };
}

describe('LegalPanel', () => {
  it('runs the deterministic rule and renders a Critical finding for a missing amount', async () => {
    const submitReview = vi.fn().mockResolvedValue(makeRun());
    const getReport = vi.fn().mockResolvedValue(makeReport());
    render(<LegalPanel documentId="doc-1" client={{ submitReview, getReport }} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Rule check' }));
    await userEvent.click(screen.getByRole('button', { name: 'Amount missing' }));

    await waitFor(() => expect(screen.getByText('Missing amount')).toBeTruthy());
    expect(screen.getByText('Critical')).toBeTruthy();
    expect(screen.getByText(/DEMO-AMOUNT-REQUIRED v1/)).toBeTruthy();
    expect(submitReview).toHaveBeenCalledWith(
      expect.objectContaining({ modes: ['deterministic'], facts: {} }),
      expect.anything(),
    );
  });

  it('shows the statute advice surface by default', () => {
    render(<LegalPanel documentId="doc-1" client={{ submitReview: vi.fn(), getReport: vi.fn() }} />);

    expect(screen.getByLabelText('Legal question')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeTruthy();
    expect(screen.getByText(/仅供参考/)).toBeTruthy();
  });
});
