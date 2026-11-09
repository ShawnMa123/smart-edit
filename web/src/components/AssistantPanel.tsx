import { useState } from 'react';

import { AuditPanel, type AuditPanelProps } from './AuditPanel';
import { LegalPanel, type LegalState } from './LegalPanel';

interface Tab {
  id: string;
  label: string;
  implemented: boolean;
}

const TABS: Tab[] = [
  { id: 'audit', label: 'Rule audit', implemented: true },
  { id: 'knowledge', label: 'Knowledge Q&A', implemented: false },
  { id: 'automation', label: 'Automation', implemented: false },
  { id: 'legal', label: 'Legal advice', implemented: true },
];

export interface AssistantPanelProps extends AuditPanelProps {
  legalState?: LegalState;
  onRunLegal?: () => void;
  canRunLegal?: boolean;
  legalHint?: string;
}

/**
 * Right pane: the prototype's four tabs. The audit and legal tabs are wired to their backends; the
 * other two state that they are unimplemented and never render sample answers.
 */
export function AssistantPanel({
  legalState = { phase: 'idle' },
  onRunLegal = () => undefined,
  canRunLegal = false,
  legalHint,
  ...auditProps
}: AssistantPanelProps) {
  const [activeTab, setActiveTab] = useState<string>('audit');
  const active = TABS.find((tab) => tab.id === activeTab) ?? TABS[0];

  return (
    <aside className="pane" aria-label="AI assistant">
      <div className="row">
        <h2>AI assistant</h2>
        <span className="muted tiny">Human decides</span>
      </div>

      <div className="assistant-tabs" role="tablist" aria-label="Assistant capabilities">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={tab.id === activeTab}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.implemented ? tab.label : `${tab.label} · not implemented`}
          </button>
        ))}
      </div>

      <div className="assistant-body">
        {active.id === 'audit' ? (
          <AuditPanel {...auditProps} />
        ) : active.id === 'legal' ? (
          <LegalPanel
            state={legalState}
            canRun={canRunLegal}
            onRun={onRunLegal}
            hint={legalHint}
          />
        ) : (
          <div className="notice" role="status">
            <h3>{active.label} is not implemented in this build</h3>
            <p className="tiny">
              No answers, findings or citations are produced for this capability. Only the rule audit
              and legal advice tabs are wired to a backend in this build.
            </p>
          </div>
        )}
      </div>

      <div className="assistant-footer">
        Fixed snapshot · sources traceable · the assistant does not approve or submit
      </div>
    </aside>
  );
}