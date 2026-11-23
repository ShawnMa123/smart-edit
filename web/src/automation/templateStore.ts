/**
 * Browser-local document-template snapshots (design D13).
 *
 * Templates live in `localStorage`, per browser, capped, and are deliberately NOT a server-side
 * template registry — the UI must say so. The `Storage` is injectable because Node ≥ 22 exposes a
 * `localStorage` getter that is unavailable without `--localstorage-file`, which would otherwise make
 * the store untestable.
 */

import type { Provenance, RichDocument } from '../rich/richDocument';
import { isRichDocument } from '../rich/richDocument';
import { defaultStorage } from '../versionStore';

export const TEMPLATE_STORAGE_KEY = 'smart-edit:automation-templates';
export const TEMPLATE_SCHEMA_VERSION = 1;
/** Newest-first cap; the oldest template is evicted when a capture exceeds it. */
export const MAX_TEMPLATES = 20;
export const MAX_TEMPLATE_NAME = 80;
/** The summary is for display only; keep it bounded. */
const MAX_VARIABLES_LISTED = 20;

export type TemplateValueType = 'string' | 'amount' | 'date' | 'currency';

/** Where the captured content came from. Never claim more than the stored provenance. */
export type TemplateSource =
  | { kind: 'imported'; provenance: Provenance; note?: string }
  | { kind: 'edited' };

export interface TemplateVariableSummary {
  label: string;
  valueType: TemplateValueType;
  required: boolean;
}

export interface TemplateRecord {
  id: string;
  name: string;
  version: string;
  source: TemplateSource;
  boundRevision: number | null;
  charCount: number;
  variables: TemplateVariableSummary[];
  capturedAt: string;
  /** Captured snapshot. Later edits to the working document never touch it. */
  rich: RichDocument;
  /** `false` means browser storage rejected the write; the record lives in this session only. */
  persisted: boolean;
}

export type TemplateStoreIssue = 'unreadable' | 'unavailable';

export interface CaptureTemplateInput {
  name: string;
  document: RichDocument;
  source: TemplateSource;
  revision: number | null;
  charCount: number;
  variables: TemplateVariableSummary[];
  now?: Date;
}

export type CaptureTemplateResult =
  | { ok: true; record: TemplateRecord; persisted: boolean }
  | { ok: false; reason: 'blank_name' };

export interface UpdateTemplateInput {
  document: RichDocument;
  source: TemplateSource;
  revision: number | null;
  charCount: number;
  variables: TemplateVariableSummary[];
  now?: Date;
}

export type UpdateTemplateResult =
  | { ok: true; record: TemplateRecord; persisted: boolean }
  | { ok: false; reason: 'not_found' };

export type RenameTemplateResult =
  | { ok: true; record: TemplateRecord; persisted: boolean }
  | { ok: false; reason: 'blank_name' | 'not_found' };

export interface TemplateStore {
  list(): TemplateRecord[];
  get(id: string): TemplateRecord | null;
  capture(input: CaptureTemplateInput): CaptureTemplateResult;
  update(id: string, input: UpdateTemplateInput): UpdateTemplateResult;
  rename(id: string, name: string): RenameTemplateResult;
  remove(id: string): boolean;
  issue(): TemplateStoreIssue | null;
  nextVersion(): string;
}

interface StorePayload {
  schemaVersion: number;
  nextSequence: number;
  templates: TemplateRecord[];
}

