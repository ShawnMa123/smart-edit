import { DEMO_ORGS, DEMO_USERS, demoUser, type DemoState } from '../demo/demoData';

export interface DemoPeopleDialogProps {
  state: DemoState;
  onInviteGuest: () => void;
  onRevokeGuest: () => void;
}

export function DemoPeopleDialog({ state, onInviteGuest, onRevokeGuest }: DemoPeopleDialogProps) {
  const guest = demoUser('lawyer');
  return (
    <div>
      <p className="notice notice--warn tiny">
        <strong>Sample data.</strong> The directory below is a demo fixture, not an authenticated
        organisation or member list.
      </p>
      {DEMO_ORGS.map((org) => (
        <section className="demo-org" key={org.id}>
          <div className="row">
            <h3>{org.name}</h3>
            <span className="tag tag--muted">Sample organisation</span>
          </div>
          <ul className="demo-people-list">
            {org.members.map((id) => {
              const user = DEMO_USERS.find((item) => item.id === id);
              if (!user) return null;
              return (
                <li className="demo-person" key={user.id}>
                  <span className="avatar" aria-hidden="true">
                    {user.initials}
                  </span>
                  <div className="demo-person-copy">
                    <strong>{user.name}</strong>
                    <span>{user.role}</span>
                  </div>
                  <span className="tag tag--ok">Verified in demo</span>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      <section className="demo-org">
        <div className="row">
          <h3>External collaborator</h3>
          <span className="tag tag--warn">Guest · simulated</span>
        </div>
        <div className="demo-person">
          <span className="avatar" aria-hidden="true">
            {guest.initials}
          </span>
          <div className="demo-person-copy">
            <strong>{guest.name}</strong>
            <span>
              {guest.org} · {guest.role}
            </span>
            <span className="tiny muted">Status: {state.guestStatus} · simulated</span>
          </div>
          {state.guestStatus === 'revoked' ? (
            <button type="button" className="small primary" onClick={onInviteGuest}>
              Invite external counsel
            </button>
          ) : (
            <button type="button" className="small" onClick={onRevokeGuest}>
              Revoke guest
            </button>
          )}
        </div>
      </section>
    </div>
  );
}