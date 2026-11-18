import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { VersionEntry } from '../versionStore';
import { VersionCompareDialog } from './VersionCompareDialog';

const version = (over: Partial<VersionEntry> = {}): VersionEntry => ({
  id: 'v-1',
  label: 'Version 1',
  digest: 'a'.repeat(64),
  createdAt: '2026-11-17T09:00:00.000Z',
  chars: 3,
  text: 'A\n\nB',
  ...over,
});

describe('VersionCompareDialog', () => {
  it('shows both versions and the block diff', () => {
    render(
      <VersionCompareDialog
        before={version()}
        after={version({ id: 'v-2', label: 'Version 2', text: 'A\n\nC', digest: 'b'.repeat(64) })}
        onClose={() => undefined}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: 'Version compare' });
    expect(dialog.textContent).toContain('Version 1');
    expect(dialog.textContent).toContain('Version 2');
    expect(dialog.textContent).toContain('A');
    expect(dialog.textContent).toContain('B');
    expect(dialog.textContent).toContain('C');
    expect(dialog.textContent).toContain('Read-only comparison');
    expect(dialog.textContent).not.toContain('AI summary:');
  });

  it('states when the captured text has no differences', () => {
    render(
      <VersionCompareDialog before={version()} after={version()} onClose={() => undefined} />,
    );

    expect(screen.getByText(/No textual differences in the captured text/i)).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Version differences' })).toBeNull();
  });
});