import { readFileSync } from 'node:fs';

import { expect, type Page } from '@playwright/test';

/** The recorded fixture (`fixtures/llm/extract_sample.json`) was taken from exactly this text. */
export const DOCUMENT = readFileSync(
  new URL('../../../fixtures/llm/sample_document.txt', import.meta.url),
  'utf8',
);

/**
 * Page object for the three-pane workspace.
 *
 * Selectors prefer the `data-testid` hooks added to `AuditPanel` / `EditorColumn`: copy changes weekly
 * in a POC, and a test that breaks on wording teaches the team to delete tests.
 */
export class Workspace {
  /** Every POST the page issued to `/api/runs*`, in order. */
  readonly posts: string[] = [];

  constructor(readonly page: Page) {
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (request.method() === 'POST' && url.pathname.startsWith('/api/runs')) {
        this.posts.push(url.pathname);
      }
    });
  }

  async open(): Promise<void> {
    await this.page.goto('/');
    await expect(this.textarea).toBeVisible();
  }

  /**
   * The editor became TipTap in `rich-text-editor`; the old `editor-text` textarea no longer exists.
   * `.ProseMirror` is the contenteditable that owns the document text.
   */
  get textarea() {
    return this.page.locator('[data-testid="editor-rich"] .ProseMirror');
  }

  async paste(text: string): Promise<void> {
    await this.textarea.fill(text);
  }

  async runAudit(): Promise<void> {
    await this.page.locator('[data-testid="audit-run"]').click();
  }

  stageRows = () => this.page.locator('[data-testid="stage-row"]');
  gate = () => this.page.locator('[data-testid="gate"]');
  ruleAudit = () => this.page.locator('[data-testid="rule-audit"]');
  result = () => this.page.locator('[data-testid="audit-result"]');
  staleAlert = () => this.page.locator('[data-testid="stale-alert"]');
  notRunAlert = () => this.page.locator('[data-testid="not-run-alert"]');

  /** `[stage, status]` pairs as rendered, in envelope order. */
  async stages(): Promise<Array<[string, string]>> {
    return this.stageRows().evaluateAll((rows) =>
      rows.map((row) => [row.getAttribute('data-stage') ?? '', row.getAttribute('data-status') ?? '']),
    );
  }

  /** Stage names the page asked the backend to run (`normalize` also backfills parse+extract). */
  stageCalls(): string[] {
    return this.posts
      .filter((path) => path.includes('/stages/'))
      .map((path) => path.split('/stages/')[1] ?? '');
  }
}