/**
 * Markdown export for one conformance report.
 *
 * Kept out of the panel so it is testable without DOM: the export must say the same honest things
 * the screen says (outcome, coverage, limitations, redaction steps, provenance).
 */

import type { ConformanceReport } from './api/conformance';

const bulletList = (items: string[]): string =>
  items.length ? items.map((item) => `- ${item}`).join('\n') : '- (none)';

export function reportToMarkdown(report: ConformanceReport): string {
  const lines: string[] = [];
  lines.push(`# Template audit — ${report.config.name}`);
  lines.push('');
  lines.push(
    `- Config: \`${report.config.config_id}\` v${report.config.version} (sha ${report.config.content_sha256.slice(0, 8)})`,
  );
  lines.push(
    `- Draft: rev ${report.snapshot.revision ?? '—'} · sha ${(report.snapshot.content_sha256 ?? '—').slice(0, 8)} · ${report.snapshot.analyzed_chars} chars analysed`,
  );
  lines.push(`- Outcome: **${report.outcome}** (${report.completion})`);
  lines.push(
    `- Coverage: ${report.counts.passed}/${report.counts.requirements} assessed · ${Math.round(report.counts.coverage_ratio * 100)}%`,
  );
  lines.push('');

  if (report.summary) {
    lines.push('## Summary');
    lines.push('');
    lines.push(report.summary);
    lines.push('');
    lines.push(`> ${report.summary_note}`);
    lines.push('');
  }

  if (report.missing_fields.length) {
    lines.push('## Required fields not found');
    lines.push('');
    lines.push(bulletList(report.missing_fields.map((field) => `${field.label} (\`${field.key}\`)`)));
    lines.push('');
  }

  const findings = report.results.filter((item) => item.status === 'finding');
  if (findings.length) {
    lines.push('## Does not match the config');
    lines.push('');
    for (const item of findings) {
      lines.push(`### ${item.title}`);
      lines.push('');
      lines.push(`- Requirement: \`${item.id}\` · ${item.level} · ${item.severity}`);
      lines.push(`- Confidence: ${item.confidence}`);
      lines.push(`- Why: ${item.explanation}`);
      if (item.quote) lines.push(`- Quote: “${item.quote}”`);
      if (item.suggestion) lines.push(`- Suggestion: ${item.suggestion}`);
      lines.push('');
    }
  }

  const passed = report.results.filter((item) => item.status === 'pass');
  if (passed.length) {
    lines.push('## Requirements met');
    lines.push('');
    lines.push(
      bulletList(
        passed.map((item) => `${item.title}${item.quote ? ` — “${item.quote}”` : ''}`),
      ),
    );
    lines.push('');
  }

  const unable = report.results.filter((item) => item.status === 'unable_to_assess');
  if (unable.length) {
    lines.push('## Not assessed');
    lines.push('');
    lines.push(
      bulletList(
        unable.map(
          (item) => `${item.title} — ${item.reason_codes.join(', ') || 'not assessed'}`,
        ),
      ),
    );
    lines.push('');
  }

  if (report.limitations.length) {
    lines.push('## Limitations');
    lines.push('');
    lines.push(
      bulletList(report.limitations.map((item) => `\`${item.code}\` ${item.message}`)),
    );
    lines.push('');
  }

  lines.push('## Redaction');
  lines.push('');
  lines.push(report.provenance.redaction.note);
  lines.push('');
  lines.push(
    bulletList(
      report.provenance.redaction.steps.map(
        (step) => `${step.kind} × ${step.count} — masked sample \`${step.sample}\``,
      ),
    ),
  );
  lines.push('');

  lines.push('## Provenance');
  lines.push('');
  lines.push(
    `- Model: ${report.provenance.model ?? 'none'} · prompt ${report.provenance.prompt_version} · ${report.provenance.model_calls} call(s) · ${report.provenance.duration_ms} ms`,
  );
  lines.push(
    `- Extraction: ${report.provenance.extraction_status} (${report.provenance.extraction_profile ?? 'no profile'})`,
  );
  lines.push(`- Report: ${report.report_id} · run ${report.run_id}`);
  return `${lines.join('\n')}\n`;
}

export const reportFileName = (report: ConformanceReport): string =>
  `template-audit-${report.config.config_id}-rev${report.snapshot.revision ?? 'x'}.md`;