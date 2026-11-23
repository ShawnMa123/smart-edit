/** Browser-local template store: snapshots, persistence, cap and honest failures (task 7.1). */

import { describe, expect, it } from 'vitest';

import {
  MAX_TEMPLATES,
  TEMPLATE_SCHEMA_VERSION,
  TEMPLATE_STORAGE_KEY,
  createTemplateStore,
  type CaptureTemplateInput,
  type TemplateRecord,
  type UpdateTemplateInput,
} from './templateStore';
import { memoryStorage } from '../versionStore';
import { plainTextToDocument } from '../rich/richDocument';

const AT = (day: number, hour = 10): Date => new Date(2026, 10, day, hour);

const captureInput = (over: Partial<CaptureTemplateInput> = {}): CaptureTemplateInput => {
  const document = plainTextToDocument('Amount: USD 500,000.00');
  return {
    name: 'Demand guarantee template',
    document,
    source: { kind: 'edited' },
    revision: 3,
    charCount: 'Amount: USD 500,000.00'.length,
    variables: [{ label: 'amount', valueType: 'amount', required: true }],
    ...over,
  };
};

const failingStorage = (mode: 'read' | 'write'): Storage => {
  const base = memoryStorage();
  return {
    ...base,
    getItem: (key: string) => {
      if (mode === 'read') throw new Error('storage blocked');
      return base.getItem(key);
    },
    setItem: (key: string, value: string) => {
      if (mode === 'write') throw new Error('quota exceeded');
      base.setItem(key, value);
    },
  } as Storage;
};

const readPayload = (storage: Storage): Record<string, unknown> =>
  JSON.parse(storage.getItem(TEMPLATE_STORAGE_KEY) ?? '{}') as Record<string, unknown>;

describe('templateStore capture', () => {
  it('stores metadata and a content snapshot in browser storage', () => {
    const storage = memoryStorage();
    const store = createTemplateStore(storage);

    const result = store.capture(captureInput({ now: AT(15) }));

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.persisted).toBe(true);
    expect(result.record).toMatchObject({
      name: 'Demand guarantee template',
      version: 'v1',
      boundRevision: 3,
      charCount: 22,
      persisted: true,
    });
    expect(result.record.source).toEqual({ kind: 'edited' });
    expect(result.record.variables).toEqual([
      { label: 'amount', valueType: 'amount', required: true },
    ]);
    expect(store.list()).toHaveLength(1);

    const payload = readPayload(storage);
    expect(payload.schemaVersion).toBe(TEMPLATE_SCHEMA_VERSION);
    expect(payload.nextSequence).toBe(1);
    expect((payload.templates as TemplateRecord[])[0].rich).toEqual(result.record.rich);
  });

  it('rejects a blank name without writing anything', () => {
    const store = createTemplateStore(memoryStorage());

    expect(store.capture(captureInput({ name: '   ' }))).toEqual({
      ok: false,
      reason: 'blank_name',
    });
    expect(store.list()).toHaveLength(0);
  });

  it('keeps the captured content when the working document changes afterwards', () => {
    const document = plainTextToDocument('Amount A');
    const store = createTemplateStore(memoryStorage());

    store.capture(captureInput({ document }));
    document.content.push({ type: 'paragraph', content: [{ type: 'text', text: 'extra' }] });

    expect(store.list()[0].rich.content).toHaveLength(1);
  });

  it('does not consume a version when the preview is rendered repeatedly', () => {
    const store = createTemplateStore(memoryStorage());

    expect(store.nextVersion()).toBe('v1');
    expect(store.nextVersion()).toBe('v1');
    const result = store.capture(captureInput({ now: AT(15) }));

    expect(result.ok && result.record.version).toBe('v1');
    expect(store.nextVersion()).toBe('v2');
  });
});

