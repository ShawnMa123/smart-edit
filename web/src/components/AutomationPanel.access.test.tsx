/** The Automation tab itself refuses to render the workbench without `automation.view`. */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AutomationPanel } from './AutomationPanel';

const binding = {
  draft: null,
  document: { type: 'doc' as const, content: [] },
  selection: null,
  pendingVariable: null,
  onChange: vi.fn(),
  onVariableHandled: vi.fn(),
};

describe('AutomationPanel access', () => {
  it('shows the bank-operations boundary instead of the workbench', () => {
    render(<AutomationPanel {...binding} canUseAutomation={false} />);

    const boundary = screen.getByTestId('automation-forbidden');
    expect(boundary.textContent).toContain('Bank Operations');
    expect(screen.queryByLabelText('Server automation')).toBeNull();
  });
});