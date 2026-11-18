import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { IMPLEMENTATION_MAP, ImplementationMap } from './ImplementationMap';

describe('ImplementationMap', () => {
  it('lists available, partial and unavailable modules in words', () => {
    render(<ImplementationMap />);

    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getAllByText('Available').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Partial').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
    expect(screen.getByText(/No authentication or organisation service/i)).toBeTruthy();
  });

  it('does not invent API contracts or sample identities', () => {
    render(<ImplementationMap />);

    const text = document.body.textContent ?? '';
    expect(text).not.toContain('http://');
    expect(text).not.toContain('https://');
    expect(text).not.toContain('endpoint');
    expect(text).not.toMatch(/Alpha Tech|HSBC|Acme/);
    expect(IMPLEMENTATION_MAP.every((row) => row.module && row.limitation)).toBe(true);
  });
});