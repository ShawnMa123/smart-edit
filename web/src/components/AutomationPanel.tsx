/**
 * The Automation tab entry point (task 2.4).
 *
 * The tab used to be a fixture run panel; the main view is now the three-area workbench. The run core
 * stays covered by the API tests (`web/src/api/automation.test.ts`), not by this surface.
 */

import { AutomationWorkbench, type AutomationWorkbenchProps } from './AutomationWorkbench';

export type AutomationPanelProps = AutomationWorkbenchProps;

export function AutomationPanel(props: AutomationPanelProps) {
  return <AutomationWorkbench {...props} />;
}