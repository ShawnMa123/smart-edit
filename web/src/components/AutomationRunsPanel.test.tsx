/** Runs panel: delivery badge, job list, timeline and the manual fallback buttons. */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AutomationRunsPanel } from './AutomationRunsPanel';
import type { Job, JobDetail, JobsClient } from '../api/automationJobs';

const baseJob: Job = {
  job_id: 'job_sent',
  rule_id: 'rule_erp',
  rule_name: 'ERP rule',
  document_id: 'doc-1',
  document_title: 'Guarantee',
  submission_id: 'sub_1',
  template_id: 'tpl_1',
  connector_id: 'con_erp',
  connector_name: 'ERP',
  status: 'sent',
  mode: 'auto_send',
  required: true,
  attempts: 1,
  next_attempt_at: null,
  error_code: null,
  receipt_id: 'dsp_1',
  request: null,
  response_excerpt: '{"ok": true}',
  created_at: '2026-11-22T00:00:00Z',
  updated_at: '2026-11-22T00:00:01Z',
};

const failedJob: Job = {
  ...baseJob,
  job_id: 'job_failed',
  rule_id: 'rule_core',
  rule_name: 'Core rule',
  connector_id: 'con_core',
  connector_name: 'Core',
  status: 'needs_attention',
  error_code: 'http_409',
};

const reviewJob: Job = {
  ...baseJob,
  job_id: 'job_review',
  rule_id: 'rule_legacy',
  rule_name: 'Legacy rule',
  connector_id: 'con_legacy',
  connector_name: 'Legacy',
  status: 'needs_review',
  mode: 'needs_review',
  attempts: 0,
};

const detail: JobDetail = {
  ...failedJob,
  events: [
    {
      event_id: 'evt_1',
      from_status: null,
      to_status: 'queued',
      detail: {},
      created_at: '2026-11-22T00:00:00Z',
    },
    {
      event_id: 'evt_2',
      from_status: 'queued',
      to_status: 'sending',
      detail: {},
      created_at: '2026-11-22T00:00:01Z',
    },
    {
      event_id: 'evt_3',
      from_status: 'sending',
      to_status: 'needs_attention',
      detail: {},
      created_at: '2026-11-22T00:00:02Z',
    },
  ],
};

const baseClient = () =>
  ({
    listJobs: vi.fn().mockResolvedValue({ items: [baseJob, failedJob, reviewJob] }),
    getJob: vi.fn().mockResolvedValue(detail),
    releaseJob: vi.fn().mockResolvedValue(reviewJob),
    retryJob: vi.fn().mockResolvedValue({ ...failedJob, status: 'queued' }),
    cancelJob: vi.fn().mockResolvedValue({ ...failedJob, status: 'cancelled' }),
    readDocumentDelivery: vi.fn().mockResolvedValue({
      document_id: 'doc-1',
      status: 'needs_attention',
      auto_send_enabled: true,
      skipped_reason: null,
      rows: [
        { ...baseJob, updated_at: baseJob.updated_at },
        { ...failedJob, updated_at: failedJob.updated_at },
      ],
    }),
    readSettings: vi.fn().mockResolvedValue({ auto_send_enabled: true }),
  }) as unknown as JobsClient;

