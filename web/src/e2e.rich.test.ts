// @vitest-environment node
/**
 * Task 6.1 — the rich structure over real HTTP: what the editor receives for DOCX and for a real PDF.
 *
 *   SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
 *     .venv/bin/uvicorn app.api.main:app --port 8010 &
 *
 *   VITE_E2E=1 VITE_E2E_RICH=1 VITE_API_BASE=http://127.0.0.1:8010 \
 *     npm --prefix web run test -- src/e2e.rich.test.ts
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { createRunWithFiles, triggerStage } from './api/client';
import type { ImportedDocument } from './api/types';

const enabled = import.meta.env.VITE_E2E === '1' && import.meta.env.VITE_E2E_RICH === '1';

const fixture = (relative: string, name: string, type: string): File => {
  const bytes = readFileSync(fileURLToPath(new URL(`../../${relative}`, import.meta.url)));
  return new File([bytes], name, { type });
};

const structureOf = async (file: File): Promise<ImportedDocument> => {
  const created = await createRunWithFiles([file]);
  const parsed = await triggerStage(created.thread_id, 'parse');
  const documents = parsed.documents ?? [];
  expect(documents).toHaveLength(1);
  return documents[0];
};

const countBlocks = (document: ImportedDocument) => {
  const content = (document.rich?.content ?? []) as Array<{ type: string }>;
  return {
    blocks: content.length,
    headings: content.filter((block) => block.type === 'heading').length,
    tables: content.filter((block) => block.type === 'table').length,
  };
};

describe.skipIf(!enabled)('rich structure over HTTP', () => {
  it('6.1 a DOCX arrives as deterministic structure', async () => {
    const document = await structureOf(
      fixture(
        'fixtures/imports/guarantee.docx',
        'guarantee.docx',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ),
    );
    const counts = countBlocks(document);

    // eslint-disable-next-line no-console
    console.log('DOCX rich:', document.rich?.provenance, JSON.stringify(counts));

    expect(document.form).toBe('docx_text');
    expect(document.rich?.provenance).toBe('deterministic');
    expect(counts.tables).toBe(1);
    expect(counts.blocks).toBeGreaterThan(2);
  });

  it('6.1/9.1 the shipped 25-page booklet arrives as heuristic structure with headings', async () => {
    const document = await structureOf(
      fixture(
        'fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf',
        'guarantee-and-standby-letters-of-credit-wording.pdf',
        'application/pdf',
      ),
    );
    const counts = countBlocks(document);

    // eslint-disable-next-line no-console
    console.log('PDF rich:', document.rich?.provenance, JSON.stringify(counts));

    expect(document.form).toBe('pdf_text');
    expect(document.rich?.provenance).toBe('heuristic');
    expect(counts.headings).toBeGreaterThan(0);
    expect(counts.blocks).toBeGreaterThan(50);
  });

  it('9.1 overload: page breaks and display attributes survive the trip', async () => {
    const document = await structureOf(
      fixture(
        'fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf',
        'guarantee-and-standby-letters-of-credit-wording.pdf',
        'application/pdf',
      ),
    );
    const content = (document.rich?.content ?? []) as Array<{ type: string; attrs?: Record<string, unknown> }>;
    const breaks = content.filter((block) => block.type === 'pageBreak').length;
    const withFont = content.filter((block) => block.attrs?.fontSize !== undefined).length;

    // eslint-disable-next-line no-console
    console.log('Booklet rich:', JSON.stringify({ blocks: content.length, breaks, withFont }));

    expect(document.rich?.provenanceNote ?? '').toContain('25 pages');
    expect(breaks).toBe(24);
    expect(withFont).toBe(content.length - breaks);
  });
});