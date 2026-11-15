import { useState } from 'react';

import type { AssistantClient, AssistantOptions } from '../api/assistant';
import type { AssistantSelection } from '../api/assistantTypes';
import type { DraftView } from '../api/documents';
import type { TemplateStore } from '../automation/templateStore';
import type { RichDocument } from '../rich/richDocument';
import { AuditPanel, type AuditPanelProps } from './AuditPanel';
import { AutomationPanel } from './AutomationPanel';
import { KnowledgePanel } from './KnowledgePanel';

type TabStatus = 'full' | 'fixture-only' | 'not-implemented';

interface Tab {
  id: string;
  label: string;
  status: TabStatus;
}

const TABS: Tab[] = [
  { id: 'audit', label: 'Rule audit', status: 'full' },
  { id: 'knowledge', label: 'Knowledge Q&A', status: 'full' },
  { id: 'automation', label: 'Automation', status: 'fixture-only' },
  { id: 'legal', label: 'Legal advice', status: 'not-implemented' },
];

const tabLabel = (tab: Tab): string => {
  if (tab.status === 'fixture-only') return `${tab.label} · fixture only`;
  if (tab.status === 'not-implemented') return `${tab.label} · not implemented`;
  return tab.label;
};

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

export interface AutomationPanelBinding {
  draft: DraftView | null;
  document: RichDocument;
  selection: AssistantSelection | null;
  pendingVariable: AssistantSelection | null;
  digest?: string;
  richEditorAvailable?: boolean;
  templateStore?: TemplateStore;
  onApplyTemplate?: (document: RichDocument) => void;
  onChange: (document: RichDocument) => void;
  onVariableHandled: () => void;
}

export interface AssistantPanelProps extends AuditPanelProps {
  knowledge: KnowledgePanelBinding;
  automation: AutomationPanelBinding;
}

/**
 * Right pane: the prototype's four tabs. Audit, knowledge and the fixture-backed automation
 * surface are available; legal stays labelled as unimplemented and never renders sample output.
 */
export function AssistantPanel({ knowledge, automation, ...auditProps }: AssistantPanelProps) {
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
            {tabLabel(tab)}
          </button>
        ))}
      </div>

      <div className="assistant-body">
        {active.id === 'audit' ? (
          <AuditPanel {...auditProps} />
        ) : active.id === 'knowledge' ? (
          <KnowledgePanel {...knowledge} />
        ) : active.id === 'automation' ? (
          <AutomationPanel {...automation} />
        ) : (
          <div className="notice" role="status">
            <h3>{active.label} is not implemented in this build</h3>
            <p className="tiny">
              No answers, findings or citations are produced for this capability. The rule audit,
              knowledge and fixture-backed automation tabs are wired to a backend in this build.
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