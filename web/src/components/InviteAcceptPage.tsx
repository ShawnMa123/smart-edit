/** Accept a one-time invite link (`/invites/<token>`) while signed in (task 4.3 UI). */

import { useState } from 'react';

import { ApiError } from '../api/errors';
import * as api from '../api/identity';
import { useAuth } from '../auth/AuthProvider';

export function InviteAcceptPage({ token, fetchImpl }: { token: string; fetchImpl?: typeof fetch }) {
  const auth = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.acceptInvite(token, { fetchImpl });
      await auth.switchOrg(result.org_id);
      await auth.refresh();
      window.history.replaceState({}, '', '/');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'could not accept this invite');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card">
        <h1>Join organisation</h1>
        <p className="tiny">
          This one-time link adds your account to the inviting organisation with the granted role.
          It can be used once and expires after 72 hours.
        </p>
        {error ? (
          <p className="notice notice--warn" role="alert">
            {error}
          </p>
        ) : null}
        <button type="button" className="primary" disabled={busy} onClick={() => void accept()}>
          {busy ? 'Accepting…' : 'Accept invite'}
        </button>
      </section>
    </main>
  );
}