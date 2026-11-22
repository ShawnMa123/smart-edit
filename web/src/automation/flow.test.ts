/** The guided order of the Server & Downstream panel (one next step at a time). */

import { describe, expect, it } from 'vitest';

import { automationFlow, type AutomationFlowInput } from './flow';

const base: AutomationFlowInput = {
  hasTemplate: true,
  variableCount: 6,
  hasConnector: true,
  hasSpec: true,
  unmappedRequired: 0,
  prepared: true,
  bodyIssues: 0,
};

describe('automationFlow', () => {
  it('starts at the template when nothing is selected', () => {
    const flow = automationFlow({ ...base, hasTemplate: false });

    expect(flow.id).toBe('template');
    expect(flow.index).toBe(1);
    expect(flow.canSend).toBe(false);
    expect(flow.steps[0].state).toBe('current');
  });

  it('asks for fields before a downstream system', () => {
    expect(automationFlow({ ...base, variableCount: 0 }).id).toBe('fields');
  });

  it('asks for a connector once the fields are confirmed', () => {
    expect(automationFlow({ ...base, hasConnector: false }).id).toBe('target');
  });

  it('asks for the mapping when a required spec field is unmapped', () => {
    const flow = automationFlow({ ...base, unmappedRequired: 2, prepared: false });

    expect(flow.id).toBe('mapping');
    expect(flow.title).toBe('Map 2 required fields');
    expect(flow.steps.map((step) => step.id)).toEqual([
      'template',
      'fields',
      'target',
      'mapping',
      'values',
      'send',
    ]);
  });

  it('skips the mapping step for a connector without a spec', () => {
    const flow = automationFlow({ ...base, hasSpec: false, prepared: false });

    expect(flow.id).toBe('values');
    expect(flow.total).toBe(5);
    expect(flow.steps.map((step) => step.id)).not.toContain('mapping');
  });

  it('asks to fix body issues instead of offering Send', () => {
    const flow = automationFlow({ ...base, bodyIssues: 1 });

    expect(flow.id).toBe('values');
    expect(flow.title).toBe('Fix 1 request-body issue');
    expect(flow.canSend).toBe(false);
  });

  it('closes the loop after a successful send', () => {
    const flow = automationFlow({ ...base, lastSendSucceeded: true });

    expect(flow.id).toBe('send');
    expect(flow.canSend).toBe(true);
    expect(flow.title).toBe('Sent — press Send to repeat, or pick another template');
  });

  it('offers Send only when everything is ready', () => {
    const flow = automationFlow(base);

    expect(flow.id).toBe('send');
    expect(flow.canSend).toBe(true);
    expect(flow.steps.at(-1)?.state).toBe('current');
    expect(flow.steps.slice(0, -1).every((step) => step.state === 'done')).toBe(true);
  });
});