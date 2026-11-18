/** Shell layers: product frame, standing environment band, document header (2.1–2.4). */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
    render(<TopBar onOpenModule={onOpenModule} activityCount={3} unreadCount={2} />);

    for (const label of ['Activity', 'People', 'Inbox', 'Developer']) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy();
    }
    expect(screen.getByLabelText('3 activity entries').textContent).toBe('3');
    expect(screen.getByLabelText('2 unread notifications').textContent).toBe('2');

    fireEvent.click(screen.getByRole('button', { name: 'People' }));
    expect(onOpenModule).toHaveBeenCalledWith('people');

    fireEvent.click(screen.getByRole('button', { name: /Local demo session/ }));
    expect(onOpenModule).toHaveBeenCalledWith('identity');
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
    expect(text).toMatch(/does not approve or submit/i);
    expect(text).toMatch(/this browser/i);
    expect(screen.getByRole('status')).toBeTruthy();
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
});