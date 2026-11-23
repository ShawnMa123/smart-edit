/** Task 14.1 - the editor must not reset its selection when the parent echoes its own output. */

import { EditorContent, type Editor } from '@tiptap/react';
import { act, render, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { richToPlainText } from './plainText';
import { plainTextToDocument, type RichDocument } from './richDocument';
import { toRichDocument } from './tiptap';
import { useRichEditor } from './useRichEditor';

function Harness({ onReady }: { onReady: (editor: Editor) => void }) {
  const [document, setDocument] = useState<RichDocument>(() => plainTextToDocument('one two'));
  const editor = useRichEditor({ document, onChange: setDocument });

  useEffect(() => {
    if (editor) onReady(editor);
  }, [editor, onReady]);

  return <EditorContent editor={editor} />;
}

describe('the editor state loop (14.1)', () => {
  it('keeps the caret when the parent echoes the editor output', async () => {
    let editor: Editor | null = null;
    render(
      <Harness
        onReady={(instance) => {
          editor = instance;
        }}
      />,
    );

    await waitFor(() => expect(editor).not.toBeNull());
    // "one two": position 4 is after "one", before the space. A parent echo that calls `setContent`
    // would move this selection to the end of the document.
    act(() => {
      editor!.commands.setTextSelection(4);
      editor!.commands.insertContent('X');
    });

    await waitFor(() =>
      expect(richToPlainText(toRichDocument(editor!.getJSON()))).toContain('oneX two'),
    );
    expect(editor!.state.selection.from).toBe(5);
  });
});

/**
 * Regression (deployment, ECS :8082): `editor.setEditable()` emits an update by default, so mounting
 * the read-write editor reported an empty document as a user edit. `App` then treated the server
 * draft as "the operator typed first" and overwrote it with empty content on the next save.
 */
function MountHarness({
  onChange,
  editable,
}: {
  onChange: (document: RichDocument) => void;
  editable?: boolean;
}) {
  const editor = useRichEditor({
    document: plainTextToDocument('server draft body'),
    onChange,
    editable,
  });
  return <EditorContent editor={editor} />;
}

describe('mounting the editor (deployment regression)', () => {
  it('does not report the mount-time editable transaction as a user edit', async () => {
    const onChange = vi.fn();
    const { container } = render(<MountHarness onChange={onChange} editable />);

    await waitFor(() => expect(container.querySelector('.ProseMirror')).not.toBeNull());
    // Let any mount transaction land before asserting.
    await act(async () => {
      await Promise.resolve();
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('keeps the server document when the editor mounts read-only', async () => {
    const onChange = vi.fn();
    const { container } = render(<MountHarness onChange={onChange} editable={false} />);

    await waitFor(() => expect(container.querySelector('.ProseMirror')).not.toBeNull());
    await act(async () => {
      await Promise.resolve();
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(container.querySelector('.ProseMirror')?.textContent).toContain('server draft body');
  });
});

function FocusHarness({ block, token }: { block: number | null; token: number }) {
  const editor = useRichEditor({
    document: plainTextToDocument('one\n\ntwo\n\nthree'),
    onChange: () => {},
    focusBlock: block,
    focusToken: token,
  });
  return <EditorContent editor={editor} />;
}

describe('document-anchor jump ("legal-document-risk-scan")', () => {
  it('moves the caret into the requested top-level block', async () => {
    const { container, rerender } = render(<FocusHarness block={null} token={0} />);
    await waitFor(() => expect(container.querySelector('.ProseMirror')).not.toBeNull());

    rerender(<FocusHarness block={2} token={1} />);

    await waitFor(() => {
      const focused = (container.querySelector('.ProseMirror') as HTMLElement | null)
        ?.ownerDocument.activeElement;
      expect(focused?.className ?? '').toContain('ProseMirror');
    });
  });
});