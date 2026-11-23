import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AiWaitBox } from './AiWaitBox';

describe('AiWaitBox', () => {
  it('is a live status with title, message, elapsed time and a cancel action', async () => {
    const onCancel = vi.fn();
    render(
      <AiWaitBox
        title="Asking the statute service"
        message="Searching the statute corpus…"
        hint="The answer will cite the chunks it used."
        elapsedMs={2_500}
        onCancel={onCancel}
      />,
    );

    const box = screen.getByTestId('ai-wait');
    expect(box.getAttribute('role')).toBe('status');
    expect(box.getAttribute('aria-busy')).toBe('true');
    expect(box.querySelector('.ai-wait__glyph')).toBeTruthy();
    expect(box.querySelectorAll('.ai-wait__thinking i')).toHaveLength(3);
    expect(screen.getByText('Asking the statute service')).toBeTruthy();
    expect(screen.getByText('Searching the statute corpus…')).toBeTruthy();
    expect(screen.getByText('2.5s elapsed')).toBeTruthy();
    expect(screen.getByText(/will cite the chunks/i)).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Stop waiting' }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('renders only the phases it is given, marking the active one', () => {
    render(
      <AiWaitBox
        title="Working on your question"
        steps={['Resolve context', 'Retrieve evidence', 'Compose answer']}
        activeStep={1}
      />,
    );

    expect(screen.getByRole('list', { name: 'Progress' })).toBeTruthy();
    expect(screen.getByText('Resolve context').closest('li')?.getAttribute('data-state')).toBe('done');
    expect(screen.getByText('Retrieve evidence').closest('li')?.getAttribute('data-state')).toBe(
      'active',
    );
    expect(screen.getByText('Compose answer').closest('li')?.getAttribute('data-state')).toBe(
      'pending',
    );
  });

  it('renders a one-line inline status without the card copy', () => {
    render(
      <AiWaitBox
        variant="inline"
        title="Waiting for the app"
        message="card only"
        hint="card only"
        elapsedMs={1500}
      />,
    );

    const box = screen.getByTestId('ai-wait');
    expect(box.className).toContain('ai-wait--inline');
    expect(box.querySelector('.ai-wait__glyph')).toBeTruthy();
    expect(screen.getByText('Waiting for the app')).toBeTruthy();
    expect(screen.getByText('1.5s elapsed')).toBeTruthy();
    expect(screen.queryByText('card only')).toBeNull();
    expect(box.querySelector('.ai-wait__progress')).toBeNull();
  });

  it('omits the cancel action when the call cannot be stopped', () => {
    render(<AiWaitBox title="Running the rule check" />);

    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText(/elapsed/)).toBeNull();
  });
});