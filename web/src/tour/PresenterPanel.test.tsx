/** Presenter teleprompter: sections, countdown, pause and close — no app actions. */

import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PresenterPanel } from './PresenterPanel';

const renderPanel = () => {
  const onClose = vi.fn();
  render(<PresenterPanel open onClose={onClose} />);
  return onClose;
};

afterEach(() => {
  vi.useRealTimers();
});

describe('PresenterPanel', () => {
  it('starts on the opening section with the 8-minute clock', () => {
    renderPanel();

    expect(screen.getByTestId('presenter')).toBeTruthy();
    expect(screen.getByText('开场：登录与工作台')).toBeTruthy();
    expect(screen.getByTestId('presenter-clock').textContent).toContain('left 8:00');
    expect(screen.getByTestId('presenter-clock').textContent).toContain('0:00 / 8:00');
  });

  it('moves between sections and closes on Escape', async () => {
    const onClose = renderPanel();

    await userEvent.click(screen.getByTestId('presenter-next'));
    expect(screen.getByText('★ 模板审计（核心）')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }));
    expect(screen.getByText('开场：登录与工作台')).toBeTruthy();

    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('counts up and freezes while paused', () => {
    vi.useFakeTimers();
    renderPanel();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByTestId('presenter-clock').textContent).toContain('0:02 /');

    fireEvent.click(screen.getByTestId('presenter-toggle'));
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId('presenter-clock').textContent).toContain('0:02 /');
    expect(screen.getByTestId('presenter-toggle').textContent).toBe('Resume');
  });
});