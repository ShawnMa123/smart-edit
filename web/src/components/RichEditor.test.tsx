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