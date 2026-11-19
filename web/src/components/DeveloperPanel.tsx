/** Developer: API keys (shown once), request logs, usage; no Webhooks in v1 (task 8.4). */

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/errors';
import * as api from '../api/identity';
import type { ApiKey, RequestLog, UsageRow } from '../api/identityTypes';

interface DeveloperPanelProps {
  orgId: string;
  fetchImpl?: typeof fetch;
}

export function DeveloperPanel({ orgId, fetchImpl }: DeveloperPanelProps) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [logs, setLogs] = useState<RequestLog[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextKeys, nextLogs, nextUsage] = await Promise.all([
        api.listApiKeys(orgId, { fetchImpl }),
        api.listRequestLogs(orgId, { limit: 20 }, { fetchImpl }),
        api.usageByDay(orgId, 7, { fetchImpl }),
      ]);
      setKeys(nextKeys);
      setLogs(nextLogs.items);
      setUsage(nextUsage);
      setForbidden(false);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 403) {
        setForbidden(true);
      } else {
        setError(caught instanceof Error ? caught.message : 'could not load developer data');
      }
    }
  }, [fetchImpl, orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!name.trim()) return;
    try {
      const created = await api.createApiKey(orgId, { name: name.trim() }, { fetchImpl });
      setNewToken(created.key_token ?? null);
      setName('');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'could not create API key');
    }
  };

  const revoke = async (keyId: string) => {
    try {
      await api.revokeApiKey(orgId, keyId, { fetchImpl });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'could not revoke API key');
    }
  };

  if (forbidden) {
    return (
      <div className="empty-state" role="status">
        <strong>Developer access requires developer.manage</strong>
        <p className="tiny">Ask an organisation administrator to grant the permission.</p>
      </div>
    );
  }

  return (
    <div className="developer-panel">
      {error ? <p className="notice notice--warn">{error}</p> : null}

      <section aria-label="API keys">
        <h3>API keys</h3>
        <div className="inline-form">
          <input
            aria-label="API key name"
            placeholder="Key name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button type="button" className="primary" onClick={() => void create()}>
            Create key
          </button>
        </div>
        {newToken ? (
          <div className="notice" role="status">
            <strong>Copy this key now — it is shown only once.</strong>
            <code data-testid="new-api-key">{newToken}</code>
          </div>
        ) : null}
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Prefix</th>
              <th>Created</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key.key_id}>
                <td>{key.name}</td>
                <td>
                  <code>{key.prefix}…</code>
                </td>
                <td className="tiny">{new Date(key.created_at).toLocaleDateString()}</td>
                <td className="tiny">
                  {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'never'}
                </td>
                <td>
                  {key.revoked_at ? (
                    <span className="chip">revoked</span>
                  ) : (
                    <button type="button" className="link" onClick={() => void revoke(key.key_id)}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-label="Request logs">
        <h3>Request logs</h3>
        <p className="tiny">Method, path, status and latency only — request bodies are never stored.</p>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Method</th>
              <th>Path</th>
              <th>Status</th>
              <th>Latency</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => (
              <tr key={log.log_id}>
                <td className="tiny">{new Date(log.created_at).toLocaleString()}</td>
                <td>{log.method}</td>
                <td>
                  <code>{log.path}</code>
                </td>
                <td>{log.status}</td>
                <td>{log.latency_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-label="Usage">
        <h3>Usage (last 7 days)</h3>
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>Key</th>
              <th>Status</th>
              <th>Requests</th>
              <th>Avg latency</th>
            </tr>
          </thead>
          <tbody>
            {usage.map((row) => (
              <tr key={`${row.day}-${row.api_key_id}-${row.status}`}>
                <td>{row.day}</td>
                <td>
                  <code>{row.api_key_id}</code>
                </td>
                <td>{row.status}</td>
                <td>{row.requests}</td>
                <td>{row.avg_latency_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <p className="tiny">Webhooks are not available in this version.</p>
    </div>
  );
}