describe('templateStore persistence', () => {
  it('restores templates and continues version numbering after a reload', () => {
    const storage = memoryStorage();
    const first = createTemplateStore(storage);
    first.capture(captureInput({ name: 'First', now: AT(15) }));

    const reloaded = createTemplateStore(storage);

    expect(reloaded.list().map((template) => template.name)).toEqual(['First']);
    expect(reloaded.nextVersion()).toBe('v2');
    const second = reloaded.capture(captureInput({ name: 'Second', now: AT(16) }));
    expect(second.ok && second.record.version).toBe('v2');
    expect(reloaded.list().map((template) => template.name)).toEqual(['Second', 'First']);
  });

  it('keeps at most 20 templates, newest first, evicting the oldest', () => {
    const storage = memoryStorage();
    const store = createTemplateStore(storage);

    for (let index = 1; index <= MAX_TEMPLATES + 2; index += 1) {
      store.capture(captureInput({ name: `Template ${index}`, now: AT(index) }));
    }

    const names = store.list().map((template) => template.name);
    expect(names).toHaveLength(MAX_TEMPLATES);
    expect(names[0]).toBe(`Template ${MAX_TEMPLATES + 2}`);
    expect(names).not.toContain('Template 1');
    expect(readPayload(storage).nextSequence).toBe(MAX_TEMPLATES + 2);
  });
describe('templateStore failure paths', () => {
  it('reports unreadable JSON and still allows a new capture', () => {
    const storage = memoryStorage();
    storage.setItem(TEMPLATE_STORAGE_KEY, '{not json');
    const store = createTemplateStore(storage);

    expect(store.list()).toEqual([]);
    expect(store.issue()).toBe('unreadable');
    expect(store.capture(captureInput({ now: AT(15) })).ok).toBe(true);
    expect(store.list()).toHaveLength(1);
  });

  it('clears a payload from an older schema instead of guessing its shape', () => {
    const storage = memoryStorage();
    storage.setItem(
      TEMPLATE_STORAGE_KEY,
      JSON.stringify({ schemaVersion: 0, nextSequence: 5, templates: [{ id: 'old' }] }),
    );
    const store = createTemplateStore(storage);

    expect(store.list()).toEqual([]);
    expect(store.issue()).toBe('unreadable');
    expect(storage.getItem(TEMPLATE_STORAGE_KEY)).toBeNull();
  });

  it('keeps valid entries and reports invalid ones instead of fabricating templates', () => {
    const storage = memoryStorage();
    const seeded = createTemplateStore(storage);
    seeded.capture(captureInput({ name: 'Valid', now: AT(15) }));
    const payload = readPayload(storage);
    storage.setItem(
      TEMPLATE_STORAGE_KEY,
      JSON.stringify({ ...payload, templates: [...(payload.templates as unknown[]), { id: 'broken' }] }),
    );

    const store = createTemplateStore(storage);
    expect(store.list().map((template) => template.name)).toEqual(['Valid']);
    expect(store.issue()).toBe('unreadable');
  });

  it('reports unavailable storage and keeps captures session-only', () => {
    const storage = memoryStorage();
    storage.setItem(TEMPLATE_STORAGE_KEY, '');
    const blocked = failingStorage('read');
    const reader = createTemplateStore(blocked);

    expect(reader.list()).toEqual([]);
    expect(reader.issue()).toBe('unavailable');

    const writer = createTemplateStore(failingStorage('write'));
    const first = writer.capture(captureInput({ name: 'Session A', now: AT(15) }));
    const second = writer.capture(captureInput({ name: 'Session B', now: AT(16) }));

    expect(first.ok && first.persisted).toBe(false);
    expect(second.ok && second.persisted).toBe(false);
    expect(second.ok && second.record.version).toBe('v2');
    expect(writer.list().map((template) => [template.name, template.persisted])).toEqual([
      ['Session B', false],
      ['Session A', false],
    ]);
    // Nothing was persisted: a fresh store on the same storage cannot see them.
    expect(createTemplateStore(failingStorage('write')).list()).toEqual([]);
  });
});

describe('templateStore rename and remove', () => {
  it('renames without changing the id, version or captured content, and persists it', () => {
    const storage = memoryStorage();
    const store = createTemplateStore(storage);
    const captured = store.capture(captureInput({ now: AT(15) }));
    if (!captured.ok) throw new Error('capture failed');
    const before = captured.record;

    const renamed = store.rename(before.id, 'Reviewed guarantee');

    expect(renamed.ok).toBe(true);
    if (!renamed.ok) return;
    expect(renamed.persisted).toBe(true);
    expect(renamed.record).toMatchObject({
      id: before.id,
      version: before.version,
      capturedAt: before.capturedAt,
      boundRevision: before.boundRevision,
      charCount: before.charCount,
    });
    expect(renamed.record.rich).toEqual(before.rich);
    expect(createTemplateStore(storage).list()[0].name).toBe('Reviewed guarantee');
  });

  it('rejects a blank rename and an unknown id', () => {
    const store = createTemplateStore(memoryStorage());
    const captured = store.capture(captureInput({ now: AT(15) }));
    if (!captured.ok) throw new Error('capture failed');

    expect(store.rename(captured.record.id, '   ')).toEqual({ ok: false, reason: 'blank_name' });
    expect(store.rename('missing', 'Name')).toEqual({ ok: false, reason: 'not_found' });
    expect(store.list()[0].name).toBe('Demand guarantee template');
  });

  it('removes a template from this browser and reports unknown ids', () => {
    const storage = memoryStorage();
    const store = createTemplateStore(storage);
    const captured = store.capture(captureInput({ now: AT(15) }));
    if (!captured.ok) throw new Error('capture failed');

    expect(store.remove(captured.record.id)).toBe(true);
    expect(store.list()).toEqual([]);
    expect(store.remove(captured.record.id)).toBe(false);
    expect(createTemplateStore(storage).list()).toEqual([]);
  });

  it('can rename and remove a session-only template', () => {
    const store = createTemplateStore(failingStorage('write'));
    const captured = store.capture(captureInput({ now: AT(15) }));
    if (!captured.ok) throw new Error('capture failed');

    const renamed = store.rename(captured.record.id, 'Session renamed');
    expect(renamed.ok && renamed.record.name).toBe('Session renamed');
    expect(store.list()[0].name).toBe('Session renamed');

    expect(store.remove(captured.record.id)).toBe(true);
    expect(store.list()).toEqual([]);
  });
});
const updateInput = (over: Partial<UpdateTemplateInput> = {}): UpdateTemplateInput => ({
  document: plainTextToDocument('Updated content'),
  source: { kind: 'edited' },
  revision: 9,
  charCount: 'Updated content'.length,
  variables: [],
  now: AT(20),
  ...over,
});

describe('templateStore update', () => {
  it('keeps id/name and replaces the snapshot with a new version', () => {
    const storage = memoryStorage();
    const store = createTemplateStore(storage);
    const captured = store.capture(captureInput({ name: 'Guarantee', now: AT(15) }));
    const other = store.capture(captureInput({ name: 'Other', now: AT(16) }));
    if (!captured.ok || !other.ok) throw new Error('seed failed');

    const updated = store.update(captured.record.id, updateInput());

    expect(updated.ok).toBe(true);
    if (!updated.ok) return;
    expect(updated.persisted).toBe(true);
    expect(updated.record).toMatchObject({
      id: captured.record.id,
      name: 'Guarantee',
      version: 'v3',
      boundRevision: 9,
      charCount: 'Updated content'.length,
      capturedAt: AT(20).toISOString(),
    });
    expect(store.get(captured.record.id)?.rich).toEqual(plainTextToDocument('Updated content'));
    expect(store.get(other.record.id)?.rich).toEqual(other.record.rich);
    expect(createTemplateStore(storage).get(captured.record.id)?.version).toBe('v3');
  });

  it('reports an unknown template instead of inventing one', () => {
    const store = createTemplateStore(memoryStorage());
    expect(store.update('missing', updateInput())).toEqual({ ok: false, reason: 'not_found' });
  });

  it('keeps a failed update session-only and restores the old snapshot on reload', () => {
    const storage = memoryStorage();
    const store = createTemplateStore(storage);
    const captured = store.capture(captureInput({ now: AT(15) }));
    if (!captured.ok) throw new Error('capture failed');

    const backed = memoryStorage();
    backed.setItem(TEMPLATE_STORAGE_KEY, storage.getItem(TEMPLATE_STORAGE_KEY) ?? '');
    const failing = createTemplateStore({
      ...backed,
      setItem: () => {
        throw new Error('quota');
      },
    } as Storage);

    const updated = failing.update(captured.record.id, updateInput());

    expect(updated.ok && updated.persisted).toBe(false);
    expect(failing.list()[0]).toMatchObject({ version: 'v2', persisted: false });
    expect(createTemplateStore(backed).get(captured.record.id)?.version).toBe('v1');
  });

  it('can update a session-only template', () => {
    const store = createTemplateStore(failingStorage('write'));
    const captured = store.capture(captureInput({ now: AT(15) }));
    if (!captured.ok) throw new Error('capture failed');

    const updated = store.update(captured.record.id, updateInput());

    expect(updated.ok && updated.persisted).toBe(false);
    expect(store.get(captured.record.id)?.version).toBe('v2');
    expect(store.get(captured.record.id)?.rich).toEqual(plainTextToDocument('Updated content'));
  });
});
});