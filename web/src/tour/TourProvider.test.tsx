/** Guided tour: launcher choices, guide gating, autopilot clicks/typing, stop and missing targets. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { TourProvider, useTour } from './TourProvider';
import type { Tour, TourEditorApi, TourStep } from './types';

const makeTour = (steps: TourStep[]): Tour => ({
  id: `test-${Math.random().toString(36).slice(2)}`,
  version: 1,
  title: 'Test tour',
  description: 'Test description',
  steps,
});

function LaunchButton() {
  const tour = useTour();
  return (
    <button type="button" onClick={() => tour.openLauncher()}>
      start
    </button>
  );
}

function EditorRegistrar({ api }: { api: TourEditorApi }) {
  const tour = useTour();
  useEffect(() => {
    tour.registerEditor(api);
    return () => tour.registerEditor(null);
  }, [api, tour]);
  return null;
}

const startTour = async (
  mode: 'guide' | 'auto' = 'guide',
  approvals: 'manual' | 'auto' = 'manual',
) => {
  await userEvent.click(screen.getByRole('button', { name: 'start' }));
  expect(await screen.findByTestId('tour-launcher')).toBeTruthy();
  if (mode === 'auto') {
    await userEvent.click(screen.getByRole('radio', { name: /Watch me/i }));
  }
  if (approvals === 'auto') {
    await userEvent.click(screen.getByRole('radio', { name: /Let the tour submit/i }));
  }
  await userEvent.click(screen.getByTestId('tour-start'));
};

describe('TourProvider', () => {
  it('launches a dialog, then gates Next on the real app state in guide mode', async () => {
    function Harness() {
      const [ready, setReady] = useState(false);
      return (
        <div>
          <button type="button" data-tour="gate" onClick={() => setReady(true)}>
            finish the step
          </button>
          {ready ? <span data-tour="ready" /> : null}
        </div>
      );
    }
    const tour = makeTour([
      {
        id: 'one',
        title: 'First step',
        body: 'Do the thing',
        target: '[data-tour="gate"]',
        until: { kind: 'selector', selector: '[data-tour="ready"]' },
      },
      { id: 'two', title: 'Second step', body: 'Done', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
        <Harness />
      </TourProvider>,
    );

    await startTour('guide');
    expect(await screen.findByTestId('tour-tooltip')).toBeTruthy();
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('First step');

    const next = screen.getByTestId('tour-next') as HTMLButtonElement;
    expect(next.disabled).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: 'finish the step' }));
    await waitFor(() => expect(next.disabled).toBe(false));

    await userEvent.click(next);
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('Second step');
  });

  it('autopilot clicks the real control and advances by itself', async () => {
    const onTarget = vi.fn();
    function Harness() {
      const [clicked, setClicked] = useState(false);
      return (
        <button
          type="button"
          data-tour="auto-target"
          onClick={() => {
            onTarget();
            setClicked(true);
          }}
        >
          {clicked ? 'clicked' : 'click me'}
          {clicked ? <span data-tour="clicked" /> : null}
        </button>
      );
    }
    const tour = makeTour([
      {
        id: 'auto',
        title: 'Autopilot step',
        body: 'Clicking for you',
        target: '[data-tour="auto-target"]',
        action: { kind: 'click', selector: '[data-tour="auto-target"]' },
        until: { kind: 'selector', selector: '[data-tour="clicked"]' },
      },
      { id: 'done', title: 'Autopilot done', body: 'Finished', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour} autoDwellMs={400}>
        <LaunchButton />
        <Harness />
      </TourProvider>,
    );

    await startTour('auto');
    await waitFor(() => expect(onTarget).toHaveBeenCalledTimes(1));
    await waitFor(
      () => expect(screen.getByTestId('tour-tooltip').textContent).toContain('Autopilot done'),
      { timeout: 4000 },
    );
  });

  it('types through the registered editor bridge', async () => {
    const texts: string[] = [];
    const api: TourEditorApi = {
      clear: vi.fn(),
      focus: vi.fn(),
      insertText: (text) => texts.push(text),
    };
    const tour = makeTour([
      {
        id: 'typing',
        title: 'Typing',
        body: 'Typing for you',
        action: { kind: 'type', text: 'abcdef', cps: 1000 },
      },
      { id: 'after', title: 'After typing', body: 'ok', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour} autoDwellMs={400}>
        <LaunchButton />
        <EditorRegistrar api={api} />
      </TourProvider>,
    );

    await startTour('auto');
    await waitFor(() => expect(texts.join('')).toBe('abcdef'));
    expect(api.clear).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }));
  });

  it('keeps submission manual unless the operator allows the tour to submit', async () => {
    const submit = vi.fn();
    const tour = makeTour([
      {
        id: 'submit',
        title: 'Submit',
        body: 'This is yours to click',
        target: '[data-tour="submit"]',
        action: { kind: 'click', selector: '[data-tour="submit"]' },
        requiresApprovalAuto: true,
        until: { kind: 'selector', selector: '[data-tour="submitted"]' },
      },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
        <button type="button" data-tour="submit" onClick={submit}>
          Submit
        </button>
      </TourProvider>,
    );

    await startTour('auto', 'manual');
    const hint = await screen.findByTestId('tour-hint');
    expect(hint.textContent).toContain('manual');
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(submit).not.toHaveBeenCalled();
  });

  it('skips an optional step whose target is not on screen', async () => {
    const tour = makeTour([
      {
        id: 'missing',
        title: 'Not here',
        body: 'Optional',
        target: '[data-tour="does-not-exist"]',
        optional: true,
      },
      { id: 'next', title: 'Next step', body: 'Here', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
      </TourProvider>,
    );

    await startTour('guide');
    await waitFor(
      () => expect(screen.getByTestId('tour-tooltip').textContent).toContain('Next step'),
      { timeout: 3000 },
    );
  });

  it('stops on Escape and removes the overlay', async () => {
    const tour = makeTour([
      { id: 'only', title: 'Only step', body: 'Press Escape', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
      </TourProvider>,
    );

    await startTour('guide');
    expect(await screen.findByTestId('tour-layer')).toBeTruthy();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('tour-layer')).toBeNull());
  });

  it('shows a reading countdown in autopilot and lets the reader jump ahead', async () => {
    const tour = makeTour([
      { id: 'read', title: 'Read me', body: 'Long copy', placement: 'center' },
      { id: 'next', title: 'Second step', body: 'Next', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour} autoDwellMs={5000}>
        <LaunchButton />
      </TourProvider>,
    );

    await startTour('auto');
    expect(await screen.findByTestId('tour-countdown')).toBeTruthy();
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('Read me');
    expect(screen.getByTestId('tour-countdown').textContent).toMatch(/Auto-advance in \d+s/);

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('Read me');

    await userEvent.click(screen.getByTestId('tour-next'));
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('Second step');
  });

  it('freezes the autopilot countdown while paused', async () => {
    const tour = makeTour([
      { id: 'read', title: 'Read me', body: 'Long copy', placement: 'center' },
      { id: 'next', title: 'Second step', body: 'Next', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour} autoDwellMs={1200}>
        <LaunchButton />
      </TourProvider>,
    );

    await startTour('auto');
    await screen.findByTestId('tour-countdown');
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }));

    await new Promise((resolve) => setTimeout(resolve, 1600));
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('Read me');
    expect(screen.getByTestId('tour-countdown').textContent).toContain('Paused');

    await userEvent.click(screen.getByRole('button', { name: 'Resume' }));
    await waitFor(
      () => expect(screen.getByTestId('tour-tooltip').textContent).toContain('Second step'),
      { timeout: 4000 },
    );
  });

  it('lets the operator pick a tour from the catalog', async () => {
    const first: Tour = {
      id: 'first',
      version: 1,
      title: 'First tour',
      description: 'One',
      steps: [{ id: 'first-step', title: 'First step', body: 'A', placement: 'center' }],
    };
    const second: Tour = {
      id: 'second',
      version: 1,
      title: 'Second tour',
      description: 'Two',
      steps: [{ id: 'second-step', title: 'Second step', body: 'B', placement: 'center' }],
    };
    function LaunchSecond() {
      const tour = useTour();
      return (
        <button type="button" onClick={() => tour.openLauncher('second')}>
          start second
        </button>
      );
    }

    render(
      <TourProvider tours={[first, second]}>
        <LaunchSecond />
      </TourProvider>,
    );

    await userEvent.click(screen.getByRole('button', { name: 'start second' }));
    expect(await screen.findByTestId('tour-launcher')).toBeTruthy();
    const select = screen.getByRole('combobox', { name: 'Tour' }) as HTMLSelectElement;
    expect(select.value).toBe('second');

    await userEvent.selectOptions(select, 'first');
    expect(select.value).toBe('first');

    await userEvent.click(screen.getByTestId('tour-start'));
    expect(screen.getByTestId('tour-tooltip').textContent).toContain('First step');
  });

  it('skips a step whose precondition is already true', async () => {
    const tour = makeTour([
      {
        id: 'skipped',
        title: 'Should be skipped',
        body: 'Already submitted',
        target: '[data-tour="gate"]',
        skipIf: [{ kind: 'selector', selector: '[data-tour="already"]' }],
      },
      { id: 'shown', title: 'After the skip', body: 'Here', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
        <span data-tour="already" />
        <button type="button" data-tour="gate">
          gate
        </button>
      </TourProvider>,
    );

    await startTour('guide');
    await waitFor(
      () => expect(screen.getByTestId('tour-tooltip').textContent).toContain('After the skip'),
      { timeout: 3000 },
    );
  });

  it('skips a step when the guarded control is absent (RBAC-hidden tab)', async () => {
    const tour = makeTour([
      {
        id: 'guarded',
        title: 'Needs a role',
        body: 'The control is hidden for this session',
        target: '[data-tour="gate"]',
        skipIf: [{ kind: 'absent', selector: '[data-tour="no-such-tab"]' }],
      },
      { id: 'shown', title: 'After the guard', body: 'Here', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
        <button type="button" data-tour="gate">
          gate
        </button>
      </TourProvider>,
    );

    await startTour('guide');
    await waitFor(
      () => expect(screen.getByTestId('tour-tooltip').textContent).toContain('After the guard'),
      { timeout: 3000 },
    );
  });

  it('opens a disclosure once and never closes it on a repeated step', async () => {
    const tour = makeTour([
      {
        id: 'open-once',
        title: 'Open the disclosure',
        body: 'Opening',
        target: '[data-tour="details"]',
        action: { kind: 'open', selector: '[data-tour="details"]' },
      },
      {
        id: 'open-again',
        title: 'Ask again',
        body: 'Still open',
        target: '[data-tour="details"]',
        action: { kind: 'open', selector: '[data-tour="details"]' },
      },
      { id: 'done', title: 'After the disclosures', body: 'Done', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour} autoDwellMs={300}>
        <LaunchButton />
        <details data-tour="details">
          <summary>more</summary>
          <p>inside</p>
        </details>
      </TourProvider>,
    );

    const details = document.querySelector('details[data-tour="details"]') as HTMLDetailsElement;
    await startTour('auto');
    await waitFor(() => expect(details.open).toBe(true));
    await waitFor(
      () => expect(screen.getByTestId('tour-tooltip').textContent).toContain('Ask again'),
      { timeout: 4000 },
    );
    await waitFor(
      () =>
        expect(screen.getByTestId('tour-tooltip').textContent).toContain('After the disclosures'),
      { timeout: 4000 },
    );
    expect(details.open).toBe(true);
  });

  it('shows both submission choices and reflects the selection', async () => {
    const tour = makeTour([
      { id: 'only', title: 'Only step', body: 'Body', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
      </TourProvider>,
    );

    await userEvent.click(screen.getByRole('button', { name: 'start' }));
    expect(screen.getByTestId('tour-approvals-auto')).toBeTruthy();
    expect(screen.getByTestId('tour-approvals-manual')).toBeTruthy();
    expect(screen.getByTestId('tour-summary').textContent).toContain('hand off to me');

    await userEvent.click(screen.getByTestId('tour-approvals-auto'));
    expect(screen.getByTestId('tour-summary').textContent).toContain('the tour submits');

    await userEvent.click(screen.getByTestId('tour-mode-auto'));
    expect(screen.getByTestId('tour-summary').textContent).toContain('Watch me');
  });

  it('opens the presenter script from the launcher without starting the tour', async () => {
    const tour = makeTour([
      { id: 'only', title: 'Only step', body: 'Body', placement: 'center' },
    ]);

    render(
      <TourProvider tour={tour}>
        <LaunchButton />
      </TourProvider>,
    );

    await userEvent.click(screen.getByRole('button', { name: 'start' }));
    await userEvent.click(screen.getByTestId('tour-presenter'));

    expect(await screen.findByTestId('presenter')).toBeTruthy();
    expect(screen.queryByTestId('tour-tooltip')).toBeNull();

    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('presenter')).toBeNull());
  });
});