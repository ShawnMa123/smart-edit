/**
 * Browser-local activity log for the workspace shell (workspace-activity).
 *
 * This is deliberately not a server audit trail: entries are written to `localStorage` for the
 * current document, are unsigned and can be cleared by the operator. The store never records
 * questions, document text, citations, identities or credentials.
 */

export type ActivityKind =
  | 'import'
  | 'save'
  | 'capture'
  | 'restore'
  | 'audit'
  | 'knowledge'
  | 'template'
  | 'export-attempt'
  | 'conflict';

export interface ActivityEntry {
  id: string;
  kind: ActivityKind;
  action: string;
  detail: string;
  at: string;
  read: boolean;
  notifiable: boolean;
}

export type ActivityInput = Pick<ActivityEntry, 'kind' | 'action' | 'detail' | 'notifiable'>;

export interface ActivityStore {
  list(documentId: string): ActivityEntry[];
  record(documentId: string, input: ActivityInput, now?: Date): ActivityEntry;
  markAllRead(documentId: string): void;
  clear(documentId: string): void;
  available(): boolean;
}

export const MAX_ACTIVITY = 100;

/** Minimal in-memory Storage for tests and browsers without localStorage. */
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

function defaultStorage(): Storage {
  try {
    if (typeof globalThis.localStorage !== 'undefined' && globalThis.localStorage) {
      return globalThis.localStorage;
    }
  } catch {
    // Accessing the getter can throw in restricted contexts; fall through to memory.
  }
  return memoryStorage();
}

export function createActivityStore(storage: Storage = defaultStorage()): ActivityStore {
  const key = (documentId: string): string => `smart-edit:activity:${documentId}`;
  const memory = new Map<string, ActivityEntry[]>();
  let usable = true;
  let sequence = 0;

  const readMemory = (documentId: string): ActivityEntry[] => memory.get(documentId) ?? [];

  const read = (documentId: string): ActivityEntry[] => {
    if (!usable) return readMemory(documentId);
    try {
      const raw = storage.getItem(key(documentId));
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) throw new Error('activity is not an array');
      memory.set(documentId, parsed as ActivityEntry[]);
      return parsed as ActivityEntry[];
    } catch {
      // Corrupt or unavailable storage: keep working in memory and report the degradation.
      usable = false;
      return readMemory(documentId);
    }
  };

  const write = (documentId: string, entries: ActivityEntry[]): void => {
    memory.set(documentId, entries);
    if (!usable) return;
    try {
      storage.setItem(key(documentId), JSON.stringify(entries));
    } catch {
      usable = false;
    }
  };

  return {
    list(documentId) {
      return read(documentId);
    },

    record(documentId, input, now = new Date()) {
      const entry: ActivityEntry = {
        id: `a-${now.getTime()}-${sequence++}`,
        kind: input.kind,
        action: input.action,
        detail: input.detail,
        at: now.toISOString(),
        read: false,
        notifiable: input.notifiable,
      };
      write(documentId, [entry, ...read(documentId)].slice(0, MAX_ACTIVITY));
      return entry;
    },

    markAllRead(documentId) {
      const entries = read(documentId);
      if (entries.length === 0) return;
      write(
        documentId,
        entries.map((entry) => ({ ...entry, read: true })),
      );
    },

    clear(documentId) {
      memory.delete(documentId);
      if (!usable) return;
      try {
        storage.removeItem(key(documentId));
      } catch {
        usable = false;
      }
    },

    available() {
      return usable;
    },
  };
}

/** The app-wide store; components use this one. */
export const activityStore = createActivityStore();