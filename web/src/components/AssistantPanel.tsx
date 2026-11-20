import { useState } from 'react';

import type { AssistantClient, AssistantOptions } from '../api/assistant';
import type { AssistantSelection } from '../api/assistantTypes';
import type { DraftView } from '../api/documents';
import type { DownstreamSystemStore } from '../automation/downstreamSystemStore';
import type { TemplateStore } from '../automation/templateStore';
import type { RichDocument } from '../rich/richDocument';
import type { ActivityKind } from '../workspace/activityStore';
import { AuditPanel, type AuditPanelProps } from './AuditPanel';
import { AutomationPanel } from './AutomationPanel';
import { KnowledgePanel } from './KnowledgePanel';
import { LegalPanel, type LegalPanelProps } from './LegalPanel';

type TabStatus = 'full' | 'fixture-only' | 'not-implemented';

interface Tab {
  id: string;
  /** Accessible name; keeps the build status readable to assistive tech. */
  label: string;
  /** Visible label; must stay short enough for four tabs on one row at 352px. */
  shortLabel: string;
  status: TabStatus;
  statusLabel: string;
  statusTone: string;
}

const TABS: Tab[] = [
  {
    id: 'audit',
    label: 'Rule audit',
    shortLabel: 'Audit',
    status: 'full',
    statusLabel: 'Full',
    statusTone: 'tag--ok',
  },
  {
    id: 'knowledge',
    label: 'Knowledge Q&A',
    shortLabel: 'Knowledge',
    status: 'full',
    statusLabel: 'Full',
    statusTone: 'tag--ok',
  },
  {
    id: 'automation',
    label: 'Automation',
    shortLabel: 'Automation',
    status: 'fixture-only',
    statusLabel: 'Fixture only',
    statusTone: 'tag--warn',
  },
  {
    id: 'legal',
    label: 'Legal advice',
    shortLabel: 'Legal',
    status: 'full',
    statusLabel: 'Full',
    statusTone: 'tag--ok',
  },
];

/**
 * Accessible name: base label plus the build status, so assistive tech hears the same caveat the
 * visible tag shows. The visible label stays short (design D7).
 */
const tabLabel = (tab: Tab): string =>
  tab.status === 'full' ? tab.label : `${tab.label} · ${tab.statusLabel.toLowerCase()}`;

export interface KnowledgePanelBinding {
  documentId: string;
  /** Active organisation workspace (PG identity); defaults to the demo workspace. */
  workspaceId?: string;
  digest: string;
  text: string;
  selection?: AssistantSelection | null;
  locale?: 'zh-CN' | 'en';
  client?: AssistantClient;
  options?: AssistantOptions;
  pollDelayMs?: number;
  onActivity?: (kind: ActivityKind, action: string, detail: string) => void;
}

export interface AutomationPanelBinding {
  draft: DraftView | null;
  document: RichDocument;
  selection: AssistantSelection | null;
  pendingVariable: AssistantSelection | null;
  digest?: string;
  richEditorAvailable?: boolean;
  templateStore?: TemplateStore;
  downstreamStore?: DownstreamSystemStore;
  onApplyTemplate?: (document: RichDocument) => void;
  onChange: (document: RichDocument) => void;
  onVariableHandled: () => void;
}

export interface AssistantPanelProps extends AuditPanelProps {
  knowledge: KnowledgePanelBinding;
  automation: AutomationPanelBinding;
  legal: LegalPanelProps;
}

/**
 * Right pane: the prototype's four tabs. Audit, knowledge, fixture-backed automation and the
 * legal advice surface are all wired; the assistant never approves or submits.
 */
export function AssistantPanel({ knowledge, automation, legal, ...auditProps }: AssistantPanelProps) {
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
            aria-label={tabLabel(tab)}
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="tab-label" aria-hidden="true">
              {tab.shortLabel}
            </span>
            <span className={`tab-status tag ${tab.statusTone}`} aria-hidden="true">
              {tab.statusLabel}
            </span>
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
        ) : active.id === 'legal' ? (
          <LegalPanel {...legal} />
        ) : null}
      </div>

      <div className="assistant-footer">
        Fixed snapshot · sources traceable · the assistant does not approve or submit
      </div>
    </aside>
  );
}