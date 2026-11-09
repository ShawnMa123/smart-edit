/** Tasks 2.1-2.4 — the rich editor: formats, toolbar state, tables, find/replace, fallback. */

import { Editor } from '@tiptap/core';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { RichEditor } from './RichEditor';
import { richToPlainText } from '../rich/plainText';
import { plainTextToDocument, type RichDocument } from '../rich/richDocument';
import { extensions, toEditorContent, toRichDocument } from '../rich/tiptap';

const headless = (document: RichDocument = plainTextToDocument('DEMAND GUARANTEE')) =>
  new Editor({ extensions, content: toEditorContent(document) });

const doc = (text: string) => plainTextToDocument(text);

describe('formats (2.1)', () => {
  it('applies and removes marks, and the projection stays the same', () => {
    const editor = headless(doc('Amount: USD 500,000.00'));
    const before = richToPlainText(toRichDocument(editor.getJSON()));

    editor.commands.selectAll();
    editor.chain().focus().toggleBold().run();
    const bolded = toRichDocument(editor.getJSON());

    editor.chain().focus().toggleBold().run();
    const plainAgain = toRichDocument(editor.getJSON());

    expect(richToPlainText(bolded)).toBe(before);
    expect(JSON.stringify(bolded)).toContain('"bold"');
    expect(JSON.stringify(plainAgain)).not.toContain('"bold"');
    editor.destroy();
  });

  it('turns a paragraph into a heading and projects it with hashes', () => {
    const editor = headless(doc('DEMAND GUARANTEE'));

    editor.chain().focus().toggleHeading({ level: 2 }).run();

    expect(richToPlainText(toRichDocument(editor.getJSON())).trimEnd()).toBe('## DEMAND GUARANTEE');
    editor.destroy();
  });

  it('builds lists and tables that project with structure', () => {
    const editor = headless(doc('Beneficiary'));

    editor.chain().focus().toggleBulletList().run();
    expect(richToPlainText(toRichDocument(editor.getJSON())).trimEnd()).toBe('- Beneficiary');

    editor.chain().focus().toggleBulletList().run();
    editor.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run();
    const projected = richToPlainText(toRichDocument(editor.getJSON()));
    expect(projected.split('\n').filter((line) => line.includes(' | ')).length).toBeGreaterThan(0);
    editor.destroy();
  });

  it('undoes and redoes an edit', () => {
    const editor = headless(doc('one'));
    editor.chain().focus().insertContent(' two').run();
    const edited = richToPlainText(toRichDocument(editor.getJSON()));

    editor.chain().focus().undo().run();
    const undone = richToPlainText(toRichDocument(editor.getJSON()));
    editor.chain().focus().redo().run();
    const redone = richToPlainText(toRichDocument(editor.getJSON()));

    expect(edited).toContain('two');
    expect(undone).not.toContain('two');
    expect(redone).toBe(edited);
    editor.destroy();
  });

  it('round-trips a display gap through the editor schema (13.5)', () => {
    const editor = headless({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          attrs: { row: true },
          content: [
            { type: 'text', text: 'Beneficiary:' },
            { type: 'pdfGap', attrs: { rule: true, grow: 479.1 } },
          ],
        },
      ],
    });

    const restored = toRichDocument(editor.getJSON());
    const paragraph = restored.content[0];
    expect(paragraph.type).toBe('paragraph');
    if (paragraph.type !== 'paragraph') throw new Error('expected a paragraph');
    expect(paragraph.attrs).toMatchObject({ row: true });

    const gap = (paragraph.content ?? []).find((node) => node.type === 'pdfGap');
    expect(gap).toBeTruthy();
    if (!gap || gap.type !== 'pdfGap') throw new Error('expected a pdfGap');
    expect(gap.attrs).toEqual({ rule: true, grow: 479.1 });

    expect(richToPlainText(restored)).toBe('Beneficiary:');
    editor.destroy();
  });
});

