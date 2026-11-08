/** Envelope builders shared by unit and component tests. */

import type {
  AuditFinding,
  AuditReport,
  FieldValue,
  GateDecision,
  RunEnvelope,
  StageReport,
  TrailEntry,
  VerificationReport,
} from '../api/types';

export const field = (over: Partial<FieldValue> & { key: string }): FieldValue => {
  const { key, ...rest } = over;
  return {
    key,
    value: 'value',
    status: 'extracted',
    confirmed: false,
    edited_by_user: false,
    source: null,
    normalized_from: null,
    label: null,
    doc_type: null,
    notes: [],
    ...rest,
  };
};

export const stage = (over: Partial<StageReport> & { stage: string }): StageReport => {
  const { stage, ...rest } = over;
  return {
    stage,
    agent: 'agent1',
    status: 'done',
    reason: null,
    produced: 1,
    model_calls: 1,
    ...rest,
  };
};

export const trailEntry = (over: Partial<TrailEntry> = {}): TrailEntry => ({
  id: 'agent1.parse#001',
  agent: 'agent1',
  stage: 'parse',
  op: 'read',
  before: null,
  after: '1 docs / 8 blocks',
  ref: null,
  model: null,
  prompt_hash: null,
  detail: {},
  ...over,
});

export const FIXTURE_REASON = 'candidates from fixture:fixtures/llm/extract_sample.json';
export const NO_PROVIDER_REASON = 'no model provider configured (set SMART_EDIT_LLM)';

export const envelope = (over: Partial<RunEnvelope> = {}): RunEnvelope => ({
  thread_id: 'R-test',
  business_type: 'guarantee',
  files: [],
  fields: {},
  extra_fields: {},
  findings: [],
  stages: [
    stage({ stage: 'parse' }),
    stage({ stage: 'extract', reason: FIXTURE_REASON }),
    stage({ stage: 'normalize' }),
  ],
  trail: [trailEntry()],
  _candidates: [],
  supported_stages: ['extract', 'normalize', 'parse'],
  ...over,
});

/** Extraction completed: field checks may be reported. */
export const doneEnvelope = (over: Partial<RunEnvelope> = {}): RunEnvelope =>
  envelope({
    fields: {
      guarantee_amount: field({
        key: 'guarantee_amount',
        value: '500000.00',
        normalized_from: 'USD 500,000.00',
        label: 'Amount',
        source: {
          file_id: 'F-1',
          page: null,
          bbox: null,
          span: 'USD 500,000.00',
          form_label: null,
        },
      }),
      applicant_name: field({
        key: 'applicant_name',
        value: 'Alpha Tech Pte Ltd',
        notes: ['value_truncated'],
        status: 'inferred',
        label: 'Applicant',
      }),
      expiry_date: field({
        key: 'expiry_date',
        value: null,
        status: 'missing',
        notes: ['not_in_source'],
        label: 'Expiry Date',
      }),
    },
    ...over,
  });

/** Extraction failed: no field checks may be reported, only a blocked reason. */
export const noProviderEnvelope = (over: Partial<RunEnvelope> = {}): RunEnvelope =>
  envelope({
    fields: {
      guarantee_number: field({
        key: 'guarantee_number',
        value: null,
        status: 'missing',
        notes: ['not_in_source'],
      }),
    },
    stages: [
      stage({ stage: 'parse' }),
      stage({ stage: 'extract', status: 'failed', reason: NO_PROVIDER_REASON, produced: 0, model_calls: 0 }),
      stage({ stage: 'normalize' }),
    ],
    ...over,
  });

