-- 002_organization.sql — organizations, department tree + closure, memberships, roles.
-- Role rows are synced from app.identity.permissions by IdentityStore.sync_role_catalog().

CREATE TABLE IF NOT EXISTS organizations (
  org_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  slug TEXT UNIQUE,
  -- Bumped on every member/role/department change; long-running contexts compare it (design D5).
  authorization_version BIGINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- `ws_demo_01` keeps historical documents/assistant data readable (design D10, task 3.1).
-- The organisation id is the workspace id (design D2).
INSERT INTO organizations (org_id, workspace_id, name, slug)
VALUES ('ws_demo_01', 'ws_demo_01', 'Demo organisation', 'demo')
ON CONFLICT (org_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS departments (
  department_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES departments(department_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS departments_org_idx ON departments (org_id);
CREATE INDEX IF NOT EXISTS departments_parent_idx ON departments (parent_id);

-- Ancestor/descendant closure; every department is its own depth-0 row.
CREATE TABLE IF NOT EXISTS department_closure (
  ancestor_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
  descendant_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
  depth INTEGER NOT NULL CHECK (depth >= 0),
  PRIMARY KEY (ancestor_id, descendant_id)
);
CREATE INDEX IF NOT EXISTS department_closure_desc_idx ON department_closure (descendant_id);

CREATE TABLE IF NOT EXISTS memberships (
  membership_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  department_id TEXT REFERENCES departments(department_id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'removed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, user_id)
);
CREATE INDEX IF NOT EXISTS memberships_user_idx ON memberships (user_id);

CREATE TABLE IF NOT EXISTS roles (
  role_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scope_level TEXT NOT NULL CHECK (scope_level IN ('org', 'department'))
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role_key TEXT NOT NULL REFERENCES roles(role_key) ON DELETE CASCADE,
  permission TEXT NOT NULL,
  PRIMARY KEY (role_key, permission)
);

-- Additive only: no deny table. Revoking a role deletes the assignment (design D3).
CREATE TABLE IF NOT EXISTS role_assignments (
  assignment_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('org', 'department')),
  scope_id TEXT NOT NULL,
  role_key TEXT NOT NULL REFERENCES roles(role_key),
  granted_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, scope_type, scope_id, role_key)
);
CREATE INDEX IF NOT EXISTS role_assignments_user_org_idx ON role_assignments (user_id, org_id);
CREATE INDEX IF NOT EXISTS role_assignments_scope_idx ON role_assignments (org_id, scope_type, scope_id);