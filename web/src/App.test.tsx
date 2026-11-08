/** Task 2.2 — the three-pane shell and the narrow-viewport switcher. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

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

  it('offers the audit action inside the assistant pane', () => {
    setViewport(false);
    render(<App />);

    expect(screen.getByRole('button', { name: /Run spec audit/i })).toBeTruthy();
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