export const findingsEnvelope = (): RunEnvelope =>
  doneEnvelope({
    findings: [
      {
        id: 'N-001',
        source: 'normalization',
        kind: 'invalid_value',
        rule_id: 'F-applicant_name-max_length',
        severity: 'warn',
        blocking: false,
        resolved: false,
        resolution: null,
        field_keys: ['applicant_name'],
        message: 'applicant_name value length 70 exceeds the limit 64; it was truncated',
        evidence: 'Alpha Tech Pte Ltd …',
        citation: null,
        suggestion: null,
      },
      {
        id: 'N-002',
        source: 'normalization',
        kind: 'invalid_value',
        rule_id: 'F-guarantee_amount-max_length',
        severity: 'critical',
        blocking: false,
        resolved: false,
        resolution: null,
        field_keys: ['guarantee_amount'],
        message: 'amount truncated',
        evidence: '500000.00',
        citation: null,
        suggestion: null,
      },
    ],
  });

const auditFinding = (over: Partial<AuditFinding> = {}): AuditFinding => ({
  id: 'B-001',
  check_id: 'SCHEMA:guarantee_amount:required',
  rule_id: 'SCHEMA:guarantee_amount:required',
  rule_version: 'schema-1',
  category: 'field',
  severity: 'critical',
  gate_type: 'hard_block',
  target_operations: ['start_approval', 'formal_export', 'handoff'],
  method: 'deterministic',
  field_id: 'guarantee_amount',
  evidence: null,
  message: 'Required field is missing',
  ...over,
});

/** `verification.audit` — the numbers the panel prints. */
export const auditReport = (over: Partial<AuditReport> = {}): AuditReport => ({
  planned: 51,
  counts: {
    pass: 33,
    finding: 0,
    not_applicable: 18,
    needs_input: 0,
    unable_to_assess: 0,
    failed: 0,
  },
  coverage: { assessed: 33, not_applicable: 18, unsettled: 0, ratio: 0.647 },
  completion: 'complete',
  outcome: 'no_findings',
  freshness: 'current',
  freshness_reasons: [],
  reasons: [],
  snapshot_digest: 'server-digest-0123456789',
  schema_version: '044a959e73af',
  bundle_versions: { 'guarantee-core': '1.0.0' },
  engine_version: '1.0.0',
  findings: [],
  ...over,
});

export const verification = (over: Partial<VerificationReport> = {}): VerificationReport => ({
  checks: [],
  verdict: 'pass',
  credibility: {
    assessed: 33,
    planned: 51,
    ratio: 0.647,
    formula: 'assessed / planned, assessed = pass + finding (not_applicable never counts)',
  },
  score: null,
  audit: auditReport(),
  ...over,
});

export const gateDecision = (over: Partial<GateDecision> = {}): GateDecision => ({
  decision: 'blocked',
  operation: 'start_approval',
  candidate_content_sha256: 'server-digest-0123456789',
  policy_revision: '2026-11-08.2',
  evaluated_at: '2026-11-08T09:00:01.000Z',
  reason_codes: ['hard_block'],
  authorized_finding_ids: ['B-001'],
  open_gaps: 0,
  advisory_finding_ids: [],
  unsupported_capability: null,
  ...over,
});

/** A run that went all the way through the audit stage. */
export const auditedEnvelope = (over: Partial<RunEnvelope> = {}): RunEnvelope =>
  doneEnvelope({
    stages: [
      stage({ stage: 'parse' }),
      stage({ stage: 'extract', reason: FIXTURE_REASON }),
      stage({ stage: 'normalize' }),
      stage({ stage: 'audit', agent: 'agent4', produced: 0, model_calls: 0 }),
    ],
    supported_stages: ['audit', 'extract', 'normalize', 'parse'],
    verification: verification(),
    gate: null,
    ...over,
  });

/** An audit that did find something, with a gate decision about `start_approval`. */
export const blockedAuditEnvelope = (): RunEnvelope =>
  auditedEnvelope({
    verification: verification({
      verdict: 'warn',
      audit: auditReport({
        counts: {
          pass: 32,
          finding: 1,
          not_applicable: 18,
          needs_input: 0,
          unable_to_assess: 0,
          failed: 0,
        },
        coverage: { assessed: 33, not_applicable: 18, unsettled: 0, ratio: 0.647 },
        outcome: 'findings_present',
        reasons: [],
        findings: [auditFinding()],
      }),
    }),
    gate: gateDecision(),
  });