/** Task 2.2 — the three-pane shell and the narrow-viewport switcher. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { automationTemplateStore } from './automation/templateStore';
import { plainTextToDocument } from './rich/richDocument';

const setViewport = (narrow: boolean) => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: narrow,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
};

const paneLabels = () =>
  Array.from(document.querySelectorAll('.work-grid > *')).map((node) => node.getAttribute('aria-label'));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('wide viewport', () => {
  it('shows all three panes, in prototype order', () => {
    setViewport(false);
    render(<App />);

    expect(paneLabels()).toEqual(['Version history', 'Document editor', 'AI assistant']);
    expect(screen.queryByRole('tablist', { name: 'Workspace panes' })).toBeNull();
  });

  it('derives the header title from stored metadata, never from an example', () => {
    setViewport(false);
    render(<App />);

    const header = document.querySelector('.document-head') as HTMLElement;
    expect(header).toBeTruthy();
    // No draft has loaded yet, so the English fallback is used.
    expect(header.textContent).toContain('Untitled document');
    expect(header.textContent).not.toContain('见索即付保函');
    expect(header.textContent).not.toContain('DG-2026-00417');
  });

  it('offers the audit action inside the assistant pane', () => {
    setViewport(false);
    render(<App />);

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
  });
});

describe('automation template apply (8.3)', () => {
  it('replaces the editor content and marks it dirty/autosave-pending', async () => {
    automationTemplateStore.capture({
      name: 'Shell template',
      document: plainTextToDocument('Template body'),
      source: { kind: 'edited' },
      revision: null,
      charCount: 'Template body'.length,
      variables: [],
      now: new Date('2026-11-15T10:00:00Z'),
    });
    setViewport(false);
    render(<App />);

    await userEvent.click(screen.getByRole('tab', { name: /Automation · fixture only/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Shell template · v1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Apply to editor' }));

    await waitFor(() =>
      expect(screen.getByTestId('editor-rich').textContent).toContain('Template body'),
    );
    expect(screen.getByTestId('save-state').textContent).toContain('Unsaved changes');
  });
});

describe('narrow viewport', () => {
  it('shows one pane with a tab switcher', () => {
    setViewport(true);
    render(<App />);

    expect(screen.getByRole('tablist', { name: 'Workspace panes' })).toBeTruthy();
    expect(paneLabels()).toHaveLength(1);
    expect(paneLabels()).toEqual(['Document editor']);
  });

  it('switches between panes', async () => {
    setViewport(true);
    render(<App />);

    await userEvent.click(screen.getByRole('tab', { name: 'Version history' }));
    expect(paneLabels()).toEqual(['Version history']);

    await userEvent.click(screen.getByRole('tab', { name: 'AI assistant' }));
    expect(paneLabels()).toEqual(['AI assistant']);
  });

  it('keeps every pane reachable by keyboard', async () => {
    setViewport(true);
    render(<App />);

    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    for (const tab of tabs) {
      expect((tab as HTMLButtonElement).disabled).toBe(false);
    }
  });
});