describe('AutomationRunsPanel', () => {
  it('shows the document delivery state and one run per downstream', async () => {
    render(<AutomationRunsPanel documentId="doc-1" client={baseClient()} />);

    const badge = await screen.findByTestId('document-delivery');
    expect(badge.getAttribute('data-status')).toBe('needs_attention');
    expect(badge.textContent).toContain('Needs attention');
    expect(screen.getByRole('columnheader', { name: 'Downstream' })).toBeTruthy();
    const failedRow = screen.getByTestId('delivery-row-job_failed');
    expect(within(failedRow).getByRole('rowheader', { name: 'Core' })).toBeTruthy();
    expect(within(failedRow).getByText('Needs attention')).toBeTruthy();
    expect(within(failedRow).getByText(/Required/)).toBeTruthy();
    const sentRow = screen.getByTestId('delivery-row-job_sent');
    expect(within(sentRow).getByText('Sent')).toBeTruthy();
    expect(screen.getByTestId('run-job_sent').textContent).toContain('Sent');
    expect(screen.getByTestId('run-job_failed').textContent).toContain('Needs attention');
  });

  it('offers retry and release only where the state machine allows them', async () => {
    render(<AutomationRunsPanel documentId="doc-1" client={baseClient()} />);

    await screen.findByTestId('run-job_failed');
    expect(screen.getByTestId('retry-job_failed')).toBeTruthy();
    expect(screen.getByTestId('cancel-job_failed')).toBeTruthy();
    expect(screen.queryByTestId('release-job_failed')).toBeNull();

    expect(screen.getByTestId('release-job_review')).toBeTruthy();
    expect(screen.queryByTestId('retry-job_review')).toBeNull();

    expect(screen.queryByTestId('retry-job_sent')).toBeNull();
    expect(screen.queryByTestId('cancel-job_sent')).toBeNull();
  });

  it('retries a failed job and refreshes the list', async () => {
    const client = baseClient();
    render(<AutomationRunsPanel documentId="doc-1" client={client} />);

    await screen.findByTestId('retry-job_failed');
    await userEvent.click(screen.getByTestId('retry-job_failed'));

    await waitFor(() => expect(client.retryJob).toHaveBeenCalledWith('job_failed'));
    await waitFor(() => expect(client.listJobs).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('status')).toBeTruthy();
  });

  it('releases a needs_review job through the same idempotency key', async () => {
    const client = baseClient();
    render(<AutomationRunsPanel documentId="doc-1" client={client} />);

    await screen.findByTestId('release-job_review');
    await userEvent.click(screen.getByTestId('release-job_review'));

    await waitFor(() => expect(client.releaseJob).toHaveBeenCalledWith('job_review'));
    await waitFor(() => expect(client.listJobs).toHaveBeenCalledTimes(2));
  });

  it('shows the status timeline in the job detail', async () => {
    render(<AutomationRunsPanel documentId="doc-1" client={baseClient()} />);

    await screen.findByTestId('run-job_failed');
    const details = screen.getByTestId('run-job_failed').querySelector('button');
    await userEvent.click(details as HTMLButtonElement);

    const timeline = await screen.findByTestId('run-timeline');
    expect(timeline.textContent).toContain('queued');
    expect(timeline.textContent).toContain('sending → needs_attention');
  });

  it('warns when the global kill switch is off', async () => {
    const client = baseClient();
    (client.readSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      auto_send_enabled: false,
    });
    render(<AutomationRunsPanel documentId="doc-1" client={client} />);

    const banner = await screen.findByTestId('auto-send-switch');
    expect(banner.getAttribute('data-enabled')).toBe('no');
    expect(banner.textContent).toContain('disabled globally');
  });

  it('explains a skipped document instead of showing rows', async () => {
    const client = baseClient();
    (client.listJobs as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
    (client.readDocumentDelivery as ReturnType<typeof vi.fn>).mockResolvedValue({
      document_id: 'doc-1',
      status: 'not_configured',
      auto_send_enabled: true,
      skipped_reason: 'no_binding',
      rows: [],
    });
    render(<AutomationRunsPanel documentId="doc-1" client={client} />);

    expect((await screen.findByTestId('document-delivery')).getAttribute('data-status')).toBe(
      'not_configured',
    );
    expect(screen.getByTestId('delivery-skip').textContent).toContain('no template binding');
    expect(screen.getByText('No automatic runs yet.')).toBeTruthy();

    const before = (client.listJobs as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(screen.getByTestId('runs-refresh'));
    await waitFor(() =>
      expect((client.listJobs as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(before),
    );
  });

  it('falls back to the newest workspace runs when the document has none', async () => {
    const client = baseClient();
    (client.listJobs as ReturnType<typeof vi.fn>).mockImplementation(
      (params: { document_id?: string } = {}) =>
        Promise.resolve({
          items: params.document_id ? [] : [{ ...baseJob, document_id: 'doc-2' }],
        }),
    );
    render(<AutomationRunsPanel documentId="doc-1" client={client} />);

    expect(await screen.findByTestId('runs-scope')).toBeTruthy();
    expect(screen.getByTestId('run-job_sent')).toBeTruthy();
    expect(client.listJobs).toHaveBeenCalledWith({ document_id: 'doc-1' });
    expect(client.listJobs).toHaveBeenCalledWith({});
  });

  it('ties approval and delivery into one rail', async () => {
    render(
      <AutomationRunsPanel documentId="doc-1" submissionStatus="approved" client={baseClient()} />,
    );

    const rail = await screen.findByTestId('delivery-chain');
    expect(rail.querySelectorAll('[data-state]')).toHaveLength(5);
    expect(screen.getByTestId('delivery-chain-caption').textContent).toContain('Approved');
  });

  it('does not ask for a delivery state without an open document', async () => {
    const client = baseClient();
    render(<AutomationRunsPanel documentId={null} client={client} />);

    expect(await screen.findByText('Open a document to see its delivery state.')).toBeTruthy();
    expect(client.readDocumentDelivery).not.toHaveBeenCalled();
  });
});