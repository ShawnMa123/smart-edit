/** Sign-in / registration page (design D9, task 6.1). */

import { useState, type FormEvent } from 'react';

import { ApiError } from '../api/errors';
import { useAuth } from '../auth/AuthProvider';

type Mode = 'signin' | 'register';

export function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [organizationName, setOrganizationName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === 'signin') {
        await login(email, password);
      } else {
        await register(email, password, displayName || undefined, organizationName || undefined);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'sign-in failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page" aria-label="Sign in">
      <section className="auth-card">
        <header>
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <h1>{mode === 'signin' ? 'Sign in to smart-edit' : 'Create your workspace'}</h1>
          <p className="tiny">
            Accounts, organisations and departments are stored by this server. Passwords are hashed
            with argon2id and the session is an HttpOnly cookie.
          </p>
        </header>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            Email
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              name="password"
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              required
              minLength={mode === 'register' ? 8 : undefined}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {mode === 'register' ? (
            <>
              <label>
                Display name
                <input
                  name="display_name"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </label>
              <label>
                Organisation name
                <input
                  name="organization_name"
                  value={organizationName}
                  onChange={(event) => setOrganizationName(event.target.value)}
                />
              </label>
            </>
          ) : null}
          {error ? (
            <p className="notice notice--warn" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="primary" disabled={busy}>
            {busy ? 'Working…' : mode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <footer>
          {mode === 'signin' ? (
            <button type="button" className="link" onClick={() => setMode('register')}>
              No account yet? Create one
            </button>
          ) : (
            <button type="button" className="link" onClick={() => setMode('signin')}>
              Already have an account? Sign in
            </button>
          )}
        </footer>
      </section>
    </main>
  );
}