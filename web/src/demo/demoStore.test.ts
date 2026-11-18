import { describe, expect, it } from 'vitest';

import { memoryStorage } from '../versionStore';
import { DEMO_USERS, seedDemoState } from './demoData';
import { DEMO_STORE_KEY, createDemoStore } from './demoStore';

describe('demo store', () => {
  it('seeds four users, two comments, a DRAFT approval and sample activity', () => {
    const state = seedDemoState();
    expect(DEMO_USERS.map((user) => user.id)).toEqual([
      'applicant',
      'ops',
      'compliance',
      'lawyer',
    ]);
    expect(state.comments).toHaveLength(2);
    expect(state.approval.status).toBe('DRAFT');
    expect(state.approval.steps).toHaveLength(2);
    expect(state.activity.length).toBeGreaterThanOrEqual(4);
    expect(state.currentUserId).toBe('applicant');
  });

  it('reads, writes and resets the demo state without touching real activity', () => {
    const storage = memoryStorage();
    storage.setItem('smart-edit:activity:demo-document', '["real"]');
    const store = createDemoStore(storage);

    expect(store.read()).toBeNull();
    const next = { ...seedDemoState(), guestStatus: 'revoked' as const };
    store.write(next);
    expect(store.read()?.guestStatus).toBe('revoked');
    expect(storage.getItem(DEMO_STORE_KEY)).toContain('revoked');

    const seed = store.reset();
    expect(seed.guestStatus).toBe('active');
    expect(store.read()?.guestStatus).toBe('active');
    expect(storage.getItem('smart-edit:activity:demo-document')).toBe('["real"]');
  });

  it('reports corrupt storage and falls back to the in-memory seed', () => {
    const storage = memoryStorage();
    storage.setItem(DEMO_STORE_KEY, '{bad json');
    const store = createDemoStore(storage);

    expect(store.read()?.comments).toHaveLength(2);
    expect(store.available()).toBe(false);
  });
});