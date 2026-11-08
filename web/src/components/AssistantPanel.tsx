import { useState } from 'react';

import { AuditPanel, type AuditPanelProps } from './AuditPanel';

interface Tab {
  id: string;
  label: string;
  implemented: boolean;
}

const TABS: Tab[] = [
  { id: 'audit', label: 'Rule audit', implemented: true },
  { id: 'knowledge', label: 'Knowledge Q&A', implemented: false },
  { id: 'automation', label: 'Automation', implemented: false },
  { id: 'legal', label: 'Legal advice', implemented: false },
];

/**
 * Right pane (task 6.3): the prototype's four tabs, with only the audit one implemented.
 *
 * Selecting an unimplemented tab states that it is unimplemented — it never renders sample answers,
 * findings or citations (spec: "MUST NOT render sample answers").
 */
export function AssistantPanel(props: AuditPanelProps) {
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
        {active.implemented ? (
          <AuditPanel {...props} />
        ) : (
          <div className="notice" role="status">
            <h3>{active.label} is not implemented in this build</h3>
            <p className="tiny">
              No answers, findings or citations are produced for this capability. Only the rule audit
              tab is wired to a backend in this build.
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