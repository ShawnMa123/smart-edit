/** Shell layers: product frame, standing environment band, document header (2.1–2.4). */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SubmissionSummary } from '../api/approvalTypes';
import {
  DOCUMENT_SECTION,
  DocumentHead,
  EnvironmentStrip,
  PRODUCT_NAME,
  SESSION_LABEL,
  TopBar,
  type DocumentFacts,
} from './AppShell';

const facts = (over: Partial<DocumentFacts> = {}): DocumentFacts => ({
  documentId: 'demo-document',
  title: 'Demand Guarantee',
  versions: 2,
  characters: 41,
  draftRevision: 7,
  draftSha256: 'a'.repeat(64),
  provenance: null,
  lockLabel: 'held by this session',
  ...over,
});

const submission = (over: Partial<SubmissionSummary> = {}): SubmissionSummary => ({
  submission_id: 'sub_1',
  document_id: 'demo-document',
  revision: 3,
  content_sha256: 'a'.repeat(64),
  status: 'pending_first',
  submitted_by: 'user_applicant',
  created_at: '2026-11-19T14:02:00Z',
  request_id: 'apr_1',
  current_stage: 'first',
  approval_revision: 1,
  latest_comment: null,
  latest_decision: null,
  latest_actor: null,
  latest_decided_at: null,
  ...over,
});

