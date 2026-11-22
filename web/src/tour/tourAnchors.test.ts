/**
 * Anchor guard: every `data-tour` selector used by the core tour must exist in the app source.
 * Renaming a control without updating the tour fails here instead of silently breaking the demo.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { CORE_TOUR } from './tours/core';
import { TOURS } from './catalog';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const TOUR_DIR = dirname(fileURLToPath(import.meta.url));

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });

const files = walk(SRC).filter(
  (file) =>
    /\.(ts|tsx)$/.test(file) &&
    !/\.test\./.test(file) &&
    !/\.d\.ts$/.test(file) &&
    // Exclude the tour module itself: a selector string in core.ts must not satisfy its own guard.
    !file.startsWith(TOUR_DIR),
);
const source = files.map((file) => readFileSync(file, 'utf8')).join('\n');

const anchors = new Set<string>();
for (const tour of TOURS) {
  for (const step of tour.steps) {
    const selectors: string[] = [];
    if (step.target) selectors.push(step.target);
    if (step.action && 'selector' in step.action) selectors.push(step.action.selector);
    if (step.until && 'selector' in step.until) selectors.push(step.until.selector);
    for (const selector of selectors) {
      const match = selector.match(/data-tour="([^"]+)"/);
      if (match) anchors.add(match[1]);
    }
  }
}

const DYNAMIC_PREFIXES = [
  'tab-',
  'approval-tab-',
  'topbar-',
  'automation-area-',
  'automation-sandbox-tab-',
];

describe('tour anchors', () => {
  it('offers the expected tours', () => {
    expect(TOURS.map((tour) => tour.id)).toEqual([
      'core',
      'lifecycle-applicant',
      'lifecycle-first',
      'lifecycle-second',
      'audit',
      'legal',
      'approval',
      'automation',
    ]);
  });

  it('ships the lifecycle parts in execution order', () => {
    const ids = TOURS.map((tour) => tour.id);
    expect(ids.indexOf('lifecycle-applicant')).toBeLessThan(ids.indexOf('lifecycle-first'));
    expect(ids.indexOf('lifecycle-first')).toBeLessThan(ids.indexOf('lifecycle-second'));
    const applicant = TOURS.find((tour) => tour.id === 'lifecycle-applicant');
    expect(applicant?.steps[0]?.id).toBe('role');
    expect(applicant?.steps.some((step) => step.id === 'new-document')).toBe(true);
    const first = TOURS.find((tour) => tour.id === 'lifecycle-first');
    expect(first?.steps.some((step) => step.id === 'role')).toBe(true);
    const second = TOURS.find((tour) => tour.id === 'lifecycle-second');
    expect(second?.steps.at(-1)?.title).toContain('Lifecycle complete');
  });

  it('finds a meaningful number of anchors', () => {
    expect(anchors.size).toBeGreaterThan(12);
  });

  it('asks for the edit lock before it asks for content', () => {
    const ids = CORE_TOUR.steps.map((step) => step.id);
    expect(ids.indexOf('lock')).toBeGreaterThan(-1);
    expect(ids.indexOf('lock')).toBeLessThan(ids.indexOf('paste'));
  });

  it('skips the submission segment when the draft is already submitted', () => {
    const submit = CORE_TOUR.steps.find((step) => step.id === 'submit');
    const confirm = CORE_TOUR.steps.find((step) => step.id === 'confirm-submit');
    expect(submit?.skipIf?.length ?? 0).toBeGreaterThan(0);
    expect(confirm?.optional).toBe(true);
  });

  it('every anchor exists in the app source', () => {
    for (const anchor of anchors) {
      const prefix = DYNAMIC_PREFIXES.find((item) => anchor.startsWith(item));
      if (prefix) {
        // Tabs and topbar entries are generated; the template literal is the anchor.
        expect(source.includes(`data-tour={\`${prefix}`)).toBe(true);
        continue;
      }
      expect(source.includes(`data-tour="${anchor}"`), `missing anchor ${anchor}`).toBe(true);
    }
  });

  it('the launcher button is wired in the shell', () => {
    expect(source.includes('data-tour="tour-launcher"')).toBe(true);
  });

  it('guards the automation tour by the RBAC-gated tab and never sends', () => {
    const tour = TOURS.find((item) => item.id === 'automation');
    expect(tour).toBeTruthy();
    // The tab is hidden (not disabled) without automation.view: every step that reveals something
    // must skip instead of failing (the centered closing step has no target and always runs).
    for (const step of tour?.steps ?? []) {
      if (!step.target && !step.action) continue;
      const guard = (step.skipIf ?? []).some(
        (predicate) =>
          predicate.kind === 'absent' && predicate.selector.includes('data-tour="tab-automation"'),
      );
      expect(guard, `step ${step.id} is not guarded`).toBe(true);
    }
    // The walkthrough explains Send; it must never click it or ask for the submission approval.
    expect(tour?.steps.some((step) => step.requiresApprovalAuto)).toBe(false);
    expect(
      tour?.steps.some(
        (step) => step.action && 'selector' in step.action && /send/.test(step.action.selector),
      ),
    ).toBe(false);
  });
});