/**
 * Lightweight semantic toasts (`approval-ui-polish` D6).
 *
 * Pure React, no dependencies: at most three stacked messages, one live region for assistive
 * technology, errors stay until dismissed, everything else clears itself. Toasts are for immediate
 * feedback only; persistent state (read-only, return reasons, conflicts) stays in inline banners.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ToastVariant = 'success' | 'info' | 'warning' | 'error';

export const MAX_TOASTS = 3;
export const DEFAULT_TOAST_DURATION_MS = 4000;

export interface ToastInput {
  message: string;
  variant?: ToastVariant;
  /** `null` keeps the toast until it is dismissed. Defaults to 4s, or never for errors. */
  durationMs?: number | null;
  actionLabel?: string;
  onAction?: () => void;
}

export interface ToastEntry {
  id: string;
  message: string;
  variant: ToastVariant;
  actionLabel?: string;
  onAction?: () => void;
}

type ToastExtras = Omit<ToastInput, 'message' | 'variant'>;

export interface ToastApi {
  toasts: ToastEntry[];
  notify: (input: ToastInput) => string;
  dismiss: (id: string) => void;
  success: (message: string, extras?: ToastExtras) => string;
  info: (message: string, extras?: ToastExtras) => string;
  warning: (message: string, extras?: ToastExtras) => string;
  error: (message: string, extras?: ToastExtras) => string;
}

const ToastContext = createContext<ToastApi | null>(null);

const noop = () => '';
const fallbackToast: ToastApi = {
  toasts: [],
  notify: noop,
  dismiss: () => undefined,
  success: noop,
  info: noop,
  warning: noop,
  error: noop,
};

const VARIANT_ICON: Record<ToastVariant, string> = {
  success: '✓',
  info: 'ℹ',
  warning: '!',
  error: '✕',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const timers = useRef(new Map<string, number>());
  const counter = useRef(0);

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((previous) => previous.filter((toast) => toast.id !== id));
  }, []);

  useEffect(
    () => () => {
      for (const timer of timers.current.values()) window.clearTimeout(timer);
      timers.current.clear();
    },
    [],
  );

  const notify = useCallback(
    (input: ToastInput) => {
      counter.current += 1;
      const id = `toast-${counter.current}`;
      const variant = input.variant ?? 'info';
      const entry: ToastEntry = {
        id,
        message: input.message,
        variant,
        actionLabel: input.actionLabel,
        onAction: input.onAction,
      };
      setToasts((previous) => [...previous, entry].slice(-MAX_TOASTS));

      const duration =
        input.durationMs === undefined
          ? variant === 'error'
            ? null
            : DEFAULT_TOAST_DURATION_MS
          : input.durationMs;
      if (duration !== null) {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo<ToastApi>(
    () => ({
      toasts,
      notify,
      dismiss,
      success: (message, extras) => notify({ ...extras, message, variant: 'success' }),
      info: (message, extras) => notify({ ...extras, message, variant: 'info' }),
      warning: (message, extras) => notify({ ...extras, message, variant: 'warning' }),
      error: (message, extras) => notify({ ...extras, message, variant: 'error' }),
    }),
    [dismiss, notify, toasts],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-relevant="additions text">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast toast--${toast.variant}`}
            role={toast.variant === 'error' ? 'alert' : 'status'}
            data-variant={toast.variant}
          >
            <span className="toast-icon" aria-hidden="true">
              {VARIANT_ICON[toast.variant]}
            </span>
            <span className="toast-message">{toast.message}</span>
            {toast.actionLabel && toast.onAction ? (
              <button
                type="button"
                className="toast-action"
                onClick={() => {
                  toast.onAction?.();
                  dismiss(toast.id);
                }}
              >
                {toast.actionLabel}
              </button>
            ) : null}
            <button
              type="button"
              className="toast-dismiss"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** Components can render outside a provider (isolated tests); toasts then become a no-op. */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? fallbackToast;
}