describe('TopBar', () => {
  it('names the product and the neutral session, without an identity', () => {
    const { container } = render(<TopBar />);
    const text = container.textContent ?? '';

    expect(text).toContain(PRODUCT_NAME);
    expect(text).toContain(SESSION_LABEL);
    // No fabricated identity: no email, no organisation/member entry.
    expect(text).not.toContain('@');
    expect(text).not.toMatch(/Alpha Tech|HSBC|Acme|member|organisation|organization/i);
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('shows the reference actions with real activity and unread counts', () => {
    const onOpenModule = vi.fn();
    render(
      <TopBar
        onOpenModule={onOpenModule}
        approvalCount={2}
        activityUnread={3}
        unreadCount={2}
      />,
    );

    for (const label of ['Activity', 'Approval', 'People', 'Inbox', 'Developer']) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy();
    }
    expect(screen.getByLabelText('2 approval requests waiting').textContent).toBe('2');
    expect(screen.getByLabelText('3 unread activity entries').textContent).toBe('3');
    expect(screen.getByLabelText('2 unread notifications').textContent).toBe('2');

    fireEvent.click(screen.getByRole('button', { name: 'Approval' }));
    expect(onOpenModule).toHaveBeenCalledWith('approval');

    fireEvent.click(screen.getByRole('button', { name: 'People' }));
    expect(onOpenModule).toHaveBeenCalledWith('people');

    fireEvent.click(screen.getByRole('button', { name: /Local demo session/ }));
    expect(onOpenModule).toHaveBeenCalledWith('identity');
  });

  it('hides zero badges and caps large counts at 99+', () => {
    const { rerender } = render(<TopBar approvalCount={0} activityUnread={0} unreadCount={0} />);
    expect(screen.queryByLabelText(/approval requests waiting/)).toBeNull();
    expect(screen.queryByLabelText(/unread activity entries/)).toBeNull();
    expect(screen.queryByLabelText(/unread notifications/)).toBeNull();

    rerender(<TopBar approvalCount={120} activityUnread={1} />);
    expect(screen.getByLabelText('120 approval requests waiting').textContent).toBe('99+');
    expect(screen.getByLabelText('1 unread activity entry').textContent).toBe('1');
  });

  it('shows the labeled demo identity when demo data is active', () => {
    const onOpenModule = vi.fn();
    render(
      <TopBar
        onOpenModule={onOpenModule}
        demoIdentity={{
          name: 'Chen Rui',
          initials: 'CR',
          org: 'Alpha Tech Ltd.',
          role: 'Applicant',
        }}
      />,
    );

    const identity = screen.getByRole('button', { name: /Demo identity: Chen Rui/ });
    expect(identity.textContent).toContain('Demo identity');
    expect(identity.textContent).toContain('Chen Rui');
    expect(identity.textContent).toContain('Alpha Tech Ltd.');
    expect(screen.queryByRole('button', { name: /Local demo session/ })).toBeNull();

    fireEvent.click(identity);
    expect(onOpenModule).toHaveBeenCalledWith('identity');
  });
});

describe('EnvironmentStrip', () => {
  it('states the three boundaries in one standing line', () => {
    const { container } = render(<EnvironmentStrip />);
    const text = container.textContent ?? '';

    expect(text).toMatch(/synthetic demo data/i);
    expect(text).toMatch(/this browser/i);
    // The old claim that the assistant cannot submit is gone from the standing strip.
    expect(text).not.toMatch(/does not approve or submit/i);
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('describes server-backed approval once PG identity is active', () => {
    render(<EnvironmentStrip authenticated />);

    const strip = screen.getByRole('status');
    expect(strip.textContent).toContain('PG identity');
    expect(strip.textContent).toMatch(/server-backed drafts, approvals and activity/i);
    expect(strip.textContent).not.toMatch(/synthetic demo data|does not approve or submit/i);
  });

  it('exposes the demo toggle and the persistent demo banner', () => {
    const onToggleDemo = vi.fn();
    const onResetDemo = vi.fn();
    const { rerender } = render(
      <EnvironmentStrip onToggleDemo={onToggleDemo} onResetDemo={onResetDemo} />,
    );

    expect(screen.getByRole('checkbox', { name: 'Demo data' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reset demo data' })).toBeNull();
    expect(screen.queryByText(/not real authentication/i)).toBeNull();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    expect(onToggleDemo).toHaveBeenCalledTimes(1);

    rerender(
      <EnvironmentStrip demoMode onToggleDemo={onToggleDemo} onResetDemo={onResetDemo} />,
    );
    expect(screen.getByText(/not real authentication or workflow/i)).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: 'Demo data' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reset demo data' }));
    expect(onResetDemo).toHaveBeenCalledTimes(1);
  });
});

describe('DocumentHead', () => {
  it('leads with document identity and only real metadata', () => {
    render(<DocumentHead facts={facts()} />);

    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Demand Guarantee');
    expect(screen.getByText('Draft')).toBeTruthy();
    expect(screen.getByText(new RegExp(`${DOCUMENT_SECTION} / demo-document`))).toBeTruthy();
    expect(
      screen.getByText(/2 captured versions · 41 characters · server draft rev 7/),
    ).toBeTruthy();
    // No example business facts from the reference prototype.
    expect(screen.queryByText(/Alpha Tech|Beta Construction|DG-2026-00417/)).toBeNull();
  });

  it('keeps the digest and lock state behind Technical details', () => {
    render(<DocumentHead facts={facts()} />);

    const details = document.querySelector('details.document-details') as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.open).toBe(false);
    expect(details.textContent).toContain('aaaaaaaaaaaa…');
    expect(details.textContent).toContain('held by this session');
    // The revision stays on the visible meta line (e2e asserts it is visible).
    expect(details.textContent).not.toContain('server draft rev');
  });

  it('says local-only when there is no server draft', () => {
    render(<DocumentHead facts={facts({ draftRevision: null, draftSha256: null })} />);

    expect(screen.getByText(/server draft local-only/)).toBeTruthy();
    expect(screen.getByText('not available')).toBeTruthy();
  });

  it('shows the real pending status instead of a fixed Draft label', () => {
    render(
      <DocumentHead
        facts={facts()}
        submissionStatus="pending_first"
        submission={submission({ status: 'pending_first', revision: 3 })}
      />,
    );

    const badge = screen.getByRole('img', { name: 'Approval status: Pending first approval' });
    expect(badge.textContent).toContain('Pending first approval');
    expect(screen.queryByText('Draft')).toBeNull();
    const line = screen.getByTestId('document-status-line');
    expect(line.textContent).toContain('Waiting for Bank Operations');
    expect(line.textContent).toContain('revision 3');
    expect(line.textContent).toContain('submitted');
    expect(screen.getByTestId('document-readonly').textContent).toContain('Editing is locked');
  });

  it('shows an approved submission as read-only', () => {
    render(
      <DocumentHead
        facts={facts()}
        submissionStatus="approved"
        submission={submission({ status: 'approved', revision: 4 })}
      />,
    );

    expect(screen.getByRole('img', { name: 'Approval status: Approved' })).toBeTruthy();
    expect(screen.queryByText('Draft')).toBeNull();
    expect(screen.getByTestId('document-readonly').textContent).toMatch(/approved/i);
  });

  it('shows the return reason and keeps the document editable', () => {
    render(
      <DocumentHead
        facts={facts()}
        submissionStatus="returned"
        submission={submission({
          status: 'returned',
          revision: 5,
          latest_comment: 'Add the guarantee expiry date.',
        })}
      />,
    );

    expect(screen.getByRole('img', { name: 'Approval status: Returned' })).toBeTruthy();
    expect(screen.getByTestId('document-latest-comment').textContent).toContain(
      'Add the guarantee expiry date.',
    );
    expect(screen.queryByTestId('document-readonly')).toBeNull();
  });

  it('keeps Draft only when the document was never submitted', () => {
    render(<DocumentHead facts={facts()} submissionStatus="draft" />);

    expect(screen.getByRole('img', { name: 'Approval status: Draft' })).toBeTruthy();
    expect(screen.queryByTestId('document-status-line')).toBeNull();
    expect(screen.queryByTestId('document-readonly')).toBeNull();
  });

  it('switches organisations and signs out from the top bar', () => {
    const onSwitch = vi.fn();
    const onLogout = vi.fn();
    render(
      <TopBar
        organizations={[
          { org_id: 'org_a', name: 'Alpha' },
          { org_id: 'org_b', name: 'Beta' },
        ]}
        activeOrgId="org_a"
        onSwitchOrg={onSwitch}
        userLabel="Owner"
        onLogout={onLogout}
      />,
    );
    fireEvent.change(screen.getByLabelText('Active organisation'), {
      target: { value: 'org_b' },
    });
    expect(onSwitch).toHaveBeenCalledWith('org_b');
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(onLogout).toHaveBeenCalled();
  });
});