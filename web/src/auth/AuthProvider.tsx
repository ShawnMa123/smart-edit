/**
 * Auth context (design D9 / task 6.1).
 *
 * Statuses:
 * - `loading` while `GET /auth/me` is in flight;
 * - `authenticated` with the server-derived profile;
 * - `unauthenticated` → the app renders the login page;
 * - `unavailable` when the server runs `AUTH_MODE=fake` (or is unreachable), so the existing local
 *   demo keeps working without pretending anyone is signed in.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { ApiError } from '../api/errors';
import { DEFAULT_WORKSPACE } from '../api/assistantTypes';
import type { AuthProfile } from '../api/identityTypes';
import * as api from '../api/identity';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'unavailable';

export interface AuthContextValue {
  status: AuthStatus;
  profile: AuthProfile | null;
  error: string | null;
  workspaceId: string;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string, organizationName?: string) => Promise<void>;
  logout: () => Promise<void>;
  switchOrg: (orgId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const isFakeMode = (error: unknown): boolean =>
  error instanceof ApiError && (error.code === 'AUTH_MODE_FAKE' || error.status === 0);

interface AuthProviderProps {
  children: ReactNode;
  /** Injected in tests. */
  fetchImpl?: typeof fetch;
  /** Tests can start from a known status; production probes on mount. */
  initialStatus?: AuthStatus;
  initialProfile?: AuthProfile | null;
  autoProbe?: boolean;
}

export function AuthProvider({
  children,
  fetchImpl,
  initialStatus,
  initialProfile = null,
  autoProbe = import.meta.env?.MODE !== 'test',
}: AuthProviderProps) {
  const [status, setStatus] = useState<AuthStatus>(
    initialStatus ?? (autoProbe ? 'loading' : 'unavailable'),
  );
  const [profile, setProfile] = useState<AuthProfile | null>(initialProfile);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.authMe({ fetchImpl });
      setProfile(next);
      setStatus('authenticated');
      setError(null);
    } catch (caught) {
      if (isFakeMode(caught)) {
        setStatus('unavailable');
        setProfile(null);
        setError(null);
        return;
      }
      if (caught instanceof ApiError && caught.status === 401) {
        setStatus('unauthenticated');
        setProfile(null);
        setError(null);
        return;
      }
      // A network failure must not lock the local demo behind a login form.
      setStatus('unavailable');
      setProfile(null);
      setError(caught instanceof Error ? caught.message : 'authentication is unavailable');
    }
  }, [fetchImpl]);

  useEffect(() => {
    if (!autoProbe) return;
    void refresh();
  }, [autoProbe, refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const next = await api.login(email, password, { fetchImpl });
      setProfile(next);
      setStatus('authenticated');
      setError(null);
    },
    [fetchImpl],
  );

  const register = useCallback(
    async (email: string, password: string, displayName?: string, organizationName?: string) => {
      const next = await api.register(email, password, displayName, organizationName, { fetchImpl });
      setProfile(next);
      setStatus('authenticated');
      setError(null);
    },
    [fetchImpl],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout({ fetchImpl });
    } finally {
      setProfile(null);
      setStatus('unauthenticated');
    }
  }, [fetchImpl]);

  const switchOrg = useCallback(
    async (orgId: string) => {
      const next = await api.switchOrganization(orgId, { fetchImpl });
      setProfile(next);
    },
    [fetchImpl],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      profile,
      error,
      workspaceId: profile?.active_org?.workspace_id ?? DEFAULT_WORKSPACE,
      login,
      register,
      logout,
      switchOrg,
      refresh,
    }),
    [status, profile, error, login, register, logout, switchOrg, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value) return value;
  // Components rendered outside the provider (isolated tests) behave like the fake mode.
  return {
    status: 'unavailable',
    profile: null,
    error: null,
    workspaceId: DEFAULT_WORKSPACE,
    login: async () => undefined,
    register: async () => undefined,
    logout: async () => undefined,
    switchOrg: async () => undefined,
    refresh: async () => undefined,
  };
}

export { AuthContext };