import { useEffect, useId, useRef, type ReactNode } from 'react';

export interface WorkspaceDialogProps {
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  wide?: boolean;
}

/**
 * Accessible shell for workspace dialogs (activity, inbox, compare, placeholders, implementation
 * map). Conditionally rendered instead of native `<dialog>` so jsdom tests exercise the same DOM.
 */
export function WorkspaceDialog({ title, children, onClose, footer, wide = false }: WorkspaceDialogProps) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<Element | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    previousFocus.current = document.activeElement;
    closeRef.current?.focus();

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      if (previousFocus.current instanceof HTMLElement) previousFocus.current.focus();
    };
  }, []);

  return (
    <div
      className="dialog-backdrop"
      data-testid="dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCloseRef.current();
      }}
    >
      <section
        className={`dialog${wide ? ' dialog--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button
            ref={closeRef}
            type="button"
            className="quiet tiny"
            aria-label="Close dialog"
            data-tour="dialog-close"
            onClick={() => onCloseRef.current()}
          >
            Close
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer ? <footer className="dialog-foot">{footer}</footer> : null}
      </section>
    </div>
  );
}