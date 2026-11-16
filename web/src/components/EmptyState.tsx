import type { ReactNode } from 'react';

/**
 * The reference prototype's empty-state shape (design D11): an icon, a title, a reason and the
 * primary next action. A bare paragraph of grey text is not an empty state.
 */
export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon: string;
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden="true">
        {icon}
      </div>
      <h3 className="empty-title">{title}</h3>
      {hint ? <p className="empty-hint tiny">{hint}</p> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}