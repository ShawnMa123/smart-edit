/** Tasks 2.1-2.4 — the rich editor: formats, toolbar state, tables, find/replace, fallback. */

import { Editor } from '@tiptap/core';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { RichEditor } from './RichEditor';
import { richToPlainText } from '../rich/plainText';
import { plainTextToDocument, type RichDocument } from '../rich/richDocument';
import { extensions, toEditorContent, toRichDocument } from '../rich/tiptap';
import { useRichEditor as realUseRichEditor } from '../rich/useRichEditor';

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
    expect(screen.getByLabelText('Paragraph style')).toBeTruthy();
    for (const name of ['Bold', 'Italic', 'Underline', 'Bullet list']) {
      expect(screen.getByRole('button', { name })).toBeTruthy();
    }
    await userEvent.click(screen.getByText('Table'));
    expect(screen.getByRole('button', { name: 'Insert table' })).toBeTruthy();

    // A structural edit is the reliable way to prove the `onChange` wiring in jsdom (ProseMirror's
    // text input handling needs a real browser event pipeline).
    await userEvent.click(screen.getByRole('button', { name: 'Insert table' }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const latest = onChange.mock.calls[onChange.mock.calls.length - 1][0] as RichDocument;
    expect(JSON.stringify(latest)).toContain('table');
  });

  it('changes the block format through the grouped select', async () => {
    const onChange = vi.fn();
    render(<RichEditor document={doc('Plain text')} onChange={onChange} />);

    const select = (await screen.findByLabelText('Paragraph style')) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      'paragraph',
      'heading-1',
      'heading-2',
      'heading-3',
    ]);
    expect(select.value).toBe('paragraph');

    await userEvent.selectOptions(select, 'heading-2');
    await waitFor(() => {
      const latest = onChange.mock.calls[onChange.mock.calls.length - 1][0] as RichDocument;
      expect(JSON.stringify(latest)).toContain('"level":2');
    });
  });

  it('switches footer lock actions with the lock state and reports submit', async () => {
    const onReleaseLock = vi.fn();
    const onStartEditing = vi.fn();
    const onSubmitVersion = vi.fn();
    const { rerender } = render(
      <RichEditor
        document={doc('Plain text')}
        onChange={vi.fn()}
        lockHeld
        onReleaseLock={onReleaseLock}
        onStartEditing={onStartEditing}
        onSubmitVersion={onSubmitVersion}
      />,
    );

    const release = screen.getByRole('button', { name: 'Release lock' }) as HTMLButtonElement;
    const start = screen.getByRole('button', { name: 'Start editing' }) as HTMLButtonElement;
    expect(release.disabled).toBe(false);
    expect(start.disabled).toBe(true);

    await userEvent.click(release);
    await userEvent.click(screen.getByRole('button', { name: 'Submit new version' }));
    expect(onReleaseLock).toHaveBeenCalledTimes(1);
    expect(onSubmitVersion).toHaveBeenCalledTimes(1);

    rerender(
      <RichEditor
        document={doc('Plain text')}
        onChange={vi.fn()}
        lockHeld={false}
        onReleaseLock={onReleaseLock}
        onStartEditing={onStartEditing}
        onSubmitVersion={onSubmitVersion}
      />,
    );
    expect((screen.getByRole('button', { name: 'Release lock' }) as HTMLButtonElement).disabled).toBe(true);
    const unlockedStart = screen.getByRole('button', { name: 'Start editing' }) as HTMLButtonElement;
    expect(unlockedStart.disabled).toBe(false);
    await userEvent.click(unlockedStart);
    expect(onStartEditing).toHaveBeenCalledTimes(1);
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
describe('variable references (1.2, 1.5)', () => {
  const variableDoc = (displayValue: string | null): RichDocument => ({
    type: 'doc',
    content: [
      {
        type: 'paragraph',
        content: [
          { type: 'text', text: 'Amount: ' },
          {
            type: 'variableReference',
            attrs: {
              variableId: 'var_amount',
              label: 'amount',
              valueType: 'amount',
              required: true,
              displayValue,
              occurrenceId: 'occ_1',
            },
          },
        ],
      },
    ],
  });

  it('round-trips a variable through the editor schema and projects its value', () => {
    const editor = headless(variableDoc('USD 500,000.00'));

    const roundTripped = toRichDocument(editor.getJSON());

    expect(JSON.stringify(roundTripped)).toContain('"variableReference"');
    expect(richToPlainText(roundTripped)).toBe('Amount: USD 500,000.00');
    editor.destroy();
  });

  it('renders a non-editable chip with the variable id', () => {
    const editor = headless(variableDoc('USD 500,000.00'));

    const html = editor.getHTML();

    expect(html).toContain('data-variable-id="var_amount"');
    expect(html).toContain('variable-chip');
    expect(html).toContain('USD 500,000.00');
    editor.destroy();
  });

  it('shows the explicit {{label}} placeholder when empty', () => {
    const editor = headless(variableDoc(null));

    expect(editor.getHTML()).toContain('{{amount}}');
    expect(richToPlainText(toRichDocument(editor.getJSON()))).toBe('Amount: {{amount}}');
    editor.destroy();
  });

  it('does not destroy the node when ordinary text is appended', () => {
    const editor = headless(variableDoc('USD 500,000.00'));

    editor.chain().focus('end').insertContent('!').run();
    const next = toRichDocument(editor.getJSON());

    expect(JSON.stringify(next)).toContain('"variableReference"');
    expect(richToPlainText(next)).toContain('USD 500,000.00');
    editor.destroy();
  });

  it('offers a toolbar entry that is disabled without a selection', () => {
    render(
      <RichEditor document={doc('Amount')} onChange={vi.fn()} onMarkVariable={vi.fn()} />,
    );

    const button = screen.getByRole('button', { name: 'Mark selection as variable' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it('offers a keyboard entry for the same action', async () => {
    const onMarkVariable = vi.fn();
    let instance: Editor | null = null;
    const captureEditor = (options: Parameters<typeof realUseRichEditor>[0]) => {
      const editor = realUseRichEditor(options);
      instance = editor;
      return editor;
    };
    render(
      <RichEditor
        document={doc('Amount')}
        onChange={vi.fn()}
        onMarkVariable={onMarkVariable}
        useEditorImpl={captureEditor}
      />,
    );

    act(() => {
      instance?.commands.setTextSelection({ from: 1, to: 1 + 'Amount'.length });
    });
    fireEvent.keyDown(screen.getByTestId('editor-rich'), {
      key: 'v',
      altKey: true,
      shiftKey: true,
    });

    expect(onMarkVariable).toHaveBeenCalledTimes(1);
    expect(onMarkVariable.mock.calls[0][0]).toMatchObject({ selectedText: 'Amount' });
  });

  it('undoes an external whole-document replacement', () => {
    const captured: { editor: Editor | null } = { editor: null };
    const captureEditor = (options: Parameters<typeof realUseRichEditor>[0]) => {
      const editor = realUseRichEditor(options);
      captured.editor = editor;
      return editor;
    };
    const { rerender } = render(
      <RichEditor document={doc('Original')} onChange={vi.fn()} useEditorImpl={captureEditor} />,
    );

    rerender(
      <RichEditor document={doc('Replaced')} onChange={vi.fn()} useEditorImpl={captureEditor} />,
    );
    act(() => {
      captured.editor?.commands.undo();
    });

    const current = toRichDocument(captured.editor?.getJSON());
    expect(richToPlainText(current)).toBe('Original');
  });

  it('keeps import provenance when an imported document is edited', () => {
    const onChange = vi.fn();
    let instance: Editor | null = null;
    const captureEditor = (options: Parameters<typeof realUseRichEditor>[0]) => {
      const editor = realUseRichEditor(options);
      instance = editor;
      return editor;
    };
    const imported: RichDocument = {
      ...plainTextToDocument('Amount'),
      provenance: 'heuristic',
      provenanceNote: 'font_size_1.42x',
    };
    render(
      <RichEditor document={imported} onChange={onChange} useEditorImpl={captureEditor} />,
    );

    act(() => {
      instance?.chain().focus('end').insertContent('!').run();
    });

    const latest = onChange.mock.calls[onChange.mock.calls.length - 1][0] as RichDocument;
    expect(latest.provenance).toBe('heuristic');
    expect(latest.provenanceNote).toBe('font_size_1.42x');
  });

  it('fallback shows {{label}} and explains that variable editing needs the rich editor', () => {
    const broken = () => {
      throw new Error('schema exploded');
    };

    render(
      <RichEditor
        document={variableDoc(null)}
        onChange={vi.fn()}
        useEditorImpl={broken}
        onMarkVariable={vi.fn()}
      />,
    );

    const textarea = screen.getByTestId('editor-text') as HTMLTextAreaElement;
    expect(textarea.value).toBe('Amount: {{amount}}');
    expect(screen.getByTestId('fallback-variable-notice').textContent).toContain(
      'Variable editing needs the rich editor',
    );
    expect(screen.getByTestId('fallback-variable-notice').textContent).toContain('{{label}}');
    expect(screen.queryByRole('button', { name: 'Mark selection as variable' })).toBeNull();
    });
  });
describe('page presentation (3.1, 3.2)', () => {
  const renderEditor = (over: Partial<Parameters<typeof RichEditor>[0]> = {}) =>
    render(
      <RichEditor
        document={plainTextToDocument('DEMAND GUARANTEE')}
        onChange={() => undefined}
        documentId="demo-document"
        versions={2}
        draftRevision={12}
        lockHeld
        {...over}
      />,
    );

  it('renders the editing surface inside a page container', () => {
    renderEditor();

    const paper = document.querySelector('article.paper');
    expect(paper).toBeTruthy();
    expect(paper!.querySelector('[data-testid="editor-rich"]')).toBeTruthy();
    expect(paper!.textContent).toContain('WORKING COPY');
    expect(paper!.textContent).toContain('demo-document');
    expect(paper!.textContent).not.toContain('DG-2026-00417');
    expect(screen.getByRole('toolbar', { name: 'Formatting' })).toBeTruthy();
  });

  it('puts the save, snapshot and lock state in one band in words', () => {
    renderEditor({ saveState: 'saved' });

    const band = screen.getByTestId('editor-status');
    expect(band.textContent).toContain('snapshot v2');
    expect(band.textContent).toContain('draft rev 12');
    expect(band.textContent).toContain('lock: this session');
    expect(screen.getByTestId('save-state').textContent).toBe('Saved to server');
  });

  it('says unknown rather than inventing a lock holder', () => {
    renderEditor({ lockHeld: false, draftRevision: null, versions: 0 });

    const band = screen.getByTestId('editor-status');
    expect(band.textContent).toContain('lock: unknown');
    expect(band.textContent).toContain('no server draft');
    expect(band.textContent).toContain('no captured version');
  });
});
});