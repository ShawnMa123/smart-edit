// @vitest-environment node
/**
 * Task 6.1 — the import path over real HTTP: upload → parse → `documents[]` → editor text.
 *
 *   SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
 *     .venv/bin/uvicorn app.api.main:app --port 8010 &
 *
 *   VITE_E2E=1 VITE_E2E_IMPORT=1 VITE_API_BASE=http://127.0.0.1:8010 \
 *     npm --prefix web run test -- src/e2e.import.test.ts
 *
 * Node's global `File`/`FormData` let the browser client be used unchanged. OCR depends on a system
 * engine, so the image case asserts either a recognition result or the *named* refusal.
 */

import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { createRunWithFiles, triggerStage } from './api/client';
import type { ImportedDocument } from './api/types';

const enabled = import.meta.env.VITE_E2E === '1' && import.meta.env.VITE_E2E_IMPORT === '1';

const fixture = (name: string): File => {
  const bytes = readFileSync(new URL(`../../fixtures/imports/${name}`, import.meta.url));
  const type =
    name.endsWith('.docx')
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : name.endsWith('.png')
        ? 'image/png'
        : name.endsWith('.xlsx')
          ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
          : 'text/plain';
  return new File([bytes], name, { type });
};

const importFile = async (name: string): Promise<{ documents: ImportedDocument[]; stages: string[] }> => {
  const created = await createRunWithFiles([fixture(name)]);
  const parsed = await triggerStage(created.thread_id, 'parse');
  return {
    documents: parsed.documents ?? [],
    stages: (parsed.stages ?? []).map((report) => `${report.stage}:${report.status}`),
  };
};

describe.skipIf(!enabled)('file import over HTTP', () => {
  it('6.1 a DOCX becomes editable text, with its source named', async () => {
    const { documents, stages } = await importFile('guarantee.docx');

    // eslint-disable-next-line no-console
    console.log('DOCX:', documents[0]?.form, '|', stages.join(' '), '| chars:', documents[0]?.full_text.length);

    expect(documents).toHaveLength(1);
    expect(documents[0].form).toBe('docx_text');
    expect(documents[0].errors).toEqual([]);
    expect(documents[0].full_text).toContain('DEMAND GUARANTEE');
    expect(documents[0].full_text).toContain('Adidas AG');
    expect(documents[0].full_text).toContain('USD 500,000.00');
    expect(stages).toEqual(['parse:done']);
  });

  it('6.1 an image either yields recognised text or a named refusal', async () => {
    const { documents, stages } = await importFile('scan.png');
    const document = documents[0];

    // eslint-disable-next-line no-console
    console.log('PNG:', document.form, '|', stages.join(' '), '| errors:', document.errors.join(','));

    expect(document.form).toBe('image_ocr');
    if (document.errors.length === 0) {
      expect(document.full_text.length).toBeGreaterThan(0);
    } else {
      expect(document.errors[0]).toMatch(/^(ocr_engine_missing|no_text_recognized|ocr_failed)/);
      expect(document.full_text).toBe('');
      expect(stages[0]).toMatch(/parse:(partial|failed)/);
    }
  });

  it('6.1 plain text still parses exactly as before', async () => {
    const { documents } = await importFile('notes.txt');

    expect(documents[0].form).toBe('plain_text');
    expect(documents[0].full_text).toContain('AMOUNT: USD 500.00');
  });

  it('6.1 an unsupported type is refused by name, not silently accepted', async () => {
    const { documents, stages } = await importFile('sheet.xlsx');

    // eslint-disable-next-line no-console
    console.log('XLSX:', documents[0].errors.join(','), '|', stages.join(' '));

    expect(documents[0].errors[0]).toMatch(/^unsupported_mime/);
    expect(documents[0].full_text).toBe('');
    expect(stages[0]).toBe('parse:failed');
  });
});