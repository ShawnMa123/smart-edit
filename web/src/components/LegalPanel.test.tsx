/** LegalPanel: statute advice (question scope) and the draft document scan. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { LegalPanel } from './LegalPanel';
import type { Finding, ReviewReport, ReviewRun } from '../api/legal';

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    finding_id: 'lf_1',
    check_id: 'LEGAL:element:amount',
    method: 'deterministic',
    category: 'element',
    severity: 'Critical',
    gate_type: 'hard_block',
    target_operations: ['start_approval'],
    title: 'Missing guarantee / contract amount',
    explanation: 'The draft does not mention the amount.',
    anchors: [],
    document_anchors: [],
    suggestion: 'Add the amount with its currency.',
    basis: 'rule',
    rule_refs: [{ rule_id: 'LEGAL-AMOUNT', version: '1' }],
    evidence_ids: [],
    applicability: { jurisdictions: [], assessment_date: '2026-11-20', limitations: [] },
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
    completion: 'partial',
    outcome: 'findings_present',
    findings: [makeFinding()],
    coverage: [
      {
        check_id: 'LEGAL:element:amount',
        method: 'deterministic',
        scope_key: 'document',
        status: 'finding',
        rule_refs: [{ rule_id: 'LEGAL-AMOUNT', version: '1' }],
        reason_codes: ['element_missing'],
        finding_ids: ['lf_1'],
        missing_facts: [],
      },
      {
        check_id: 'LEGAL:clause:clause-01:statute',
        method: 'legal',
        scope_key: 'clause-01',
        status: 'unable_to_assess',
        rule_refs: [],
        reason_codes: ['composer_unavailable'],
        finding_ids: [],
        missing_facts: [],
        clause_id: 'clause-01',
        evidence_count: 2,
      },
    ],
    limitations: [{ code: 'truncated', message: 'Only the first 12 clauses were scanned.' }],
    snapshot: { document_id: 'doc-1', revision: 3, content_sha256: 'abcdef1234567890' },
    coverage_summary: {
      planned: 4,
      settled: 2,
      assessed: 2,
      assessed_ratio: 0.5,
      by_status: { finding: 1, unable_to_assess: 2, pass: 1 },
      clauses: 2,
      truncated: false,
    },
    retrieval: { queries: 2, hits: 3, web_requested: false, web_used: false, web_calls: 0 },
    gate: {
      status: 'blocked',
      reasons: ['hard_block_finding', 'limited_coverage'],
      coverage_ratio: 0.5,
      policy: 'legal-scan/1',
    },
    ...overrides,
  };
}

function makeRun(overrides: Partial<ReviewRun> = {}): ReviewRun {
  return {
    run_id: 'run_1',
    status: 'succeeded',
    stage: 'done',
    created_at: '2026-11-20T00:00:00Z',
    deadline_at: '2026-11-20T00:02:00Z',
    report_id: 'rep_1',
    error: null,
    finished_at: '2026-11-20T00:00:01Z',
    progress: { stage: 'done', planned: 4, done: 4 },
    ...overrides,
  };
}

function documentClient(report = makeReport()) {
  return {
    submitReview: vi.fn().mockResolvedValue(
      makeRun({ status: 'queued', report_id: 'rep_1', progress: { stage: 'queued' } }),
    ),
    getRun: vi.fn().mockResolvedValue(makeRun()),
    getReport: vi.fn().mockResolvedValue(report),
  };
}

describe('LegalPanel · statute advice', () => {
  it('asks the statute service and renders the answer with citations', async () => {
    const submitReview = vi.fn().mockResolvedValue(makeRun());
    const getReport = vi.fn().mockResolvedValue(
      makeReport({
        findings: [
          makeFinding({
            method: 'legal',
            basis: 'statute',
            support_level: 'strong',
            severity: 'Warning',
            gate_type: 'human_review',
            title: 'Amount clause',
            explanation: '该情形下应依据第 12 条办理。',
            anchors: [{ chunk_id: 'chunk_1', article_label: '第十二条', title: 'URDG 758' }],
          }),
        ],
      }),
    );
    render(<LegalPanel documentId="doc-1" client={{ submitReview, getReport }} />);

    await userEvent.click(screen.getByRole('button', { name: '银行保函的金额条款有哪些法律要求？' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    await waitFor(() => expect(screen.getByText('Amount clause')).toBeTruthy());
    expect(screen.getByText('Strong support')).toBeTruthy();
    expect(screen.getByText('第十二条')).toBeTruthy();
    expect(submitReview).toHaveBeenCalledWith(
      expect.objectContaining({ modes: ['legal'], question: '银行保函的金额条款有哪些法律要求？' }),
      expect.anything(),
    );
  });
});

describe('LegalPanel · document check', () => {
  it('pins the draft revision, polls the run and renders coverage, gate and anchors', async () => {
    const client = documentClient(
      makeReport({
        findings: [
          makeFinding({
            document_anchors: [
              {
                clause_id: 'clause-02',
                block_index: 4,
                start_cp: 120,
                end_cp: 144,
                quote: 'The guarantee will be automatically extended',
              },
            ],
          }),
        ],
      }),
    );
    const onJumpToBlock = vi.fn();
    render(
      <LegalPanel
        documentId="doc-1"
        revision={3}
        contentSha="abcdef1234567890"
        client={client}
        onJumpToBlock={onJumpToBlock}
      />,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    expect(screen.getByTestId('legal-scan-target').textContent).toContain('rev 3');
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() => expect(screen.getByText('Missing guarantee / contract amount')).toBeTruthy());

    expect(client.submitReview).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: 'document',
        modes: ['deterministic', 'legal'],
        expected_revision: 3,
        expected_content_sha256: 'abcdef1234567890',
        web_search: false,
      }),
      expect.anything(),
    );
    expect(client.getRun).toHaveBeenCalledWith('run_1', expect.anything());
    expect(screen.getByTestId('legal-coverage-summary').textContent).toContain('Planned 4');
    expect(screen.getByText('Gate: Blocked')).toBeTruthy();
    expect(screen.getByText(/A blocking finding must be fixed first/)).toBeTruthy();
    expect(screen.getByText(/Only the first 12 clauses were scanned/)).toBeTruthy();
    expect(screen.getByText('clause-02')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Jump to clause' }));
    expect(onJumpToBlock).toHaveBeenCalledWith(4);
  });

  it('keeps the web leg off unless the operator switches it on', async () => {
    const client = documentClient(makeReport({ findings: [], outcome: 'unable_to_assess' }));
    render(<LegalPanel documentId="doc-1" revision={3} client={client} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    const toggle = screen.getByRole('checkbox', { name: /Use web search/i });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() =>
      expect(client.submitReview).toHaveBeenCalledWith(
        expect.objectContaining({ web_search: true }),
        expect.anything(),
      ),
    );
  });

  it('surfaces a failed run instead of rendering an empty report', async () => {
    const client = {
      submitReview: vi.fn().mockResolvedValue(
        makeRun({ status: 'queued', report_id: 'rep_1' }),
      ),
      getRun: vi
        .fn()
        .mockResolvedValue(
          makeRun({ status: 'failed', report_id: 'rep_1', error: 'stale_snapshot' }),
        ),
      getReport: vi.fn(),
    };
    render(<LegalPanel documentId="doc-1" revision={3} client={client} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(client.getReport).not.toHaveBeenCalled();
  });

  it('warns that a report predates the draft on screen', async () => {
    const client = documentClient(
      makeReport({ snapshot: { document_id: 'doc-1', revision: 1, content_sha256: 'old' } }),
    );
    render(<LegalPanel documentId="doc-1" revision={3} client={client} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() =>
      expect(screen.getByText(/The draft changed since this scan/)).toBeTruthy(),
    );
  });

  it('saves unsaved editor changes before scanning so the scan covers the text on screen', async () => {
    // The panel's props still pin rev 3, but the pre-scan save lands rev 4: the scan must use the
    // saved result, otherwise the backend scans the older (possibly empty) revision silently.
    const client = documentClient(
      makeReport({ snapshot: { document_id: 'doc-1', revision: 4, content_sha256: 'fresh-sha' } }),
    );
    const onBeforeScan = vi.fn().mockResolvedValue({ revision: 4, contentSha: 'fresh-sha' });
    render(
      <LegalPanel
        documentId="doc-1"
        revision={3}
        contentSha="abcdef1234567890"
        dirty
        onBeforeScan={onBeforeScan}
        client={client}
      />,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    expect(screen.getByTestId('legal-dirty').textContent).toContain('saved first');
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() => expect(onBeforeScan).toHaveBeenCalledTimes(1));
    expect(client.submitReview).toHaveBeenCalledWith(
      expect.objectContaining({ expected_revision: 4, expected_content_sha256: 'fresh-sha' }),
      expect.anything(),
    );
    await waitFor(() =>
      expect(screen.getByTestId('legal-scan-target').textContent).toContain('rev 4'),
    );
    expect(screen.queryByText(/The draft changed since this scan/)).toBeNull();
  });

  it('refuses to scan a saved revision that is behind unsaved editor changes', async () => {
    const client = documentClient();
    render(<LegalPanel documentId="doc-1" revision={3} dirty client={client} />);

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    const button = screen.getByRole('button', { name: 'Scan document' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId('legal-dirty').textContent).toContain('save the draft first');
    expect(client.submitReview).not.toHaveBeenCalled();
  });

  it('names the scanned text and warns when the editor holds different text', async () => {
    const client = documentClient(
      makeReport({
        snapshot: {
          document_id: 'doc-1',
          revision: 3,
          content_sha256: 'abcdef1234567890',
          characters: 267,
          preview: 'DEMAND GUARANTEE Guarantee No: BG-2026-00417',
        },
      }),
    );
    render(
      <LegalPanel
        documentId="doc-1"
        revision={3}
        contentSha="abcdef1234567890"
        editorCharacters={156}
        editorPreview="卖方：Northbridge Arms Trading LLC（美国）"
        client={client}
      />,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    expect(screen.getByTestId('legal-editor-target').textContent).toContain('156 characters');
    expect(screen.getByTestId('legal-editor-target').textContent).toContain('Northbridge');
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() => expect(screen.getByTestId('legal-scanned-snapshot')).toBeTruthy());
    expect(screen.getByTestId('legal-scanned-snapshot').textContent).toContain('267 characters');
    expect(screen.getByTestId('legal-scanned-snapshot').textContent).toContain('DEMAND GUARANTEE');
    expect(screen.getByTestId('legal-scan-mismatch').textContent).toContain(
      'editor currently has 156',
    );
  });

  it('does not scan when the pre-scan save fails', async () => {
    const client = documentClient();
    const onBeforeScan = vi.fn().mockResolvedValue(null);
    render(
      <LegalPanel
        documentId="doc-1"
        revision={3}
        dirty
        onBeforeScan={onBeforeScan}
        client={client}
      />,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    await userEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.getByRole('alert').textContent).toContain('could not be saved');
    expect(client.submitReview).not.toHaveBeenCalled();
  });
});