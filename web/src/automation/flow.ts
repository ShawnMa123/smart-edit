/**
 * Guided order for `Automation → Server & Downstream`.
 *
 * The panel is four stacked sections, but a first-time user only needs one thing at a time: which
 * control to touch next, and why the button they expected is disabled. This module owns that
 * decision as a pure function so it can be tested without a browser.
 */

export type AutomationStepId =
  | 'template'
  | 'fields'
  | 'target'
  | 'mapping'
  | 'values'
  | 'send';

export interface AutomationFlowInput {
  hasTemplate: boolean;
  /** Confirmed variables on the selected template. */
  variableCount: number;
  hasConnector: boolean;
  /** The selected connector carries an OpenAPI operation (mapping step applies). */
  hasSpec: boolean;
  /** Required spec fields that currently have no variable mapped. */
  unmappedRequired: number;
  /** Values were prepared from the draft for the current template+connector. */
  prepared: boolean;
  /** Body issues reported by prepare (missing/invalid/unsupported). */
  bodyIssues: number;
  /** The last dispatch for this target succeeded, so the loop is closed. */
  lastSendSucceeded?: boolean;
}

export interface AutomationFlowStep {
  id: AutomationStepId;
  label: string;
  state: 'done' | 'current' | 'todo';
}

export interface AutomationFlow {
  id: AutomationStepId;
  index: number;
  total: number;
  title: string;
  detail: string;
  canSend: boolean;
  steps: AutomationFlowStep[];
}

const LABELS: Record<AutomationStepId, string> = {
  template: 'Template',
  fields: 'Fields',
  target: 'Downstream',
  mapping: 'Mapping',
  values: 'Review',
  send: 'Send',
};

export function automationFlow(input: AutomationFlowInput): AutomationFlow {
  const ids: AutomationStepId[] = input.hasSpec
    ? ['template', 'fields', 'target', 'mapping', 'values', 'send']
    : ['template', 'fields', 'target', 'values', 'send'];

  let id: AutomationStepId;
  let title: string;
  let detail: string;

  if (!input.hasTemplate) {
    id = 'template';
    title = 'Pick or save a template';
    detail = 'Choose a server template, or save the current draft as one.';
  } else if (input.variableCount === 0) {
    id = 'fields';
    title = 'Detect the fields';
    detail = 'Run “Find variables with AI”, untick what is not a field, then confirm.';
  } else if (!input.hasConnector) {
    id = 'target';
    title = 'Choose the downstream system';
    detail = 'Pick a connector — or add one with its OpenAPI spec so the body matches the receiver.';
  } else if (input.hasSpec && input.unmappedRequired > 0) {
    id = 'mapping';
    title = `Map ${input.unmappedRequired} required field${input.unmappedRequired > 1 ? 's' : ''}`;
    detail =
      'Open “3 · Downstream” → Field mapping: assign a variable to each required field, then “Save mapping”.';
  } else if (!input.prepared) {
    id = 'values';
    title = 'Review the request';
    detail = 'The values are filled from the draft automatically — check them in “4 · Review & send”.';
  } else if (input.bodyIssues > 0) {
    id = 'values';
    title = `Fix ${input.bodyIssues} request-body issue${input.bodyIssues > 1 ? 's' : ''}`;
    detail = 'A required field is empty or does not fit the spec — edit the value, mapping or draft.';
  } else if (input.lastSendSucceeded) {
    id = 'send';
    title = 'Sent — press Send to repeat, or pick another template';
    detail = 'The receipt below records the request body and the response.';
  } else {
    id = 'send';
    title = 'Send the request';
    detail = 'The preview above is exactly what the receiver gets; press “Send”.';
  }

  const currentIndex = ids.indexOf(id);
  const steps = ids.map((stepId, index) => ({
    id: stepId,
    label: LABELS[stepId],
    state: (index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'todo') as
      | 'done'
      | 'current'
      | 'todo',
  }));

  return {
    id,
    index: currentIndex + 1,
    total: ids.length,
    title,
    detail,
    canSend: id === 'send',
    steps,
  };
}