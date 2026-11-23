/** Types for the identity/administration API (user-management). */

export interface Organization {
  org_id: string;
  workspace_id: string;
  name: string;
  authorization_version?: number;
}

export interface AuthProfile {
  user: { user_id: string; email: string; display_name: string };
  active_org: Organization | null;
  active_department_id: string | null;
  organizations: Organization[];
  roles: string[];
  permissions: string[];
}

export interface Department {
  department_id: string;
  org_id: string;
  parent_id: string | null;
  name: string;
}

export interface RoleAssignment {
  assignment_id: string;
  user_id: string;
  role_key: string;
  role_name?: string;
  scope_type: 'org' | 'department';
  scope_id: string;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  display_name: string;
  status: 'active' | 'suspended' | 'removed';
  department_id: string | null;
  department_name?: string | null;
  role_assignments: RoleAssignment[];
}

export interface Invite {
  invite_id: string;
  email: string;
  role_key: string;
  department_id: string | null;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  accept_path?: string;
}

export interface ActivityEvent {
  event_id: string;
  kind: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
  is_read: boolean;
  actor: { user_id: string | null; label: string; removed: boolean };
  department_id: string | null;
}

export interface ActivityPage {
  items: ActivityEvent[];
  next_cursor: string | null;
  unread_count: number;
}

export interface ApiKey {
  key_id: string;
  name: string;
  prefix: string;
  scopes_json?: string[];
  scopes?: string[];
  department_id: string | null;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  key_token?: string;
}

export interface RequestLog {
  log_id: number;
  api_key_id: string;
  method: string;
  path: string;
  status: number;
  latency_ms: number;
  created_at: string;
}

export interface UsageRow {
  day: string;
  api_key_id: string;
  status: number;
  requests: number;
  avg_latency_ms: number;
}