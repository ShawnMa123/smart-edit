import { useState } from 'react';

import type { AssistantClient, AssistantOptions } from '../api/assistant';
import type { AssistantSelection } from '../api/assistantTypes';
import { AuditPanel, type AuditPanelProps } from './AuditPanel';
import { KnowledgePanel } from './KnowledgePanel';

interface Tab {
  id: string;
  label: string;
  implemented: boolean;
}

const TABS: Tab[] = [
  { id: 'audit', label: 'Rule audit', implemented: true },
  { id: 'knowledge', label: 'Knowledge Q&A', implemented: true },
  { id: 'automation', label: 'Automation', implemented: false },
  { id: 'legal', label: 'Legal advice', implemented: false },
];

export interface KnowledgePanelBinding {
  documentId: string;
  digest: string;
  text: string;
  selection?: AssistantSelection | null;
  locale?: 'zh-CN' | 'en';
  client?: AssistantClient;
  options?: AssistantOptions;
  pollDelayMs?: number;
}

export interface AssistantPanelProps extends AuditPanelProps {
  knowledge: KnowledgePanelBinding;
}

/**
 * Right pane: the prototype's four tabs. Audit and knowledge are wired to the backend; automation and
 * legal stay labelled as unimplemented and never render sample answers, findings or citations.
 */
export function AssistantPanel({ knowledge, ...auditProps }: AssistantPanelProps) {
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
        ) : active.id === 'knowledge' ? (
          <KnowledgePanel {...knowledge} />
        ) : (
          <div className="notice" role="status">
            <h3>{active.label} is not implemented in this build</h3>
            <p className="tiny">
              No answers, findings or citations are produced for this capability. Only the rule audit
              and knowledge tabs are wired to a backend in this build.
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