/** Contract types the workspace consumes — mirrors the envelope from `console-api`. */

export interface SourceRef {
  file_id: string;
  page: number | null;
  bbox: number[] | null;
  span: string;
  form_label: string | null;
}

export interface FieldValue {
  key: string;
  value: string | null;
  status: string;
  confirmed: boolean;
  edited_by_user: boolean;
  source: SourceRef | null;
  normalized_from: string | null;
  label: string | null;
  doc_type: string | null;
  notes: string[];
}

export interface Finding {
  id: string;
  source: string;
  kind: string;
  rule_id: string;
  severity: string;
  blocking: boolean;
  resolved: boolean;
  resolution: string | null;
  field_keys: string[];
  message: string;
  evidence: string | null;
  citation: string | null;
  suggestion: string | null;
}

export interface StageReport {
  stage: string;
  agent: string;
  status: string;
  reason: string | null;
  produced: number;
  model_calls: number;
}

export interface TrailEntry {
  id: string;
  agent: string;
  stage: string;
  op: string;
  before: string | null;
  after: string | null;
  ref: string | null;
  model: string | null;
  prompt_hash: string | null;
  detail: Record<string, unknown>;
}

export interface SourceFileRef {
  file_id: string;
  filename: string;
  mime: string;
  path: string;
  sha256: string;
}

/** Unnormalized candidate — never rendered in the field table (spec: candidates are labelled). */
export interface CandidatePreview {
  key: string;
  raw_value: string;
  span: string;
  confidence?: number;
  label?: string | null;
  doc_type?: string | null;
}

export interface RunEnvelope {
  thread_id: string;
  business_type: string | null;
  files: SourceFileRef[];
  fields: Record<string, FieldValue>;
  extra_fields: Record<string, FieldValue>;
  findings: Finding[];
  stages: StageReport[];
  trail: TrailEntry[];
  _candidates: CandidatePreview[];
  supported_stages: string[];
  /** `null` = no audit has run on this run yet. Never read as "clean". */
  verification?: VerificationReport | null;
  /** `null` = the gate was never asked about an operation. Never read as "allowed". */
  gate?: GateDecision | null;
}

/** One planned check, as `verification.checks[]` reports it (agent-audit design D13). */
export interface AuditIssue {
  checker: string;
  level: string;
  finding_ids: string[];
  detail: string;
  location: string | null;
  check_id?: string;
  gate_type?: string;
  target_operations?: string[];
  method?: string;
}

export interface AuditCoverage {
  assessed: number;
  not_applicable: number;
  unsettled: number;
  ratio: number;
}

/** One finding as the **audit** keeps it — the only copy that carries the gate type. */
export interface AuditFinding {
  id: string | null;
  check_id: string;
  rule_id: string | null;
  rule_version: number | string | null;
  category: string;
  severity: string;
  gate_type: string | null;
  target_operations: string[];
  method: string;
  field_id: string | null;
  evidence: string | null;
  message: string;
}

/** `verification.audit` — the report baseline the panel quotes from. */
export interface AuditReport {
  planned: number;
  counts: Record<string, number>;
  coverage: AuditCoverage;
  completion: string;
  outcome: string;
  freshness: string;
  freshness_reasons: string[];
  reasons: string[];
  snapshot_digest: string;
  schema_version: string;
  bundle_versions: Record<string, string>;
  engine_version: string;
  findings: AuditFinding[];
}

export interface VerificationReport {
  checks: AuditIssue[];
  verdict: string;
  credibility: {
    assessed: number | null;
    planned: number | null;
    ratio: number | null;
    formula: string;
  };
  /** Display only; the build never computes one (`null`). */
  score: number | null;
  audit?: AuditReport;
}

export interface GateDecision {
  decision: string;
  operation: string;
  candidate_content_sha256: string;
  policy_revision: string;
  evaluated_at: string;
  reason_codes: string[];
  authorized_finding_ids: string[];
  open_gaps?: number;
  advisory_finding_ids?: string[];
  unsupported_capability?: string | null;
}

export interface ErrorBody {
  code: string;
  message: string;
  detail?: unknown;
}