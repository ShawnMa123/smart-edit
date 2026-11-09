/** Task 14.1 - the editor must not reset its selection when the parent echoes its own output. */

import { EditorContent, type Editor } from '@tiptap/react';
import { act, render, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { describe, expect, it } from 'vitest';

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