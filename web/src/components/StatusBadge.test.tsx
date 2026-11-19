import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusBadge } from './StatusBadge';

describe('StatusBadge', () => {
  it.each([
    ['draft', 'Draft', 'status-badge--neutral'],
    ['pending_first', 'Pending first approval', 'status-badge--processing'],
    ['pending_second', 'Pending second approval', 'status-badge--processing'],
    ['approved', 'Approved', 'status-badge--success'],
    ['returned', 'Returned', 'status-badge--warning'],
    ['rejected', 'Rejected', 'status-badge--error'],
  ])('renders %s as text, icon and tone', (status, label, toneClass) => {
    const { container } = render(<StatusBadge status={status} />);
    const badge = screen.getByRole('img', { name: `Approval status: ${label}` });

    expect(badge.textContent).toContain(label);
    expect(badge.className).toContain('status-badge');
    expect(badge.className).toContain(toneClass);
    expect(badge.getAttribute('data-status')).toBe(status);
    expect(badge.querySelector('.status-badge-icon')?.textContent).toBeTruthy();
    expect(container.textContent).not.toMatch(/pending_first|pending_second/);
  });

  it('shows unknown statuses as Unknown with an explanatory label', () => {
    render(<StatusBadge status="awaiting_something" />);

    const badge = screen.getByRole('img', { name: 'Approval status: Unknown' });
    expect(badge.textContent).toContain('Unknown');
    expect(badge.getAttribute('data-status')).toBe('unknown');
    expect(badge.getAttribute('title')).toContain('awaiting_something');
  });
});