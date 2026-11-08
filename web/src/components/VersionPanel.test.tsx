/** Task 6.1 — the version history pane. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { VersionPanel } from './VersionPanel';
import type { VersionEntry } from '../versionStore';

const version = (over: Partial<VersionEntry> = {}): VersionEntry => ({
  id: 'v-1',
  label: 'Version 1',
  digest: 'a'.repeat(64),
  createdAt: '2026-11-08T09:00:00.000Z',
  chars: 12,
  text: 'hello world',
  ...over,
});

const renderPanel = (over: Partial<Parameters<typeof VersionPanel>[0]> = {}) => {
  const props = {
    versions: [version()],
    currentVersionId: null,
    onCapture: vi.fn(),
    onRestore: vi.fn(),
    onClear: vi.fn(),
    ...over,
  };
  render(<VersionPanel {...props} />);
  return props;
};

describe('VersionPanel', () => {
  it('lists versions with label, size and a short digest', () => {
    renderPanel();

    expect(screen.getByText('Version 1')).toBeTruthy();
    expect(screen.getByText('12 chars')).toBeTruthy();
    expect(screen.getByText('a'.repeat(12))).toBeTruthy();
  });

  it('shows an empty state before anything is captured', () => {
    renderPanel({ versions: [] });

    expect(screen.getByText(/No versions yet/i)).toBeTruthy();
  });

  it('restores a version by id', async () => {
    const props = renderPanel();

    await userEvent.click(screen.getByRole('button', { name: /Restore into editor/i }));

    expect(props.onRestore).toHaveBeenCalledWith('v-1');
  });

  it('captures and clears from the pane actions', async () => {
    const props = renderPanel();

    await userEvent.click(screen.getByRole('button', { name: /Capture version/i }));
    await userEvent.click(screen.getByRole('button', { name: /Clear version history/i }));

    expect(props.onCapture).toHaveBeenCalled();
    expect(props.onClear).toHaveBeenCalled();
  });

  it('offers comparison as visibly unavailable', () => {
    renderPanel();

    const compare = screen.getByRole('button', { name: /Compare versions — not implemented/i });
    expect((compare as HTMLButtonElement).disabled).toBe(true);
  });

  it('states that history is browser-local', () => {
    renderPanel();

    expect(screen.getByText(/stored in/i)).toBeTruthy();
    expect(screen.getByText(/this browser only/i)).toBeTruthy();
  });
});