describe('fillable blanks (14.2/14.3)', () => {
  it('accepts typed text inside a gap and projects it', () => {
    const editor = headless({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          attrs: { row: true },
          content: [
            { type: 'text', text: 'Beneficiary:' },
            { type: 'pdfGap', attrs: { rule: true, grow: 479.1 } },
          ],
        },
      ],
    });

    let gapPos = -1;
    editor.state.doc.descendants((node, pos) => {
      if (node.type.name === 'pdfGap') {
        gapPos = pos;
        return false;
      }
      return true;
    });
    expect(gapPos).toBeGreaterThan(-1);

    editor.commands.setTextSelection(gapPos + 1);
    editor.commands.insertContent('ACME Trading');

    const restored = toRichDocument(editor.getJSON());
    expect(richToPlainText(restored)).toBe('Beneficiary: ACME Trading');
    expect(JSON.stringify(restored)).toContain('ACME Trading');
    editor.destroy();
  });
});

describe('toolbar state (2.2)', () => {
  it('reports a mark as active after it is applied', () => {
    const editor = headless(doc('Amount'));

    expect(editor.isActive('bold')).toBe(false);
    editor.chain().focus().toggleBold().run();
    expect(editor.isActive('bold')).toBe(true);
    editor.chain().focus().toggleBold().run();
    expect(editor.isActive('bold')).toBe(false);
    editor.destroy();
  });

  it('does not report a mark as active for a mixed selection', () => {
    const editor = headless({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'bold part', marks: ['bold'] },
            { type: 'text', text: ' and plain part' },
          ],
        },
      ],
    });

    editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });

    expect(editor.isActive('bold')).toBe(false);
    editor.destroy();
  });
});

describe('find and replace (2.3)', () => {
  it('finds every match and replaces them without losing the marks', () => {
    const editor = headless({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'text', text: 'USD 500 and USD 600', marks: ['bold'] }],
        },
      ],
    });

    editor.commands.setSearchTerm('USD');
    const storage = (editor.storage as { findAndReplace?: { results?: unknown[] } }).findAndReplace;
    expect(storage?.results?.length).toBe(2);

    editor.commands.setReplaceTerm('EUR');
    editor.commands.replaceAll();

    const json = JSON.stringify(editor.getJSON());
    expect(json).toContain('EUR 500 and EUR 600');
    expect(json).toContain('"bold"');
    expect(json).not.toContain('USD');
    editor.destroy();
  });

  it('clears the highlights when the search is cleared', () => {
    const editor = headless(doc('USD 500'));
    editor.commands.setSearchTerm('USD');
    editor.commands.clearSearch();

    const storage = (editor.storage as { findAndReplace?: { results?: unknown[] } }).findAndReplace;
    expect(storage?.results ?? []).toHaveLength(0);
    editor.destroy();
  });
});

