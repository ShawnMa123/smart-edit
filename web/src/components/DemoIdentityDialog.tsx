import { DEMO_USERS, type DemoState, type DemoUserId } from '../demo/demoData';

export interface DemoIdentityDialogProps {
  state: DemoState;
  onSelect: (id: DemoUserId) => void;
}

export function DemoIdentityDialog({ state, onSelect }: DemoIdentityDialogProps) {
  return (
    <div>
      <p className="notice notice--warn tiny">
        <strong>Demo identity.</strong> These are sample users, not an authentication result. Switching
        identity affects sample collaboration permissions only; the real editor, lock and audit
        principal do not change.
      </p>
      <ul className="demo-people-list">
        {DEMO_USERS.map((user) => {
          const current = user.id === state.currentUserId;
          return (
            <li className="demo-person" key={user.id}>
              <span className="avatar" aria-hidden="true">
                {user.initials}
              </span>
              <div className="demo-person-copy">
                <strong>{user.name}</strong>
                <span>
                  {user.org} · {user.role}
                </span>
              </div>
              {current ? (
                <span className="tag tag--ok">Current demo identity</span>
              ) : (
                <button type="button" className="small" onClick={() => onSelect(user.id)}>
                  Switch
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}