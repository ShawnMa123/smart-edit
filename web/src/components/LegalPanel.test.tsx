import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { LegalPanel } from './LegalPanel';
import type { RunEnvelope } from '../api/types';

function envelope(overrides: Partial<RunEnvelope> = {}): RunEnvelope {
  return {
    thread_id: 'T-1',
    business_type: null,
    files: [],
    fields: {},
    extra_fields: {},
    findings: [],
    stages: [],
    trail: [],
    _candidates: [],
    supported_stages: ['agent3'],
    legal: null,
    retrieved: [],
    ...overrides,
  };
}

const EMPTY_LEGAL = {
  input_mode: 'raw' as const,
  applicable_rules: [],
  claims: [],
  coverage: {
    jurisdictions: [],
    standards: [],
    unavailable: true,
    business_type_uncertain: true,
    notes: ['本次检索未返回可引用条文'],
    corpus: { version: 'v1', documents: 92, jurisdictions: ['CN'], built_at: null },
  },
  escalate_to_human: true,
  summary: '法规建议未覆盖：本次检索未返回可引用条文，需人工复核。',
};

describe('LegalPanel', () => {
  it('never renders an empty retrieval as a clean result', () => {
    render(
      <LegalPanel
        state={{ phase: 'report', envelope: envelope({ legal: EMPTY_LEGAL }) }}
        canRun
        onRun={vi.fn()}
      />,
    );

    expect(screen.getByText(/法规建议未覆盖/)).toBeTruthy();
    expect(screen.getByText(/coverage unavailable/)).toBeTruthy();
    expect(screen.getByText(/escalate to human/)).toBeTruthy();
    expect(screen.getByText(/does not perform legal reasoning/i)).toBeTruthy();
    expect(screen.queryByText(/未发现问题/)).toBeNull();
    expect(screen.queryByText(/合规/)).toBeNull();
  });

  it('keeps an insufficient claim visible and labelled', () => {
    const legal = {
      ...EMPTY_LEGAL,
      summary: '检索到 1 条相关条文；仅指出适用规则与差异候选，不构成法律结论。',
      coverage: { ...EMPTY_LEGAL.coverage, unavailable: false, business_type_uncertain: false },
      claims: [
        {
          text: '保函金额 USD 999,999.00',
          chunk_id: 'chunk-1',
          kind: 'applicable_rule',
          support: 'insufficient',
        },
      ],
      applicable_rules: [
        {
          rule_id: 'doc#第464条',
          title: '海关事务担保条例',
          version: 'v1',
          effective_from: '2021-01-01',
          chunk_id: 'chunk-1',
        },
      ],
    };

    render(
      <LegalPanel
        state={{ phase: 'report', envelope: envelope({ legal, retrieved: [] }) }}
        canRun
        onRun={vi.fn()}
      />,
    );

    const claim = document.querySelector('[data-support="insufficient"]');
    expect(claim).toBeTruthy();
    expect(claim?.textContent).toContain('USD 999,999.00');
    expect(claim?.textContent).toContain('chunk-1');
    expect(screen.getByText('海关事务担保条例')).toBeTruthy();
  });

  it('says when a run has no legal object', () => {
    render(
      <LegalPanel state={{ phase: 'report', envelope: envelope({ legal: null }) }} canRun onRun={vi.fn()} />,
    );

    expect(screen.getByText(/No legal opinion in this run/i)).toBeTruthy();
  });

  it('disables the trigger without a run and explains why', () => {
    render(
      <LegalPanel
        state={{ phase: 'idle' }}
        canRun={false}
        onRun={vi.fn()}
        hint="Run the audit first."
      />,
    );

    expect(
      (screen.getByRole('button', { name: /Run legal check/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText('Run the audit first.')).toBeTruthy();
  });
});
