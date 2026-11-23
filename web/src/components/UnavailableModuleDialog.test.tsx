import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { UnavailableModuleDialog } from './UnavailableModuleDialog';

describe('UnavailableModuleDialog', () => {
  it('states the missing capability without sample identity data', () => {
    render(<UnavailableModuleDialog module="people" />);

    expect(screen.getByText(/Organisation membership is not available in this build/i)).toBeTruthy();
    expect(screen.getByText(/authentication service, organisation directory/i)).toBeTruthy();
    expect(screen.getByText(/No member rows, organisation names, roles/i)).toBeTruthy();
    const text = document.body.textContent ?? '';
    expect(text).not.toContain('@');
    expect(text).not.toMatch(/Alpha Tech|HSBC|Acme/);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('covers identity, approval and comments with their own boundaries', () => {
    const cases = [
      ['identity', /Authentication is not configured/i],
      ['approval', /approval workflow is not available/i],
      ['comments', /Comments are not available/i],
    ] as const;

    for (const [module, summary] of cases) {
      const { unmount } = render(<UnavailableModuleDialog module={module} />);
      expect(screen.getByText(summary)).toBeTruthy();
      expect(document.body.textContent ?? '').not.toMatch(/Alpha Tech|HSBC|Acme|@/);
      unmount();
    }
  });
});