/**
 * Identity API client (`/auth`, `/organizations`, `/activity`, `/developer`).
 *
 * All calls send cookies (`credentials: 'include'`) and every unsafe method carries the explicit
 * `X-Requested-With: smart-edit` CSRF signal the server requires (design D12).
 */

import { API_BASE } from './client';
import { ApiError } from './errors';
import type {
  ActivityPage,
  ApiKey,
  AuthProfile,
  Department,
  Invite,
  Member,
  Organization,
  RequestLog,
  RoleAssignment,
  UsageRow,
} from './identityTypes';

export interface IdentityOptions {
  fetchImpl?: typeof fetch;
}

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE';

async function request<T>(
  path: string,
  method: Method,
  body: unknown,
  options: IdentityOptions = {},
): Promise<T> {
  const doFetch = options.fetchImpl ?? globalThis.fetch;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-Requested-With'] = 'smart-edit';
  const response = await doFetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload ?? {}) as { code?: string; message?: string; detail?: unknown };
    throw new ApiError(
      response.status,
      error.code ?? `HTTP_${response.status}`,
      error.message ?? `request failed with status ${response.status}`,
      error.detail,
    );
  }
  return payload as T;
}

const qs = (params: Record<string, string | number | boolean | undefined>): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
};

export const authMe = (options?: IdentityOptions) =>
  request<AuthProfile>('/auth/me', 'GET', undefined, options);
export const login = (email: string, password: string, options?: IdentityOptions) =>
  request<AuthProfile>('/auth/login', 'POST', { email, password }, options);
export const register = (
  email: string,
  password: string,
  displayName: string | undefined,
  organizationName: string | undefined,
  options?: IdentityOptions,
) =>
  request<AuthProfile>(
    '/auth/register',
    'POST',
    { email, password, display_name: displayName, organization_name: organizationName },
    options,
  );
export const logout = (options?: IdentityOptions) =>
  request<unknown>('/auth/logout', 'POST', undefined, options);
export const switchOrganization = (orgId: string, options?: IdentityOptions) =>
  request<AuthProfile>('/auth/active-org', 'POST', { org_id: orgId }, options);

export const listOrganizations = (options?: IdentityOptions) =>
  request<Organization[]>('/organizations', 'GET', undefined, options);
export const listDepartments = (orgId: string, options?: IdentityOptions) =>
  request<Department[]>(`/organizations/${orgId}/departments`, 'GET', undefined, options);
export const createDepartment = (
  orgId: string,
  name: string,
  parentId: string | null,
  options?: IdentityOptions,
) =>
  request<Department>(
    `/organizations/${orgId}/departments`,
    'POST',
    { name, parent_id: parentId },
    options,
  );
export const listMembers = (orgId: string, options?: IdentityOptions) =>
  request<Member[]>(`/organizations/${orgId}/members`, 'GET', undefined, options);
export const updateMemberStatus = (
  orgId: string,
  userId: string,
  status: 'active' | 'suspended' | 'removed',
  options?: IdentityOptions,
) => request<Member>(`/organizations/${orgId}/members/${userId}`, 'PATCH', { status }, options);
export const assignRole = (
  orgId: string,
  input: { user_id: string; role_key: string; scope_type: 'org' | 'department'; scope_id: string },
  options?: IdentityOptions,
) => request<RoleAssignment>(`/organizations/${orgId}/role-assignments`, 'POST', input, options);
export const removeRoleAssignment = (orgId: string, assignmentId: string, options?: IdentityOptions) =>
  request<void>(`/organizations/${orgId}/role-assignments/${assignmentId}`, 'DELETE', undefined, options);
export const listInvites = (orgId: string, options?: IdentityOptions) =>
  request<Invite[]>(`/organizations/${orgId}/invites`, 'GET', undefined, options);
export const createInvite = (
  orgId: string,
  input: { email: string; role_key: string; department_id: string | null },
  options?: IdentityOptions,
) => request<Invite>(`/organizations/${orgId}/invites`, 'POST', input, options);
export const revokeInvite = (orgId: string, inviteId: string, options?: IdentityOptions) =>
  request<void>(`/organizations/${orgId}/invites/${inviteId}`, 'DELETE', undefined, options);

export const acceptInvite = (inviteToken: string, options?: IdentityOptions) =>
  request<{ org_id: string; department_id: string | null; role_key: string }>(
    '/invites/accept',
    'POST',
    { invite_token: inviteToken },
    options,
  );

export const listActivity = (
  orgId: string,
  input: { scope: 'all' | 'my_department'; unread: boolean; cursor?: string | null; limit?: number },
  options?: IdentityOptions,
) =>
  request<ActivityPage>(
    `/activity${qs({
      org_id: orgId,
      scope: input.scope,
      unread: input.unread,
      cursor: input.cursor ?? undefined,
      limit: input.limit ?? 20,
    })}`,
    'GET',
    undefined,
    options,
  );
/** Server-side unread badge; unlike the browser-local activity list this is org data. */
export const getActivityUnreadCount = (
  orgId: string,
  scope: 'all' | 'my_department' = 'all',
  options?: IdentityOptions,
) =>
  request<{ unread_count: number }>(
    `/activity/unread-count${qs({ org_id: orgId, scope })}`,
    'GET',
    undefined,
    options,
  ).then((result) => result.unread_count ?? 0);
export const markActivityRead = (orgId: string, eventId: string, options?: IdentityOptions) =>
  request<unknown>(`/activity/${eventId}/read${qs({ org_id: orgId })}`, 'POST', undefined, options);
export const markAllActivityRead = (
  orgId: string,
  scope: 'all' | 'my_department',
  options?: IdentityOptions,
) =>
  request<{ marked_read: number }>(
    `/activity/read-all${qs({ org_id: orgId, scope })}`,
    'POST',
    undefined,
    options,
  );

export const listApiKeys = (orgId: string, options?: IdentityOptions) =>
  request<ApiKey[]>(`/developer/organizations/${orgId}/keys`, 'GET', undefined, options);
export const createApiKey = (
  orgId: string,
  input: { name: string; department_id?: string | null; scopes?: string[]; expires_at?: string },
  options?: IdentityOptions,
) => request<ApiKey>(`/developer/organizations/${orgId}/keys`, 'POST', input, options);
export const revokeApiKey = (orgId: string, keyId: string, options?: IdentityOptions) =>
  request<void>(`/developer/organizations/${orgId}/keys/${keyId}`, 'DELETE', undefined, options);
export const listRequestLogs = (
  orgId: string,
  input: { limit?: number; offset?: number } = {},
  options?: IdentityOptions,
) =>
  request<{ items: RequestLog[]; total: number }>(
    `/developer/organizations/${orgId}/request-logs${qs({
      limit: input.limit ?? 20,
      offset: input.offset ?? 0,
    })}`,
    'GET',
    undefined,
    options,
  );
export const usageByDay = (orgId: string, days = 7, options?: IdentityOptions) =>
  request<UsageRow[]>(
    `/developer/organizations/${orgId}/usage${qs({ days })}`,
    'GET',
    undefined,
    options,
  );