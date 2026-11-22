/** Automatic-dispatch runs: one row per rule × submission × downstream, plus delivery state. */

import { request, type RegistryOptions } from './automationRegistry';

import type { RuleMode } from './automationRules';

export type JobStatus =
  | 'queued'
  | 'sending'
  | 'needs_review'
  | 'sent'
  | 'shadowed'
  | 'needs_attention'
  | 'cancelled'
  | 'skipped';

export type DeliveryStatus =
  | 'not_configured'
  | 'queued'
  | 'sending'
  | 'needs_review'
  | 'sent'
  | 'partial'
  | 'needs_attention'
  | 'shadowed';

export interface Job {
  job_id: string;
  rule_id: string;
  rule_name: string | null;
  document_id: string;
  document_title: string | null;
  submission_id: string;
  template_id: string;
  connector_id: string;
  connector_name: string | null;
  status: JobStatus;
  mode: RuleMode;
  required: boolean;
  attempts: number;
  next_attempt_at: string | null;
  error_code: string | null;
  receipt_id: string | null;
  request: Record<string, unknown> | null;
  response_excerpt: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobEvent {
  event_id: string;
  from_status: string | null;
  to_status: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface JobDetail extends Job {
  events: JobEvent[];
}

export interface DeliveryRow {
  job_id: string;
  rule_id: string;
  connector_id: string;
  connector_name: string | null;
  status: JobStatus;
  mode: RuleMode;
  required: boolean;
  attempts: number;
  error_code: string | null;
  receipt_id: string | null;
  updated_at: string;
}

export interface DocumentDelivery {
  document_id: string;
  status: DeliveryStatus;
  auto_send_enabled: boolean;
  skipped_reason: string | null;
  rows: DeliveryRow[];
}

export interface AutomationSettings {
  auto_send_enabled: boolean;
}

const query = (params: Record<string, string | number | undefined>): string => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
};

export function listJobs(
  params: { document_id?: string; status?: string; limit?: number } = {},
  options: RegistryOptions = {},
): Promise<{ items: Job[] }> {
  return request(`/jobs${query(params)}`, { method: 'GET' }, options);
}

export function getJob(jobId: string, options: RegistryOptions = {}): Promise<JobDetail> {
  return request(`/jobs/${encodeURIComponent(jobId)}`, { method: 'GET' }, options);
}

export function releaseJob(jobId: string, options: RegistryOptions = {}): Promise<Job> {
  return request(
    `/jobs/${encodeURIComponent(jobId)}/release`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    options,
  );
}

export function retryJob(jobId: string, options: RegistryOptions = {}): Promise<Job> {
  return request(
    `/jobs/${encodeURIComponent(jobId)}/retry`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    options,
  );
}

export function cancelJob(jobId: string, options: RegistryOptions = {}): Promise<Job> {
  return request(
    `/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    options,
  );
}

export function readDocumentDelivery(
  documentId: string,
  options: RegistryOptions = {},
): Promise<DocumentDelivery> {
  return request(`/documents/${encodeURIComponent(documentId)}/delivery`, { method: 'GET' }, options);
}

export function readSettings(options: RegistryOptions = {}): Promise<AutomationSettings> {
  return request('/settings', { method: 'GET' }, options);
}

export interface JobsClient {
  listJobs: typeof listJobs;
  getJob: typeof getJob;
  releaseJob: typeof releaseJob;
  retryJob: typeof retryJob;
  cancelJob: typeof cancelJob;
  readDocumentDelivery: typeof readDocumentDelivery;
  readSettings: typeof readSettings;
}

export const jobsClient: JobsClient = {
  listJobs,
  getJob,
  releaseJob,
  retryJob,
  cancelJob,
  readDocumentDelivery,
  readSettings,
};