describe('the component (2.1/2.3)', () => {
  it('renders the document and reports edits as a rich document', async () => {
    const onChange = vi.fn();
    render(
      <RichEditor
        document={{
          type: 'doc',
          content: [
            {
              type: 'heading',
              attrs: { level: 1 },
              content: [{ type: 'text', text: 'DEMAND GUARANTEE' }],
            },
            { type: 'paragraph', content: [{ type: 'text', text: 'Amount: USD 500,000.00' }] },
          ],
        }}
        onChange={onChange}
      />,
    );

    const surface = await screen.findByTestId('editor-rich');
    expect(surface.textContent).toContain('DEMAND GUARANTEE');
    expect(surface.textContent).toContain('USD 500,000.00');
    expect(screen.getByRole('toolbar', { name: 'Formatting' })).toBeTruthy();
    for (const name of ['Heading 1', 'Bold', 'Italic', 'Underline', 'Bullet list', 'Insert table']) {
      expect(screen.getByRole('button', { name })).toBeTruthy();
    }

    // A structural edit is the reliable way to prove the `onChange` wiring in jsdom (ProseMirror's
    // text input handling needs a real browser event pipeline).
    await userEvent.click(screen.getByRole('button', { name: 'Insert table' }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const latest = onChange.mock.calls[onChange.mock.calls.length - 1][0] as RichDocument;
    expect(JSON.stringify(latest)).toContain('table');
  });

  it('opens and closes the find panel', async () => {
    render(<RichEditor document={doc('USD 500')} onChange={vi.fn()} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Find and replace' }));
    await userEvent.type(screen.getByLabelText('Find'), 'USD');
    await waitFor(() => expect(screen.getByTestId('find-status').textContent).toContain('/'));

    await userEvent.click(screen.getByRole('button', { name: 'Close find' }));
    expect(screen.queryByLabelText('Find')).toBeNull();
  });
});

describe('display attributes and page breaks in the editor (8.2)', () => {
  it('draws the original font size and shows a page boundary', async () => {
    const onChange = vi.fn();
    render(
      <RichEditor
        document={{
          type: 'doc',
          content: [
            {
              type: 'paragraph',
              attrs: { fontSize: 9, fontFamily: 'Helvetica', page: 1 },
              content: [{ type: 'text', text: 'Amount: USD 500,000.00' }],
            },
            { type: 'pageBreak' },
            {
              type: 'heading',
              attrs: { level: 2, fontSize: 20, page: 2 },
              content: [{ type: 'text', text: 'Section' }],
            },
          ],
        }}
        onChange={onChange}
      />,
    );

    const surface = await screen.findByTestId('editor-rich');
    const styled = surface.querySelector('[data-font-size="9"]') as HTMLElement | null;
    const heading = surface.querySelector('[data-font-size="20"]') as HTMLElement | null;

    expect(styled?.style.fontSize).toBe('9pt');
    expect(styled?.style.fontFamily).toContain('Helvetica');
    expect(styled?.getAttribute('data-page')).toBe('1');
    expect(heading?.style.fontSize).toBe('20pt');
    expect(surface.querySelector('hr[data-page-break]')).toBeTruthy();
  });

  it('keeps the projection free of markup added by the attributes', async () => {
    const onChange = vi.fn();
    render(
      <RichEditor
        document={{
          type: 'doc',
          content: [
            {
              type: 'paragraph',
              attrs: { fontSize: 9 },
              content: [{ type: 'text', text: 'plain words' }],
            },
            { type: 'pageBreak' },
          ],
        }}
        onChange={onChange}
      />,
    );

    const surface = await screen.findByTestId('editor-rich');
    expect(surface.textContent).toContain('plain words');
    // The page marker contributes no characters: the projection is exactly the 11 characters of the text.
    expect(await screen.findByText('11 characters in the audit text')).toBeTruthy();
  });

  it('renders a drawn blank and a right-aligned number (13.5)', async () => {
    const onChange = vi.fn();
    render(
      <RichEditor
        document={{
          type: 'doc',
          content: [
            {
              type: 'paragraph',
              attrs: { row: true, fontSize: 9 },
              content: [
                { type: 'text', text: 'Beneficiary:' },
                { type: 'pdfGap', attrs: { rule: true, grow: 479.1 } },
              ],
            },
            {
              type: 'paragraph',
              attrs: { align: 'right' },
              content: [{ type: 'text', text: '4' }],
            },
          ],
        }}
        onChange={onChange}
      />,
    );

    const surface = await screen.findByTestId('editor-rich');
    const row = surface.querySelector('[data-pdf-row="true"]') as HTMLElement | null;
    const gap = surface.querySelector('.pdf-gap--rule') as HTMLElement | null;
    const right = surface.querySelector('[data-pdf-align="right"]') as HTMLElement | null;

    expect(row).toBeTruthy();
    expect(gap?.getAttribute('data-pdf-rule')).toBe('true');
    expect(gap?.style.flexGrow).toBe('479.1');
    expect(right).toBeTruthy();
    expect(surface.textContent).toContain('Beneficiary:');
    // The gap contributes no characters: 12 + the block separator + 1.
    expect(await screen.findByText('15 characters in the audit text')).toBeTruthy();
  });
});

describe('fallback (2.4)', () => {
  it('falls back to a textarea and says why when the editor cannot start', async () => {
    const onChange = vi.fn();
    const broken = () => {
      throw new Error('schema exploded');
    };

    render(
      <RichEditor document={doc('DEMAND GUARANTEE')} onChange={onChange} useEditorImpl={broken} />,
    );

    expect(screen.getByRole('status').textContent).toContain('schema exploded');
    const textarea = screen.getByTestId('editor-text');
    expect((textarea as HTMLTextAreaElement).value).toBe('DEMAND GUARANTEE');

    await userEvent.type(textarea, '!');
    expect(onChange).toHaveBeenCalled();
    const latest = onChange.mock.calls[onChange.mock.calls.length - 1][0] as RichDocument;
    expect(richToPlainText(latest)).toContain('DEMAND GUARANTEE!');
  });
});
describe('coverage additions from the spec test design', () => {
  it('supports all three heading levels and paragraph restoration', () => {
    const editor = headless(doc('Title'));
    for (const [level, marker] of [
      [1, '# '],
      [2, '## '],
      [3, '### '],
    ] as const) {
      editor.chain().focus().toggleHeading({ level }).run();
      expect(richToPlainText(toRichDocument(editor.getJSON())).trimEnd()).toBe(`${marker}Title`);
    }
    editor.chain().focus().setParagraph().run();
    expect(richToPlainText(toRichDocument(editor.getJSON())).trimEnd()).toBe('Title');
    editor.destroy();
  });

  it('inserts and deletes rows and columns before and after the current cell', () => {
    const editor = headless(doc('cell'));
    editor.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run();

    const counts = () => {
      let rows = 0;
      let cells = 0;
      editor.state.doc.descendants((node) => {
        if (node.type.name === 'tableRow') rows += 1;
        if (node.type.name === 'tableCell' || node.type.name === 'tableHeader') cells += 1;
        return true;
      });
      return { rows, cells };
    };

    expect(counts()).toEqual({ rows: 2, cells: 4 });
    editor.chain().focus().addRowBefore().run();
    expect(counts().rows).toBe(3);
    editor.chain().focus().addRowAfter().run();
    expect(counts().rows).toBe(4);
    editor.chain().focus().deleteRow().run();
    expect(counts().rows).toBe(3);
    editor.chain().focus().addColumnBefore().run();
    expect(counts().cells).toBe(9);
    editor.chain().focus().addColumnAfter().run();
    expect(counts().cells).toBe(12);
    editor.chain().focus().deleteColumn().run();
    expect(counts().cells).toBe(9);
    editor.chain().focus().toggleHeaderRow().run();
    editor.destroy();
  });

  it('treats regex metacharacters as literal search text', () => {
    const editor = headless(doc('a.*b (x) [y] aZZb'));
    editor.commands.setSearchTerm('a.*b');
    const storage = (editor.storage as { findAndReplace?: { results?: unknown[] } }).findAndReplace;
    expect(storage?.results?.length).toBe(1);
    editor.commands.setReplaceTerm('LITERAL');
    editor.commands.replaceAll();
    expect(richToPlainText(toRichDocument(editor.getJSON()))).toBe('LITERAL (x) [y] aZZb');
    editor.destroy();
  });

  it('projects an empty document to the empty string', () => {
    expect(richToPlainText({ type: 'doc', content: [] })).toBe('');
    expect(richToPlainText({ type: 'doc', content: [{ type: 'pageBreak' }] })).toBe('');
  });
});

describe('spec gaps found by the audit test design', () => {
  it.fails('BUG-F5 exposes insert-before/left and header toggle controls for tables', () => {
    render(<RichEditor document={doc('cell')} onChange={vi.fn()} />);
    for (const name of ['Insert row above', 'Insert column left', 'Toggle header row']) {
      expect(screen.getByRole('button', { name })).toBeTruthy();
    }
  });
});
