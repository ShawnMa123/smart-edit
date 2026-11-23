/** Browser-local downstream systems: seed, CRUD, caps and honest failures (task 11.1). */

import { describe, expect, it } from 'vitest';

import {
  DOWNSTREAM_SCHEMA_VERSION,
  DOWNSTREAM_SYSTEMS_KEY,
  MAX_SPEC_BYTES,
  createDownstreamSystemStore,
  type DownstreamSystemInput,
} from './downstreamSystemStore';
import { memoryStorage } from '../versionStore';

const AT = (day: number): Date => new Date(2026, 10, day, 10);

const input = (over: Partial<DownstreamSystemInput> = {}): DownstreamSystemInput => ({
  name: 'Trade sandbox',
  baseUrl: 'https://sandbox.example.com/api',
  environment: 'sandbox',
  enabled: true,
  auth: { type: 'bearer', hint: 'mock token' },
  specText: '{"openapi":"3.0.0","paths":{}}',
  now: AT(15),
  ...over,
});

const failingStorage = (mode: 'read' | 'write'): Storage => {
  const base = memoryStorage();
  return {
    ...base,
    getItem: (key: string) => {
      if (mode === 'read') throw new Error('blocked');
      return base.getItem(key);
    },
    setItem: (key: string, value: string) => {
      if (mode === 'write') throw new Error('quota');
      base.setItem(key, value);
    },
  } as Storage;
};

describe('downstreamSystemStore seed', () => {
  it('seeds the mock presets with a bound OpenAPI spec', () => {
    const storage = memoryStorage();
    const store = createDownstreamSystemStore(storage);

    const systems = store.list();

    expect(systems).toHaveLength(2);
    expect(systems.find((system) => system.id === 'sys_trade_sandbox')).toMatchObject({
      name: 'Trade Intake sandbox',
      baseUrl: 'https://sandbox.trade.example/api',
      environment: 'sandbox',
      enabled: true,
      auth: { type: 'bearer', hint: 'mock token' },
    });
    expect(systems[0].specText).toContain('Trade Intake API');
    const payload = JSON.parse(storage.getItem(DOWNSTREAM_SYSTEMS_KEY) ?? '{}') as {
      schemaVersion: number;
    };
    expect(payload.schemaVersion).toBe(DOWNSTREAM_SCHEMA_VERSION);
  });

  it('does not re-seed after every system is deleted', () => {
    const storage = memoryStorage();
    const store = createDownstreamSystemStore(storage);
    for (const system of store.list()) {
      expect(store.remove(system.id)).toBe(true);
    }

    expect(store.list()).toEqual([]);
    expect(createDownstreamSystemStore(storage).list()).toEqual([]);
  });
});

describe('downstreamSystemStore CRUD', () => {
  it('creates, updates and removes a system persistently', () => {
    const storage = memoryStorage();
    const store = createDownstreamSystemStore(storage);

    const created = store.create(input({ name: 'Custom API', now: AT(20) }));
    expect(created.ok).toBe(true);
    if (!created.ok) return;
    expect(created.persisted).toBe(true);
    expect(created.record.auth).toEqual({ type: 'bearer', hint: 'mock token' });
    expect(created.record.auth).not.toHaveProperty('token');

    const updated = store.update(created.record.id, input({ name: 'Renamed API', enabled: false }));
    expect(updated.ok && updated.record.id).toBe(created.record.id);
    expect(store.get(created.record.id)).toMatchObject({
      name: 'Renamed API',
      enabled: false,
    });

    expect(store.remove(created.record.id)).toBe(true);
    expect(store.get(created.record.id)).toBeNull();
    expect(createDownstreamSystemStore(storage).get(created.record.id)).toBeNull();
  });

  it('rejects invalid names, URLs, auth, oversized specs and unknown ids', () => {
    const store = createDownstreamSystemStore(memoryStorage());

    expect(store.create(input({ name: '   ' }))).toEqual({ ok: false, reason: 'invalid_name' });
    expect(store.create(input({ baseUrl: 'ftp://example.com' }))).toEqual({
      ok: false,
      reason: 'invalid_url',
    });
    expect(
      store.create(input({ auth: { type: 'oauth' as 'bearer', hint: 'x' } })),
    ).toEqual({ ok: false, reason: 'invalid_auth' });
    expect(store.create(input({ specText: 'x'.repeat(MAX_SPEC_BYTES + 1) }))).toEqual({
      ok: false,
      reason: 'spec_too_large',
    });
    expect(store.update('missing', input())).toEqual({ ok: false, reason: 'not_found' });
  });

  it('caps the number of systems at 10', () => {
    const store = createDownstreamSystemStore(memoryStorage());
    // Two seeded systems + eight new ones.
    for (let index = 0; index < 8; index += 1) {
      expect(store.create(input({ name: `System ${index}`, now: AT(16 + index) })).ok).toBe(true);
    }
    expect(store.create(input({ name: 'One too many', now: AT(30) }))).toEqual({
      ok: false,
      reason: 'limit',
    });
  });
});

describe('downstreamSystemStore failure paths', () => {
  it('ignores corrupt entries and reports the storage issue', () => {
    const storage = memoryStorage();
    storage.setItem(DOWNSTREAM_SYSTEMS_KEY, '{oops');
    const store = createDownstreamSystemStore(storage);

    expect(store.list()).toEqual([]);
    expect(store.issue()).toBe('unreadable');
  });

  it('reports unavailable storage', () => {
    const store = createDownstreamSystemStore(failingStorage('read'));
    expect(store.list()).toEqual([]);
    expect(store.issue()).toBe('unavailable');
  });

  it('keeps a failed create session-only without claiming persistence', () => {
    const backing = memoryStorage();
    const seeded = createDownstreamSystemStore(backing);
    expect(seeded.list()).toHaveLength(2);

    const blocked = createDownstreamSystemStore({
      ...backing,
      setItem: () => {
        throw new Error('quota');
      },
    } as Storage);

    const created = blocked.create(input({ name: 'Session API', now: AT(20) }));
    expect(created.ok && created.persisted).toBe(false);
    expect(blocked.list().some((system) => system.name === 'Session API')).toBe(true);
    expect(createDownstreamSystemStore(backing).list().some((system) => system.name === 'Session API')).toBe(
      false,
    );
  });
});