-- 003_collaboration.sql — invites, activity events/reads, API keys and request logs.
-- Payloads never hold document text, passwords or raw tokens (design D7/D8).

CREATE TABLE IF NOT EXISTS invites (
  invite_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
  department_id TEXT REFERENCES departments(department_id) ON DELETE SET NULL,
  email TEXT NOT NULL,
  role_key TEXT NOT NULL REFERENCES roles(role_key),
  invited_by TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  accepted_at TIMESTAMPTZ,
  accepted_by TEXT,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS invites_org_idx ON invites (org_id);

CREATE TABLE IF NOT EXISTS activity_events (
  event_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
  department_id TEXT,
  actor_user_id TEXT,
  actor_label TEXT,
  kind TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_type TEXT,
  resource_id TEXT,
  detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS activity_events_org_time_idx
  ON activity_events (org_id, created_at DESC, event_id DESC);

CREATE TABLE IF NOT EXISTS activity_reads (
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  event_id TEXT NOT NULL REFERENCES activity_events(event_id) ON DELETE CASCADE,
  read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, event_id)
);

CREATE TABLE IF NOT EXISTS api_keys (
  key_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
  department_id TEXT,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL,
  scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_by TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_keys_org_idx ON api_keys (org_id);

CREATE TABLE IF NOT EXISTS api_request_logs (
  log_id BIGSERIAL PRIMARY KEY,
  api_key_id TEXT NOT NULL,
  org_id TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  status INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_request_logs_key_time_idx
  ON api_request_logs (api_key_id, created_at DESC);