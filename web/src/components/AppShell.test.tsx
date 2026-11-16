/** Shell layers: product frame, standing environment band, document header (2.1–2.4). */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

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