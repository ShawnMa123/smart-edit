/** Template audit panel: config select, pinned review, honest results, redaction steps. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import {
  type ConformanceClient,
  type ConformanceConfigDetail,
  type ConformanceConfigSummary,
  type ConformanceReport,
  type ConformanceRun,
} from '../api/conformance';
import { ConformancePanel } from './ConformancePanel';

const CONFIG: ConformanceConfigSummary = {
  config_id: 'guarantee-standard',
  version: '1.0.0',
  name: 'Demand guarantee — standard desk check',
  document_types: ['guarantee'],
  language: 'auto',
  description: 'Desk check',
  requirement_count: 2,
  required_fields: ['applicant_name', 'guarantee_amount'],
  content_sha256: 'c'.repeat(64),
};

const DETAIL: ConformanceConfigDetail = {
  ...CONFIG,
  extraction_profile: 'guarantee-default',
  generation: { chunk_chars: 6000, max_document_chars: 24000 },
  requirements: [
    {
      id: 'rules.urdg_758',
      title: 'Governing rules are URDG 758',
      level: 'must',
      check: 'The text must name URDG 758 explicitly.',
      evidence_hint: 'Governing rules line',
      suggestion: 'Add "This guarantee is subject to URDG 758".',
    },
  ],
};

const run = (over: Partial<ConformanceRun> = {}): ConformanceRun => ({
  run_id: 'cfr_1',
  status: 'queued',
  stage: 'queued',
  created_at: '2026-11-22T10:00:00Z',
  finished_at: null,
  report_id: 'crp_1',
  error: null,
  progress: { stage: 'queued' },
  ...over,
});

const report = (over: Partial<ConformanceReport> = {}): ConformanceReport => ({
  report_id: 'crp_1',
  run_id: 'cfr_1',
  outcome: 'findings_present',
  completion: 'complete',
  config: CONFIG,
  snapshot: {
    document_id: 'doc-1',
    draft_id: 'draft-1',
    title: 'Demand guarantee',
    revision: 3,
    content_sha256: 'a'.repeat(64),
    analyzed_chars: 420,
    truncated: false,
  },
  summary: 'The document names URDG 758 but omits the applicant legal name.',
  summary_note: "The summary is model-written. 'Pass' means the quoted text meets that requirement.",
  results: [
    {
      id: 'parties.legal_names',
      title: 'Applicant and beneficiary are complete legal names',
      level: 'must',
      status: 'finding',
      severity: 'Warning',
      gate_type: 'human_review',
      explanation: 'The applicant is written as an abbreviation.',
      suggestion: 'Use the registered name.',
      quote: 'Applicant: Atlas',
      block_index: 2,
      confidence: 'high',
      reason_codes: [],
    },
    {
      id: 'rules.urdg_758',
      title: 'Governing rules are URDG 758',
      level: 'must',
      status: 'pass',
      severity: 'Warning',
      gate_type: 'human_review',
      explanation: 'Present.',
      suggestion: null,
      quote: 'Governing Rules: URDG 758',
      block_index: 7,
      confidence: 'high',
      reason_codes: [],
    },
  ],
  missing_fields: [
    { key: 'guarantee_amount', label: 'Guarantee amount', note: 'Not found in this revision.' },
  ],
  counts: {
    requirements: 2,
    passed: 1,
    findings: 1,
    unable_to_assess: 0,
    missing_fields: 1,
    coverage_ratio: 1,
  },
  limitations: [],
  provenance: {
    model: 'doubao:test-model',
    prompt_version: 'conformance/1',
    config_sha256: 'c'.repeat(64),
    extraction_status: 'deterministic',
    extraction_profile: 'guarantee-default',
    model_calls: 1,
    duration_ms: 1200,
    redaction: {
      applied: true,
      total: 2,
      note: 'Best-effort pattern redaction.',
      steps: [{ kind: 'email', count: 2, sample: 'o•••@example.com' }],
    },
  },
  ...over,
});

const makeClient = (over: Partial<ConformanceClient> = {}): ConformanceClient => ({
  listConfigs: vi.fn(async () => [CONFIG]) as unknown as ConformanceClient['listConfigs'],
  getConfig: vi.fn(async () => DETAIL) as unknown as ConformanceClient['getConfig'],
  submitReview: vi.fn(async () => run()) as unknown as ConformanceClient['submitReview'],
  getRun: vi.fn(async () =>
    run({ status: 'succeeded', stage: 'done', report_id: 'crp_1' }),
  ) as unknown as ConformanceClient['getRun'],
  getReport: vi.fn(async () => report()) as unknown as ConformanceClient['getReport'],
  ...over,
});

const renderPanel = (client: ConformanceClient, over: Record<string, unknown> = {}) =>
  render(
    <ConformancePanel
      documentId="doc-1"
      workspaceId="ws_demo_01"
      draftId="draft-1"
      revision={3}
      contentSha={'a'.repeat(64)}
      client={client}
      pollIntervalMs={1}
      {...over}
    />,
  );

describe('ConformancePanel', () => {
  it('loads configs, pins the draft and renders the report', async () => {
    const client = makeClient();
    renderPanel(client, { onJumpToBlock: vi.fn() });

    await screen.findByRole('option', { name: /standard desk check/i });
    await userEvent.click(screen.getByTestId('conformance-run'));

    await screen.findByTestId('conformance-report');
    expect(client.submitReview).toHaveBeenCalledWith(
      expect.objectContaining({
        document_id: 'doc-1',
        draft_id: 'draft-1',
        expected_revision: 3,
        expected_content_sha256: 'a'.repeat(64),
        config_id: 'guarantee-standard',
      }),
    );

    expect(screen.getByTestId('conformance-outcome').textContent).toContain('Findings');
    expect(screen.getByTestId('conformance-outcome').textContent).toContain('100% coverage');
    expect(screen.getByTestId('conformance-missing').textContent).toContain('Guarantee amount');
    expect(screen.getByTestId('conformance-finding').textContent).toContain(
      'Applicant: Atlas',
    );
    expect(screen.getByTestId('conformance-redaction').textContent).toContain(
      'o•••@example.com',
    );
    const provenance = screen.getByTestId('conformance-provenance').textContent ?? '';
    expect(provenance).toContain('AI ·');
    // The UI never names the backend model vendor.
    expect(provenance).not.toContain('doubao:test-model');
  });

  it('marks a report stale when the draft moved on', async () => {
    const client = makeClient();
    renderPanel(client, { revision: 4 });

    await screen.findByRole('option', { name: /standard desk check/i });
    await userEvent.click(screen.getByTestId('conformance-run'));

    const stale = await screen.findByTestId('conformance-stale');
    expect(stale.textContent).toContain('draft rev 3');
  });

  it('shows an unavailable model as unable to assess, never as a pass', async () => {
    const unavailable = report({
      outcome: 'unable_to_assess',
      completion: 'partial',
      results: [
        {
          id: 'rules.urdg_758',
          title: 'Governing rules are URDG 758',
          level: 'must',
          status: 'unable_to_assess',
          severity: 'Warning',
          gate_type: 'human_review',
          explanation: 'This requirement was not assessed.',
          suggestion: null,
          quote: null,
          block_index: null,
          confidence: 'low',
          reason_codes: ['composer_unavailable'],
        },
      ],
      counts: {
        requirements: 1,
        passed: 0,
        findings: 0,
        unable_to_assess: 1,
        missing_fields: 0,
        coverage_ratio: 0,
      },
      limitations: [
        { code: 'composer_unavailable', message: 'No approved model answered.' },
      ],
    });
    const client = makeClient({
      getReport: vi.fn(async () => unavailable) as unknown as ConformanceClient['getReport'],
    });
    renderPanel(client);

    await screen.findByRole('option', { name: /standard desk check/i });
    await userEvent.click(screen.getByTestId('conformance-run'));

    await screen.findByTestId('conformance-report');
    expect(screen.getByTestId('conformance-outcome').textContent).toContain('Unable to assess');
    expect(screen.getByTestId('conformance-unable').textContent).toContain(
      'composer_unavailable',
    );
    expect(screen.getByTestId('conformance-limitations').textContent).toContain(
      'No approved model answered.',
    );
  });

  it('warns about unsaved edits and offers Save', async () => {
    const client = makeClient();
    const onSave = vi.fn();
    renderPanel(client, { dirty: true, saveState: 'saving', onSave });

    const notice = await screen.findByTestId('conformance-dirty');
    expect(notice.textContent).toContain('saved revision 3');
    await userEvent.click(screen.getByRole('button', { name: 'Save now' }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('reports a failed run with its error code', async () => {
    const client = makeClient({
      getRun: vi.fn(async () =>
        run({ status: 'failed', stage: 'failed', error: 'stale_snapshot' }),
      ) as unknown as ConformanceClient['getRun'],
    });
    renderPanel(client);

    await screen.findByRole('option', { name: /standard desk check/i });
    await userEvent.click(screen.getByTestId('conformance-run'));

    const error = await screen.findByTestId('conformance-error');
    expect(error.textContent).toContain('stale_snapshot');
  });

  it('disables the action in demo mode without a server draft', async () => {
    const client = makeClient();
    renderPanel(client, { demoMode: true });

    expect((screen.getByTestId('conformance-run') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('conformance-demo')).toBeTruthy();
    await waitFor(() => expect(client.listConfigs).not.toHaveBeenCalled());
  });

  it('shows the read-only config inspector with its requirements', async () => {
    const client = makeClient();
    renderPanel(client);

    const detail = await screen.findByTestId('conformance-config-detail');
    expect(detail.textContent).toContain('Governing rules are URDG 758');
    expect(detail.textContent).toContain('guarantee-default');
    expect(detail.textContent).toContain('Read-only');
    expect(client.getConfig).toHaveBeenCalledWith('guarantee-standard');
  });

  it('copies the report as Markdown and can print it', async () => {
    const writeText = vi.fn(async (_text: string) => undefined);
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    const print = vi.fn();
    vi.stubGlobal('print', print);

    const client = makeClient();
    renderPanel(client);
    await screen.findByRole('option', { name: /standard desk check/i });
    await userEvent.click(screen.getByTestId('conformance-run'));
    await screen.findByTestId('conformance-report');

    await userEvent.click(screen.getByTestId('conformance-copy'));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = String(writeText.mock.calls[0][0]);
    expect(text).toContain('# Template audit');
    expect(text).toContain('## Does not match the config');
    expect(await screen.findByText('Copied')).toBeTruthy();

    await userEvent.click(screen.getByTestId('conformance-print'));
    expect(print).toHaveBeenCalled();
  });

  it('compares the result with the previous audit of the same document and config', async () => {
    globalThis.localStorage?.setItem(
      'smart-edit:conformance:last:doc-1:guarantee-standard',
      JSON.stringify({
        at: '2026-11-21T10:00:00Z',
        outcome: 'findings_present',
        findings: 3,
        missing: 0,
        coverage: 1,
        revision: 2,
      }),
    );
    const client = makeClient();
    renderPanel(client);

    await screen.findByRole('option', { name: /standard desk check/i });
    await userEvent.click(screen.getByTestId('conformance-run'));

    const delta = await screen.findByTestId('conformance-delta');
    expect(delta.textContent).toContain('findings -2');
    expect(delta.textContent).toContain('missing fields +1');
    expect(delta.textContent).toContain('coverage 0 pts');
  });
});