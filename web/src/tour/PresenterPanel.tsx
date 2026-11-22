/**
 * Presenter teleprompter: a floating script for the human talking through the 8-minute demo.
 *
 * It only reads the plan (sections + budgets) and keeps a timer. It never clicks, types or calls
 * the network, so it cannot change a document or a submission while the demo is running.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { PRESENTER_SECTIONS, PRESENTER_TOTAL_SECONDS } from './presenter';

const format = (seconds: number): string => {
  const safe = Math.max(0, Math.round(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, '0')}`;
};

export function PresenterPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [running, setRunning] = useState(true);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setIndex(0);
    setElapsed(0);
    setRunning(true);
  }, [open]);

  useEffect(() => {
    if (!open || !running) return undefined;
    timer.current = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
      timer.current = null;
    };
  }, [open, running]);

  const next = useCallback(
    () => setIndex((value) => Math.min(PRESENTER_SECTIONS.length - 1, value + 1)),
    [],
  );
  const prev = useCallback(() => setIndex((value) => Math.max(0, value - 1)), []);
  const restart = () => {
    setElapsed(0);
    setIndex(0);
    setRunning(true);
  };

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        next();
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        prev();
      } else if (event.key === ' ') {
        event.preventDefault();
        setRunning((value) => !value);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [next, onClose, open, prev]);

  if (!open) return null;

  const section = PRESENTER_SECTIONS[index];
  const remaining = Math.max(0, PRESENTER_TOTAL_SECONDS - elapsed);

  return (
    <section className="presenter" role="dialog" aria-label="Presenter script" data-testid="presenter">
      <div className="presenter-head">
        <div>
          <strong>Presenter script</strong>{' '}
          <span className="tiny muted">8-minute demo · this panel never drives the UI</span>
        </div>
        <div className="row">
          <span
            className={`presenter-clock ${remaining === 0 ? 'presenter-clock--over' : ''}`}
            data-testid="presenter-clock"
          >
            {format(elapsed)} / {format(PRESENTER_TOTAL_SECONDS)} · left {format(remaining)}
          </span>
          <button type="button" onClick={() => setRunning((value) => !value)} data-testid="presenter-toggle">
            {running ? 'Pause' : 'Resume'}
          </button>
          <button type="button" onClick={restart}>
            Restart
          </button>
          <button type="button" onClick={onClose} aria-label="Close presenter script">
            ×
          </button>
        </div>
      </div>

      <div className="presenter-body">
        <nav aria-label="Presenter sections" className="presenter-sections">
          {PRESENTER_SECTIONS.map((item, itemIndex) => (
            <button
              key={item.id}
              type="button"
              aria-current={itemIndex === index}
              onClick={() => setIndex(itemIndex)}
            >
              {itemIndex + 1}. {item.title}{' '}
              <span className="muted">({format(item.budget)})</span>
            </button>
          ))}
        </nav>

        <div className="presenter-current">
          <div className="row">
            <h3>{section.title}</h3>
            <span className="tiny muted">budget {format(section.budget)}</span>
          </div>
          <ul className="tiny">
            {section.cues.map((cue) => (
              <li key={cue}>{cue}</li>
            ))}
          </ul>
          <div className="row">
            <button type="button" onClick={prev} disabled={index === 0}>
              Previous
            </button>
            <button
              type="button"
              className="primary"
              onClick={next}
              disabled={index === PRESENTER_SECTIONS.length - 1}
              data-testid="presenter-next"
            >
              Next section
            </button>
            <span className="tiny muted">← / → sections · Space pause · Esc close</span>
          </div>
        </div>
      </div>
    </section>
  );
}