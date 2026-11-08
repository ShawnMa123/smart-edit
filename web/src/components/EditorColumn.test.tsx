/** Task 6.2 — the document editor column. */

import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CHAR_SOFT_LIMIT, EditorColumn } from './EditorColumn';

function Harness({ initial = '' }: { initial?: string }) {
  const [text, setText] = useState(initial);
  const [dirty, setDirty] = useState(false);
  return (
    <EditorColumn
      text={text}
      dirty={dirty}
      onChange={(next) => {
        setText(next);
        setDirty(true);
      }}
      onCapture={vi.fn()}
    />
  );
}

describe('EditorColumn', () => {
  it('reports typing as an unsaved change and updates the character count', async () => {
    render(<Harness />);

    expect(screen.getByText('No unsaved changes')).toBeTruthy();
    expect(screen.getByText('0 characters')).toBeTruthy();

    await userEvent.type(screen.getByLabelText('Document text'), 'abc');

    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    expect(screen.getByText('3 characters')).toBeTruthy();
  });

  it('keeps the typed text verbatim (no smart quotes or paragraph rewriting)', async () => {
    render(<Harness />);
    const textarea = screen.getByLabelText('Document text') as HTMLTextAreaElement;

    await userEvent.click(textarea);
    await userEvent.paste('"ABC" \u2014 900-1234');

    expect(textarea.value).toBe('"ABC" — 900-1234');
  });

  it('warns above the soft character limit', () => {
    render(
      <EditorColumn
        text={'a'.repeat(CHAR_SOFT_LIMIT + 1)}
        dirty={false}
        onChange={vi.fn()}
        onCapture={vi.fn()}
      />,
    );

    expect(
      screen.getByText(new RegExp(`${CHAR_SOFT_LIMIT.toLocaleString()} character guidance`)),
    ).toBeTruthy();
  });

  it('offers a capture action', async () => {
    const onCapture = vi.fn();
    render(<EditorColumn text="abc" dirty onChange={vi.fn()} onCapture={onCapture} />);

    await userEvent.click(screen.getByRole('button', { name: /Capture version/i }));

    expect(onCapture).toHaveBeenCalled();
  });

  it('labels rich text as unimplemented', () => {
    render(<EditorColumn text="" dirty={false} onChange={vi.fn()} onCapture={vi.fn()} />);

    expect(screen.getByText(/rich text is not implemented/i)).toBeTruthy();
  });
});