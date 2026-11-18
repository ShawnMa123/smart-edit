import { seedDemoState, type DemoState } from './demoData';

export const DEMO_STORE_KEY = 'smart-edit:demo:collaboration:v1';

const USER_IDS = new Set(['applicant', 'ops', 'compliance', 'lawyer']);

function isDemoState(value: unknown): value is DemoState {
  if (typeof value !== 'object' || value === null) return false;
  const state = value as Partial<DemoState>;
  return (
    state.schemaVersion === 1 &&
    typeof state.currentUserId === 'string' &&
    USER_IDS.has(state.currentUserId) &&
    (state.guestStatus === 'invited' ||
      state.guestStatus === 'active' ||
      state.guestStatus === 'revoked') &&
    Array.isArray(state.comments) &&
    typeof state.approval === 'object' &&
    state.approval !== null &&
    Array.isArray(state.activity)
  );
}

function defaultStorage(): Storage {
  try {
    if (typeof globalThis.localStorage !== 'undefined' && globalThis.localStorage) {
      return globalThis.localStorage;
    }
  } catch {
    // Restricted contexts throw on access; fall through to memory.
  }
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

export interface DemoStore {
  read(): DemoState | null;
  write(state: DemoState): void;
  reset(): DemoState;
  available(): boolean;
}

export function createDemoStore(storage: Storage = defaultStorage()): DemoStore {
  let memory = seedDemoState();
  let usable = true;

  const write = (state: DemoState): void => {
    memory = state;
    if (!usable) return;
    try {
      storage.setItem(DEMO_STORE_KEY, JSON.stringify(state));
    } catch {
      usable = false;
    }
  };

  return {
    read() {
      if (!usable) return memory;
      try {
        const raw = storage.getItem(DEMO_STORE_KEY);
        if (!raw) return null;
        const parsed: unknown = JSON.parse(raw);
        if (!isDemoState(parsed)) {
          usable = false;
          return memory;
        }
        memory = parsed;
        return parsed;
      } catch {
        usable = false;
        return memory;
      }
    },

    write,

    reset() {
      const next = seedDemoState();
      usable = true;
      write(next);
      return next;
    },

    available() {
      return usable;
    },
  };
}

export const demoStore = createDemoStore();