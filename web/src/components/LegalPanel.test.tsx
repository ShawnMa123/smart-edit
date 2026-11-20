/** LegalPanel: statute advice surface. */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { LegalPanel } from './LegalPanel';

describe('LegalPanel', () => {
  it('shows the statute advice surface', () => {
    render(<LegalPanel documentId="doc-1" client={{ submitReview: vi.fn(), getReport: vi.fn() }} />);

    expect(screen.getByLabelText('Legal question')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Ask' })).toBeTruthy();
    expect(screen.getByText(/仅供参考/)).toBeTruthy();
    // The deterministic rule check is not part of the legal module.
    expect(screen.queryByRole('tab', { name: 'Rule check' })).toBeNull();
  });
});
