/** Task 6.4 — actions this build cannot perform are labelled and never report success. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { DocumentActions, UNAVAILABLE_ACTIONS } from './DocumentActions';

describe('DocumentActions', () => {
  it('labels every unavailable action', () => {
    render(<DocumentActions />);

    for (const action of UNAVAILABLE_ACTIONS) {
      expect(screen.getByRole('button', { name: new RegExp(`${action.label} · not implemented`) })).toBeTruthy();
    }
  });

  it('reports unavailability instead of appearing to succeed', async () => {
    render(<DocumentActions />);

    await userEvent.click(screen.getByRole('button', { name: /Export · not implemented/ }));

    expect(screen.getByRole('status').textContent).toContain('Unavailable');
    expect(screen.getByRole('status').textContent).toContain('Export');
    expect(screen.queryByText(/success|done|exported/i)).toBeNull();
  });

  it('explains the reason for the specific action', async () => {
    render(<DocumentActions />);

    await userEvent.click(screen.getByRole('button', { name: /Start approval · not implemented/ }));

    expect(screen.getByRole('status').textContent).toContain('approval workflow');
  });
});