const emptyPayload = (): StorePayload => ({
  schemaVersion: TEMPLATE_SCHEMA_VERSION,
  nextSequence: 0,
  templates: [],
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const VALUE_TYPES = new Set(['string', 'amount', 'date', 'currency']);
const PROVENANCE = new Set(['deterministic', 'heuristic', 'fallback']);

const normalizeName = (value: string): string => value.trim().slice(0, MAX_TEMPLATE_NAME);

function isSource(value: unknown): value is TemplateSource {
  if (!isRecord(value)) return false;
  if (value.kind === 'edited') return true;
  return (
    value.kind === 'imported' &&
    typeof value.provenance === 'string' &&
    PROVENANCE.has(value.provenance) &&
    (value.note === undefined || typeof value.note === 'string')
  );
}

function isVariableSummary(value: unknown): value is TemplateVariableSummary {
  return (
    isRecord(value) &&
    typeof value.label === 'string' &&
    value.label.length > 0 &&
    typeof value.valueType === 'string' &&
    VALUE_TYPES.has(value.valueType) &&
    typeof value.required === 'boolean'
  );
}

function isStoredTemplate(value: unknown): value is TemplateRecord {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    value.id.length > 0 &&
    typeof value.name === 'string' &&
    value.name.length > 0 &&
    typeof value.version === 'string' &&
    /^v\d+$/.test(value.version) &&
    isSource(value.source) &&
    (value.boundRevision === null || typeof value.boundRevision === 'number') &&
    typeof value.charCount === 'number' &&
    Number.isFinite(value.charCount) &&
    Array.isArray(value.variables) &&
    value.variables.every(isVariableSummary) &&
    typeof value.capturedAt === 'string' &&
    isRichDocument(value.rich)
  );
}

/** A snapshot copy: later mutation of the working document must not change a template. */
const snapshot = (document: RichDocument): RichDocument =>
  JSON.parse(JSON.stringify(document)) as RichDocument;

const versionNumber = (version: string): number => Number(version.replace(/^v/, '')) || 0;

const sortTemplates = (templates: TemplateRecord[]): TemplateRecord[] =>
  [...templates].sort((left, right) => {
    if (left.capturedAt === right.capturedAt) return right.id.localeCompare(left.id);
    return right.capturedAt.localeCompare(left.capturedAt);
  });

/** Same id/name, new snapshot and version (D18). */
const refreshedRecord = (
  existing: TemplateRecord,
  sequence: number,
  input: UpdateTemplateInput,
): TemplateRecord => ({
  ...existing,
  version: `v${sequence}`,
  source: input.source,
  boundRevision: input.revision,
  charCount: Math.max(0, Math.round(input.charCount)),
  variables: input.variables.slice(0, MAX_VARIABLES_LISTED),
  capturedAt: (input.now ?? new Date()).toISOString(),
  rich: snapshot(input.document),
});

export function createTemplateStore(storage: Storage = defaultStorage()): TemplateStore {
  /** Records that could not be written to browser storage stay visible for this session. */
  const sessionOnly: TemplateRecord[] = [];
  /** Deletes that could not be persisted still disappear from this session. */
  const removedIds = new Set<string>();
  let issue: TemplateStoreIssue | null = null;
  /** Keeps versions increasing even when a write failed, so a retry never reuses vN. */
  let sessionSequence = 0;

  const read = (): StorePayload => {
    let raw: string | null;
    try {
      raw = storage.getItem(TEMPLATE_STORAGE_KEY);
    } catch {
      issue = 'unavailable';
      return emptyPayload();
    }
    if (!raw) return emptyPayload();

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      issue = 'unreadable';
      return emptyPayload();
    }

    const fresh = (value: unknown): value is StorePayload =>
      isRecord(value) &&
      value.schemaVersion === TEMPLATE_SCHEMA_VERSION &&
      Array.isArray(value.templates);

    if (!fresh(parsed)) {
      // A schema change or a malformed payload cannot be interpreted as templates.
      issue = 'unreadable';
      try {
        storage.removeItem(TEMPLATE_STORAGE_KEY);
      } catch {
        issue = 'unavailable';
      }
      return emptyPayload();
    }

    const templates: TemplateRecord[] = [];
    for (const entry of parsed.templates) {
      if (isStoredTemplate(entry)) {
        templates.push({ ...entry, persisted: true });
      } else {
        issue = 'unreadable';
      }
    }
    const nextSequence = Number.isFinite(Number(parsed.nextSequence))
      ? Math.max(0, Math.floor(Number(parsed.nextSequence)))
      : 0;
    return { schemaVersion: TEMPLATE_SCHEMA_VERSION, nextSequence, templates };
  };

  const persist = (templates: TemplateRecord[], nextSequence: number): boolean => {
    try {
      const payload: StorePayload = {
        schemaVersion: TEMPLATE_SCHEMA_VERSION,
        nextSequence,
        templates: templates.map((template) => ({ ...template, persisted: true })),
      };
      storage.setItem(TEMPLATE_STORAGE_KEY, JSON.stringify(payload));
      issue = null;
      return true;
    } catch {
      issue = 'unavailable';
      return false;
    }
  };

  const merge = (stored: TemplateRecord[]): TemplateRecord[] => {
    const byId = new Map<string, TemplateRecord>();
    for (const template of stored) byId.set(template.id, template);
    // Session-only records win over a stored copy with the same id (failed rename/delete).
    for (const template of sessionOnly) byId.set(template.id, template);
    return sortTemplates([...byId.values()]).slice(0, MAX_TEMPLATES);
  };

  const nextSequenceFor = (stored: StorePayload): number => {
    const highestVersion = stored.templates.reduce(
      (highest, template) => Math.max(highest, versionNumber(template.version)),
      0,
    );
    return Math.max(stored.nextSequence, highestVersion, sessionSequence) + 1;
  };

  const list = (): TemplateRecord[] =>
    merge(read().templates).filter((template) => !removedIds.has(template.id));

  return {
    list,

    get(id) {
      return list().find((template) => template.id === id) ?? null;
    },

    issue() {
      // Reading is what discovers an unusable payload, so probe before answering.
      list();
      return issue;
    },

    nextVersion() {
      return `v${nextSequenceFor(read())}`;
    },

    capture(input) {
      const name = normalizeName(input.name);
      if (!name) return { ok: false, reason: 'blank_name' };

      const stored = read();
      const sequence = nextSequenceFor(stored);
      const now = input.now ?? new Date();
      const record: TemplateRecord = {
        id: `tpl_${now.getTime()}_${sequence}`,
        name,
        version: `v${sequence}`,
        source: input.source,
        boundRevision: input.revision,
        charCount: Math.max(0, Math.round(input.charCount)),
        variables: input.variables.slice(0, MAX_VARIABLES_LISTED),
        capturedAt: now.toISOString(),
        rich: snapshot(input.document),
        persisted: true,
      };
      sessionSequence = Math.max(sessionSequence, sequence);

      const templates = sortTemplates([record, ...stored.templates]).slice(0, MAX_TEMPLATES);
      if (persist(templates, sequence)) {
        return { ok: true, record, persisted: true };
      }
      const sessionRecord: TemplateRecord = { ...record, persisted: false };
      sessionOnly.unshift(sessionRecord);
      if (sessionOnly.length > MAX_TEMPLATES) sessionOnly.pop();
      return { ok: true, record: sessionRecord, persisted: false };
    },

    update(id, input) {
      const stored = read();
      const sessionIndex = sessionOnly.findIndex((template) => template.id === id);
      const storedIndex = stored.templates.findIndex((template) => template.id === id);

      if (storedIndex < 0 && sessionIndex < 0) {
        return { ok: false, reason: 'not_found' };
      }

      const sequence = nextSequenceFor(stored);
      sessionSequence = Math.max(sessionSequence, sequence);

      if (storedIndex < 0) {
        const record = refreshedRecord(sessionOnly[sessionIndex], sequence, input);
        sessionOnly[sessionIndex] = { ...record, persisted: false };
        return { ok: true, record: sessionOnly[sessionIndex], persisted: false };
      }

      const record = refreshedRecord(stored.templates[storedIndex], sequence, input);
      const templates = [...stored.templates];
      templates[storedIndex] = record;
      const ordered = sortTemplates(templates).slice(0, MAX_TEMPLATES);
      if (persist(ordered, sequence)) {
        const stale = sessionOnly.findIndex((template) => template.id === id);
        if (stale >= 0) sessionOnly.splice(stale, 1);
        return { ok: true, record, persisted: true };
      }
      // The previous snapshot stays in storage; the new one is visible for this session only.
      sessionOnly.unshift({ ...record, persisted: false });
      return { ok: true, record: { ...record, persisted: false }, persisted: false };
    },

    rename(id, nextName) {
      const name = normalizeName(nextName);
      if (!name) return { ok: false, reason: 'blank_name' };

      const sessionIndex = sessionOnly.findIndex((template) => template.id === id);
      if (sessionIndex >= 0) {
        const record: TemplateRecord = { ...sessionOnly[sessionIndex], name };
        sessionOnly[sessionIndex] = record;
        return { ok: true, record, persisted: false };
      }

      const stored = read();
      const index = stored.templates.findIndex((template) => template.id === id);
      if (index < 0) return { ok: false, reason: 'not_found' };

      const record: TemplateRecord = { ...stored.templates[index], name };
      const templates = [...stored.templates];
      templates[index] = record;
      if (persist(templates, stored.nextSequence)) {
        return { ok: true, record, persisted: true };
      }
      // Keep the new name visible for this session even though the write failed.
      sessionOnly.unshift({ ...record, persisted: false });
      return { ok: true, record: { ...record, persisted: false }, persisted: false };
    },

    remove(id) {
      const existed =
        sessionOnly.some((template) => template.id === id) ||
        read().templates.some((template) => template.id === id);
      if (!existed) return false;

      removedIds.add(id);
      const sessionIndex = sessionOnly.findIndex((template) => template.id === id);
      if (sessionIndex >= 0) sessionOnly.splice(sessionIndex, 1);

      const stored = read();
      persist(
        stored.templates.filter((template) => template.id !== id),
        stored.nextSequence,
      );
      // Even if the write failed, `removedIds` keeps it hidden in this session.
      return true;
    },
  };
}

/** The app-wide store; the workbench uses this one unless a test injects another. */
export const automationTemplateStore = createTemplateStore();