/**
 * The Automation tab entry point (task 2.4).
 *
 * The tab used to be a fixture run panel; the main view is now the three-area workbench. The run core
 * stays covered by the API tests (`web/src/api/automation.test.ts`), not by this surface.
 *
 * Automation is a Bank Operations back-office capability: without `automation.view` the tab is hidden
 * upstream and this panel renders the access boundary instead of a workbench that would 403.
 */

import { AutomationWorkbench, type AutomationWorkbenchProps } from './AutomationWorkbench';

export type AutomationPanelProps = AutomationWorkbenchProps & {
  /** `false` when the signed-in role has no `automation.view`. */
  canUseAutomation?: boolean;
};

export function AutomationPanel({ canUseAutomation = true, ...props }: AutomationPanelProps) {
  if (!canUseAutomation) {
    return (
      <p className="notice notice--bad tiny" role="status" data-testid="automation-forbidden">
        Automation is a Bank Operations back office. Ask an organisation administrator for the Bank
        Operations role to review, configure or send to downstream systems.
      </p>
    );
  }
  return <AutomationWorkbench {...props} />;
}