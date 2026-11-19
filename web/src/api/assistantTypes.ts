/**
 * Knowledge-assistant contract types (`knowledge-assistant` spec §7-8).
 *
 * Shapes mirror the server DTOs exactly; the client never invents owner/role/ACL fields.
 */

export type Outcome =
  | 'answered'
  | 'needs_clarification'
  | 'insufficient_evidence'
  | 'unable_to_assess'
  | 'needs_handoff';

export type SupportLevel = 'strong' | 'qualified' | 'insufficient' | 'not_applicable';
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timed_out';
export type RunStage =
  | 'queued'
  | 'resolving_context'
  | 'analyzing'
  | 'screening'
  | 'retrieving'
  | 'local_retrieval'
  | 'web_search'
  | 'composing'
  | 'reviewing'
  | 'publishing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timed_out';
export type HandoffTarget = 'automation' | 'standards_audit' | 'regulatory_advice';
export type SourceType =
  | 'product_manual'
  | 'trade_rule'
  | 'internal_policy'
  | 'document_snapshot'
  | 'attachment'
  | 'approved_web'
  | 'general_web'
  | 'statute';

export interface AssistantSelection {
  nodeId: string;
  startOffset: number;
  endOffset: number;
  selectedText: string;
}

export interface Claim {
  id: string;
  text: string;
  kind: 'fact' | 'interpretation';
  citation_ids: string[];
}

export interface Citation {
  id: string;
  source_type: SourceType;
  title: string;
  source_version: string;
  locator: Record<string, unknown>;
}

export interface RetrievalLayer {
  layer: 'local' | 'rag' | 'web' | 'statute';
  status: 'ok' | 'failed' | 'skipped' | 'blocked';
  detail: string | null;
  retrieved_at: string | null;
  /** How many items this layer returned; `null`/absent means "not measured". */
  hits?: number | null;
}

export type AnswerRoute =
  | 'published'
  | 'statute'
  | 'document'
  | 'general_web'
  | 'handoff'
  | 'none';

export interface WebSummary {
  requested: boolean;
  status: 'off' | 'skipped' | 'ok' | 'blocked' | 'failed';
  reason: string | null;
  hint: string | null;
}

export interface Capabilities {
  model: { configured: boolean; label: string | null; approved_processor: boolean };
  layers: { local: boolean; approved_web: boolean; general_web: boolean; statute: boolean };
  egress: { policy_version: string; allowed_domains: number; loaded: boolean };
  web: { provider: 'off' | 'fixture' | 'http'; default_on?: boolean };
  presets?: {
    jurisdictions: string[] | null;
    suggested_questions: string[] | null;
  };
  statute?: {
    enabled: boolean;
    reachable: boolean;
    documents: number | null;
    chunks: number | null;
    index_version: string | null;
    jurisdictions: string[] | null;
  };
}

export interface Answer {
  schema_version: '1.0';
  outcome: Outcome;
  language: 'zh-CN' | 'en';
  support_level: SupportLevel;
  claims: Claim[];
  citations: Citation[];
  limitations: string[];
  clarification_questions: string[];
  context_stale: boolean;
  handoff_target: HandoffTarget | null;
  retrieval?: RetrievalLayer[];
  processor?: string | null;
  route?: AnswerRoute | null;
  web?: WebSummary | null;
}

export interface AssistantErrorBody {
  code: string;
  message: string;
  request_id: string;
  retryable: boolean;
  field_errors?: { field: string; code: string }[];
}

export interface AssistantSnapshot {
  id: string;
  workspace_id: string;
  document_id: string;
  content_sha256: string;
  version_label: string | null;
  created_by: string;
  created_at: string;
}

export interface Session {
  id: string;
  workspace_id: string;
  owner_user_id: string;
  document_id: string | null;
  snapshot_id: string | null;
  attachment_ids: string[];
  locale: 'zh-CN' | 'en';
  status: 'active' | 'archived';
  context_stale: boolean;
  created_at: string;
}

export interface Run {
  id: string;
  session_id: string;
  user_message_id: string;
  status: RunStatus;
  stage: RunStage;
  attempt: number;
  created_at: string;
  deadline_at: string;
  started_at: string | null;
  finished_at: string | null;
  assistant_message_id: string | null;
  result: Answer | null;
  error: AssistantErrorBody | null;
}

export interface RunAccepted extends Run {
  poll_after_ms: number;
}

export interface Message {
  id: string;
  session_id: string;
  run_id: string;
  role: 'user' | 'assistant';
  visibility: 'visible' | 'redacted';
  question: string | null;
  answer: Answer | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface EvidenceDetail {
  citation_id: string;
  source_type: SourceType;
  title: string;
  source_version: string;
  excerpt: string;
  locator: Record<string, unknown>;
  effective_from: string | null;
  effective_to: string | null;
  retrieved_at: string | null;
}

export type FeedbackRating = 'helpful' | 'not_helpful';
export type FeedbackCategory = 'incorrect' | 'wrong_citation' | 'outdated' | 'irrelevant' | 'unclear';

export interface FeedbackInput {
  rating: FeedbackRating;
  categories?: FeedbackCategory[];
  comment?: string | null;
}

export interface Feedback {
  id: string;
  message_id: string;
  rating: FeedbackRating;
  categories: FeedbackCategory[];
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export const SESSION_DOCUMENT_ID = 'demo-document';
export const DEFAULT_WORKSPACE = 'ws_demo_01';
export const TERMINAL_STATUSES: RunStatus[] = [
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
];

export const isTerminal = (status: RunStatus): boolean => TERMINAL_STATUSES.includes(status);