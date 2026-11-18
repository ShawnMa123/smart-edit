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

  it('requires exactly two versions and calls onCompare with their ids', async () => {
    const props = renderPanel({
      versions: [
        version(),
        version({ id: 'v-2', label: 'Version 2', text: 'A\n\nC' }),
        version({ id: 'v-3', label: 'Version 3', text: 'A\n\nD' }),
      ],
      onCompare: vi.fn(),
    });

    const compare = screen.getByRole('button', { name: 'Compare versions' });
    expect((compare as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Select two versions to compare.')).toBeTruthy();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Version 1 for comparison' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Version 2 for comparison' }));

    expect((compare as HTMLButtonElement).disabled).toBe(false);
    expect(
      (screen.getByRole('checkbox', { name: 'Select Version 3 for comparison' }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText('Two versions selected.')).toBeTruthy();

    await userEvent.click(compare);
    expect(props.onCompare).toHaveBeenCalledWith(['v-1', 'v-2']);
  });

  it('states that history is browser-local', () => {
    renderPanel();

    expect(screen.getByText(/stored in/i)).toBeTruthy();
    expect(screen.getByText(/this browser only/i)).toBeTruthy();
  });
describe('timeline and document info (4.1, 4.2)', () => {
  it('marks the current version with a word as well as a highlight', () => {
    const { rerender } = render(
      <VersionPanel
        versions={[version(), version({ id: 'v-2', label: 'Version 2' })]}
        currentVersionId="v-1"
        onCapture={vi.fn()}
        onRestore={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(document.querySelector('[data-current="true"]')?.textContent).toContain('Version 1');
    expect(document.querySelector('[data-current="true"]')?.textContent).toContain('current');

    rerender(
      <VersionPanel
        versions={[version(), version({ id: 'v-2', label: 'Version 2' })]}
        currentVersionId="v-2"
        onCapture={vi.fn()}
        onRestore={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    const current = document.querySelector('[data-current="true"]');
    expect(current?.textContent).toContain('Version 2');
    expect(current?.textContent).toContain('current');
  });

  it('lists only real metadata and never sample organisations', () => {
    renderPanel();

    const info = document.querySelector('.document-info');
    expect(info).toBeTruthy();
    expect(info!.textContent).toContain('Versions');
    expect(info!.textContent).not.toMatch(
      /organisation|organization|workspace|participants|Alpha Tech|HSBC/i,
    );
    // Without facts, no document id or draft row is invented.
    expect(info!.textContent).not.toContain('demo-document');
    expect(info!.textContent).not.toContain('revision');
  });

  it('shows the stored document id and draft revision when supplied', () => {
    renderPanel({ facts: { documentId: 'demo-document', draftRevision: 12 } });

    expect(screen.getByText('demo-document')).toBeTruthy();
    expect(screen.getByText('revision 12')).toBeTruthy();
  });
});
});