export const DEMO_MODE_KEY = 'smart-edit:demo-mode';

function storage(): Storage | null {
  try {
    return typeof globalThis.localStorage !== 'undefined' ? globalThis.localStorage : null;
  } catch {
    return null;
  }
}

export function readDemoMode(): boolean {
  try {
    return storage()?.getItem(DEMO_MODE_KEY) === '1';
  } catch {
    return false;
  }
}

/** Returns false when the preference could not be persisted. */
export function writeDemoMode(enabled: boolean): boolean {
  try {
    const target = storage();
    if (!target) return false;
    if (enabled) target.setItem(DEMO_MODE_KEY, '1');
    else target.removeItem(DEMO_MODE_KEY);
    return true;
  } catch {
    return false;
  }
}