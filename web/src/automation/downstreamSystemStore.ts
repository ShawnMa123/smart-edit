/**
 * Browser-local downstream systems (design D20).
 *
 * A system binds a name/base URL/environment/auth hint to one OpenAPI spec. Storage follows the
 * templateStore pattern: injectable `Storage`, schema version, seeded mock presets, honest failure
 * handling. No real credentials are stored or accepted.
 */

import openapiSample from '../../../fixtures/automation/openapi_sample.json';
import presets from '../../../fixtures/automation/downstream_systems.json';
import { defaultStorage } from '../versionStore';

export const DOWNSTREAM_SYSTEMS_KEY = 'smart-edit:automation-downstream-systems';
export const DOWNSTREAM_SCHEMA_VERSION = 1;
export const MAX_SYSTEMS = 10;
export const MAX_SPEC_BYTES = 512 * 1024;
export const MAX_NAME = 80;
export const MAX_HINT = 80;

export type DownstreamEnvironment = 'sandbox' | 'production';
export type DownstreamAuthType = 'none' | 'api_key' | 'bearer';

export interface DownstreamAuth {
  type: DownstreamAuthType;
  /** A non-secret hint only ("mock token", "uses service account"). */
  hint?: string;
}

export interface DownstreamSystem {
  id: string;
  name: string;
  baseUrl: string;
  environment: DownstreamEnvironment;
  enabled: boolean;
  auth: DownstreamAuth;
  /** OpenAPI 3.x JSON bound to this system; may be empty until edited. */
  specText: string;
  specUpdatedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface DownstreamSystemInput {
  name: string;
  baseUrl: string;
  environment: DownstreamEnvironment;
  enabled: boolean;
  auth: DownstreamAuth;
  specText: string;
  now?: Date;
}

export type DownstreamSystemFailure =
  | 'invalid_name'
  | 'invalid_url'
  | 'invalid_auth'
  | 'spec_too_large'
  | 'limit'
  | 'not_found';

export type DownstreamSystemResult =
  | { ok: true; record: DownstreamSystem; persisted: boolean }
  | { ok: false; reason: DownstreamSystemFailure };

export type DownstreamSystemIssue = 'unreadable' | 'unavailable';

export interface DownstreamSystemStore {
  list(): DownstreamSystem[];
  get(id: string): DownstreamSystem | null;
  create(input: DownstreamSystemInput): DownstreamSystemResult;
  update(id: string, input: DownstreamSystemInput): DownstreamSystemResult;
  remove(id: string): boolean;
  issue(): DownstreamSystemIssue | null;
}

interface StorePayload {
  schemaVersion: number;
  systems: DownstreamSystem[];
}

interface FixtureSystem {
  id: string;
  name: string;
  baseUrl: string;
  environment: DownstreamEnvironment;
  enabled: boolean;
  auth: DownstreamAuth;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isFilled = (value: unknown, max = MAX_NAME): value is string =>
  typeof value === 'string' && value.trim().length > 0 && value.trim().length <= max;

const isHttpUrl = (value: string): boolean => {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
};

const byteLength = (value: string): number => new TextEncoder().encode(value).length;

const isAuth = (value: unknown): value is DownstreamAuth =>
  isRecord(value) &&
  ['none', 'api_key', 'bearer'].includes(String(value.type)) &&
  (value.hint === undefined ||
    (typeof value.hint === 'string' && value.hint.length <= MAX_HINT));

const isEnvironment = (value: unknown): value is DownstreamEnvironment =>
  value === 'sandbox' || value === 'production';

const isStoredSystem = (value: unknown): value is DownstreamSystem =>
  isRecord(value) &&
  isFilled(value.id, 128) &&
  isFilled(value.name) &&
  typeof value.baseUrl === 'string' &&
  isHttpUrl(value.baseUrl) &&
  isEnvironment(value.environment) &&
  typeof value.enabled === 'boolean' &&
  isAuth(value.auth) &&
  typeof value.specText === 'string' &&
  byteLength(value.specText) <= MAX_SPEC_BYTES &&
  typeof value.specUpdatedAt === 'string' &&
  typeof value.createdAt === 'string' &&
  typeof value.updatedAt === 'string';

const seedSystems = (now: Date): DownstreamSystem[] => {
  const stamp = now.toISOString();
  const specText = JSON.stringify(openapiSample);
  return (presets.systems as FixtureSystem[]).map((preset) => ({
    id: preset.id,
    name: preset.name,
    baseUrl: preset.baseUrl,
    environment: preset.environment,
    enabled: preset.enabled,
    auth: {
      type: preset.auth.type,
      ...(preset.auth.hint ? { hint: preset.auth.hint } : {}),
    },
    specText,
    specUpdatedAt: stamp,
    createdAt: stamp,
    updatedAt: stamp,
  }));
};

type NormalisedInput = Omit<DownstreamSystemInput, 'now'>;

const normalise = (
  input: DownstreamSystemInput,
): { ok: true; value: NormalisedInput } | { ok: false; reason: DownstreamSystemFailure } => {
  const name = input.name.trim().slice(0, MAX_NAME);
  if (!name) return { ok: false, reason: 'invalid_name' };
  const baseUrl = input.baseUrl.trim();
  if (!isHttpUrl(baseUrl)) return { ok: false, reason: 'invalid_url' };
  if (!isAuth(input.auth)) return { ok: false, reason: 'invalid_auth' };
  if (byteLength(input.specText) > MAX_SPEC_BYTES) return { ok: false, reason: 'spec_too_large' };
  return {
    ok: true,
    value: {
      name,
      baseUrl,
      environment: isEnvironment(input.environment) ? input.environment : 'sandbox',
      enabled: Boolean(input.enabled),
      auth: {
        type: input.auth.type,
        ...(input.auth.hint ? { hint: input.auth.hint.trim().slice(0, MAX_HINT) } : {}),
      },
      specText: input.specText,
    },
  };
}

export function createDownstreamSystemStore(
  storage: Storage = defaultStorage(),
): DownstreamSystemStore {
  const sessionSystems: DownstreamSystem[] = [];
  const removedIds = new Set<string>();
  let issue: DownstreamSystemIssue | null = null;
  let sequence = 0;

  const read = (): StorePayload => {
    let raw: string | null;
    try {
      raw = storage.getItem(DOWNSTREAM_SYSTEMS_KEY);
    } catch {
      issue = 'unavailable';
      return { schemaVersion: DOWNSTREAM_SCHEMA_VERSION, systems: [] };
    }

    if (raw === null) {
      const systems = seedSystems(new Date());
      const persisted = persist(systems);
      if (!persisted) {
        issue = 'unavailable';
      }
      return { schemaVersion: DOWNSTREAM_SCHEMA_VERSION, systems };
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      issue = 'unreadable';
      return { schemaVersion: DOWNSTREAM_SCHEMA_VERSION, systems: [] };
    }

    if (
      !isRecord(parsed) ||
      parsed.schemaVersion !== DOWNSTREAM_SCHEMA_VERSION ||
      !Array.isArray(parsed.systems)
    ) {
      issue = 'unreadable';
      try {
        storage.removeItem(DOWNSTREAM_SYSTEMS_KEY);
      } catch {
        issue = 'unavailable';
      }
      return { schemaVersion: DOWNSTREAM_SCHEMA_VERSION, systems: [] };
    }

    const systems: DownstreamSystem[] = [];
    for (const entry of parsed.systems) {
      if (isStoredSystem(entry)) {
        systems.push(entry);
      } else {
        issue = 'unreadable';
      }
    }
    return { schemaVersion: DOWNSTREAM_SCHEMA_VERSION, systems };
  };

  const persist = (systems: DownstreamSystem[]): boolean => {
    try {
      const payload: StorePayload = {
        schemaVersion: DOWNSTREAM_SCHEMA_VERSION,
        systems,
      };
      storage.setItem(DOWNSTREAM_SYSTEMS_KEY, JSON.stringify(payload));
      issue = null;
      return true;
    } catch {
      issue = 'unavailable';
      return false;
    }
  };

  const merge = (stored: DownstreamSystem[]): DownstreamSystem[] => {
    const byId = new Map<string, DownstreamSystem>();
    for (const system of stored) byId.set(system.id, system);
    for (const system of sessionSystems) byId.set(system.id, system);
    return [...byId.values()]
      .filter((system) => !removedIds.has(system.id))
      .sort((left, right) => left.name.localeCompare(right.name));
  };

  const list = (): DownstreamSystem[] => merge(read().systems);

  return {
    list,

    get(id) {
      return list().find((system) => system.id === id) ?? null;
    },

    issue() {
      list();
      return issue;
    },

    create(input) {
      const normalised = normalise(input);
      if (!normalised.ok) return normalised;
      const existing = list();
      if (existing.length >= MAX_SYSTEMS) return { ok: false, reason: 'limit' };

      const now = input.now ?? new Date();
      const stamp = now.toISOString();
      sequence += 1;
      const record: DownstreamSystem = {
        id: `sys_${now.getTime()}_${sequence}`,
        ...normalised.value,
        specUpdatedAt: stamp,
        createdAt: stamp,
        updatedAt: stamp,
      };
      const stored = read().systems;
      if (persist([...stored, record])) {
        return { ok: true, record, persisted: true };
      }
      sessionSystems.push(record);
      return { ok: true, record, persisted: false };
    },

    update(id, input) {
      const normalised = normalise(input);
      if (!normalised.ok) return normalised;

      const stored = read();
      const sessionIndex = sessionSystems.findIndex((system) => system.id === id);
      const storedIndex = stored.systems.findIndex((system) => system.id === id);
      if (storedIndex < 0 && sessionIndex < 0) return { ok: false, reason: 'not_found' };

      const existing =
        storedIndex >= 0 ? stored.systems[storedIndex] : sessionSystems[sessionIndex];
      const stamp = (input.now ?? new Date()).toISOString();
      const record: DownstreamSystem = {
        ...existing,
        ...normalised.value,
        specUpdatedAt: stamp,
        updatedAt: stamp,
      };

      if (storedIndex >= 0) {
        const systems = [...stored.systems];
        systems[storedIndex] = record;
        if (persist(systems)) {
          const stale = sessionSystems.findIndex((system) => system.id === id);
          if (stale >= 0) sessionSystems.splice(stale, 1);
          return { ok: true, record, persisted: true };
        }
      }

      if (sessionIndex >= 0) {
        sessionSystems[sessionIndex] = record;
      } else {
        sessionSystems.push(record);
      }
      return { ok: true, record, persisted: false };
    },

    remove(id) {
      const existed =
        sessionSystems.some((system) => system.id === id) ||
        read().systems.some((system) => system.id === id);
      if (!existed) return false;

      removedIds.add(id);
      const sessionIndex = sessionSystems.findIndex((system) => system.id === id);
      if (sessionIndex >= 0) sessionSystems.splice(sessionIndex, 1);

      const stored = read();
      persist(stored.systems.filter((system) => system.id !== id));
      return true;
    },
  };
}

/** The app-wide store. */
export const downstreamSystemStore = createDownstreamSystemStore();