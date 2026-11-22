/** Task 2.2 — the three-pane shell and the narrow-viewport switcher. */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { automationTemplateStore } from './automation/templateStore';
import { plainTextToDocument } from './rich/richDocument';
import { versionStore } from './versionStore';

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

  it('opens module dialogs from the rail and the top bar', async () => {
    setViewport(false);
    render(<App />);

    const rail = document.querySelector('.rail') as HTMLElement;
    expect(rail).toBeTruthy();

    await userEvent.click(within(rail).getByRole('button', { name: 'Approval' }));
    expect(screen.getByRole('dialog', { name: /Approval workflow/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    const topbar = document.querySelector('.topbar') as HTMLElement;
    await userEvent.click(within(topbar).getByRole('button', { name: 'Activity' }));
    expect(screen.getByRole('dialog', { name: 'Activity' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    await userEvent.click(within(rail).getByRole('button', { name: 'People' }));
    expect(screen.getByRole('dialog', { name: /Organisation & members/ })).toBeTruthy();
  });

  it('opens the Comments placeholder from the document header', async () => {
    setViewport(false);
    render(<App />);

    const header = document.querySelector('.document-head') as HTMLElement;
    await userEvent.click(within(header).getByRole('button', { name: 'Comments' }));

    const dialog = screen.getByRole('dialog', { name: /Comments — not available/ });
    expect(dialog.textContent).toContain('comment service');
    expect(dialog.textContent).not.toMatch(/HSBC|Alpha Tech|@/);
  });

  it('toggles demo identity and restores the neutral session when off', async () => {
    setViewport(false);
    render(<App />);

    expect(screen.getByRole('button', { name: /Local demo session/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));

    const identity = await screen.findByRole('button', { name: /Demo identity: Chen Rui/ });
    expect(identity.textContent).toContain('Alpha Tech Ltd.');
    expect(screen.getByText(/not real authentication or workflow/i)).toBeTruthy();

    await userEvent.click(identity);
    expect(screen.getByRole('dialog', { name: 'Demo identity' }).textContent).toContain('Emma Wong');
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    expect(screen.getByRole('button', { name: /Local demo session/ })).toBeTruthy();
    expect(screen.queryByText(/not real authentication or workflow/i)).toBeNull();
  });
it('routes Submit new version to the sample approval in demo mode', async () => {
    setViewport(false);
    render(<App />);

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    await userEvent.click(screen.getByRole('button', { name: 'Submit new version' }));

    const approval = await screen.findByRole('dialog', { name: 'Approval workflow' });
    expect(approval.textContent).toContain('DRAFT');
    expect(approval.textContent).toContain('Sample approval');
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    await userEvent.click(screen.getByRole('button', { name: 'Submit new version' }));
    const honest = screen.getByRole('dialog', { name: 'Submit new version' });
    expect(honest.textContent).toContain('not available in this build');
  });

  it('opens sample comments in demo mode and the honest placeholder when off', async () => {
    setViewport(false);
    render(<App />);

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    const header = document.querySelector('.document-head') as HTMLElement;
    await userEvent.click(within(header).getByRole('button', { name: 'Comments' }));
    const sample = await screen.findByRole('dialog', { name: 'Comments' });
    expect(sample.textContent).toContain('Sample data');
    expect(sample.textContent).toContain('Please confirm the demand period');
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    await userEvent.click(within(header).getByRole('button', { name: 'Comments' }));
    expect(screen.getByRole('dialog', { name: /Comments — not available/ })).toBeTruthy();
  });

  it('switches Activity and Inbox to demo data and back to the real log', async () => {
    setViewport(false);
    render(<App />);

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    expect(screen.getByLabelText('2 unread activity entries')).toBeTruthy();
    expect(screen.getByLabelText('2 unread notifications')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Activity' }));
    const activity = screen.getByRole('dialog', { name: 'Activity' });
    expect(activity.textContent).toContain('Sample data');
    expect(activity.textContent).toContain('Version captured');
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    await userEvent.click(screen.getByRole('button', { name: 'Inbox' }));
    expect(screen.getByRole('dialog', { name: 'Inbox' }).textContent).toContain('Comment added');
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(screen.queryByLabelText(/unread notifications/)).toBeNull();

    await userEvent.click(screen.getByRole('checkbox', { name: 'Demo data' }));
    expect(screen.queryByLabelText(/unread activity/)).toBeNull();
  });

  it('records real operations in the browser-local activity log', async () => {
    setViewport(false);
    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: 'Activity' }));
    expect(screen.getByText(/No activity yet/i)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));

    await userEvent.click(screen.getByRole('button', { name: 'Capture version' }));
    expect(screen.getByLabelText('1 unread activity entry')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Activity' }));
    const dialog = screen.getByRole('dialog', { name: 'Activity' });
    expect(dialog.textContent).toContain('Version captured');
    expect(dialog.textContent).toContain('Version 1 captured');
    expect(dialog.textContent).not.toContain('Draft saved');
  });

  it('compares two captured versions without creating a version or changing the draft', async () => {
    setViewport(false);
    versionStore.clear('demo-document');
    versionStore.capture('demo-document', { digest: 'a'.repeat(64), text: 'First body' });
    versionStore.capture('demo-document', { digest: 'b'.repeat(64), text: 'Second body' });
    render(<App />);

    const beforeCount = versionStore.list('demo-document').length;
    const editorBefore = screen.getByTestId('editor-rich').textContent;

    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Version 1 for comparison' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Version 2 for comparison' }));
    await userEvent.click(screen.getByRole('button', { name: 'Compare versions' }));

    const dialog = screen.getByRole('dialog', { name: 'Version compare' });
    expect(dialog.textContent).toContain('First body');
    expect(dialog.textContent).toContain('Second body');

    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(versionStore.list('demo-document')).toHaveLength(beforeCount);
    expect(screen.getByTestId('editor-rich').textContent).toBe(editorBefore);
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

    await userEvent.click(screen.getByRole('tab', { name: /Automation · server/ }));
    await userEvent.click(screen.getByRole('tab', { name: 'Sandbox' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Templates' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Shell template · v1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Apply to editor' }));

    await waitFor(() =>
      expect(screen.getByTestId('editor-rich').textContent).toContain('Template body'),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Activity' }));
    expect(screen.getByRole('dialog', { name: 'Activity' }).textContent).toContain(
      'Template applied',
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

  it('keeps module entries reachable from the More menu', async () => {
    setViewport(true);
    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: 'More' }));
    expect(screen.getByRole('menu', { name: 'More workspace modules' })).toBeTruthy();

    await userEvent.click(screen.getByRole('menuitem', { name: 'Approval' }));
    expect(screen.getByRole('dialog', { name: /Approval workflow/ })).toBeTruthy();
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