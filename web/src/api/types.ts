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
}

export interface ErrorBody {
  code: string;
  message: string;
  detail?: unknown;
}