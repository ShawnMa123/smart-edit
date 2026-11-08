/**
 * Browser-local, append-only version history (design D4).
 *
 * Storage is `localStorage`, per browser, unsigned, capped — the pane says so. Restoring a version
 * only reads it: history is never rewritten, and capturing again always creates a new entry (the
 * spirit of VER-06, without pretending to be a server-side version store).
 *
 * The `Storage` is injectable because Node ≥ 22 exposes a global `localStorage` getter that is
 * unavailable without `--localstorage-file`, which would otherwise make the store untestable.
 */

export interface VersionEntry {
  id: string;
  label: string;
  digest: string;
  createdAt: string;
  chars: number;
  text: string;
}

export interface CaptureInput {
  digest: string;
  text: string;
  label?: string;
}

export const MAX_VERSIONS = 20;

/** Minimal in-memory `Storage`, used when the environment has no localStorage. */
export function memoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    clear: () => entries.clear(),
    getItem: (key: string) => entries.get(key) ?? null,
    key: (index: number) => Array.from(entries.keys())[index] ?? null,
    removeItem: (key: string) => {
      entries.delete(key);
    },
    setItem: (key: string, value: string) => {
      entries.set(key, value);
    },
  };
}

export function defaultStorage(): Storage {
  try {
    if (typeof globalThis.localStorage !== 'undefined' && globalThis.localStorage) {
      return globalThis.localStorage;
    }
  } catch {
    // Accessing the getter can throw in restricted contexts; fall through to memory.
  }
  return memoryStorage();
}

export interface VersionStore {
  list(documentId: string): VersionEntry[];
  get(documentId: string, id: string): VersionEntry | null;
  restore(documentId: string, id: string): string | null;
  capture(documentId: string, input: CaptureInput, now?: Date): VersionEntry;
  clear(documentId: string): void;
}

export function createVersionStore(storage: Storage = defaultStorage()): VersionStore {
  const storageKey = (documentId: string): string => `smart-edit:versions:${documentId}`;

  const read = (documentId: string): VersionEntry[] => {
    try {
      const raw = storage.getItem(storageKey(documentId));
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as VersionEntry[]) : [];
    } catch {
      return [];
    }
  };

  const write = (documentId: string, entries: VersionEntry[]): void => {
    storage.setItem(storageKey(documentId), JSON.stringify(entries));
  };

  return {
    list(documentId) {
      return read(documentId);
    },

    get(documentId, id) {
      return read(documentId).find((entry) => entry.id === id) ?? null;
    },

    restore(documentId, id) {
      return read(documentId).find((entry) => entry.id === id)?.text ?? null;
    },

    capture(documentId, input, now = new Date()) {
      const entries = read(documentId);
      const version: VersionEntry = {
        id: `v-${now.getTime()}-${entries.length + 1}`,
        label: input.label?.trim() || `Version ${entries.length + 1}`,
        digest: input.digest,
        createdAt: now.toISOString(),
        chars: input.text.length,
        text: input.text,
      };
      write(documentId, [version, ...entries].slice(0, MAX_VERSIONS));
      return version;
    },

    clear(documentId) {
      storage.removeItem(storageKey(documentId));
    },
  };
}

/** The app-wide store; components use this one. */
export const versionStore = createVersionStore();