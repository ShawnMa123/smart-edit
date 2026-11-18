/** Task 5.2 — knowledge panel behaviors over an injected client (no live server). */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { AssistantClient } from '../api/assistant';
import type { Answer, AssistantSelection, Capabilities, Run, Session } from '../api/assistantTypes';
import { ApiError, explainError } from '../api/errors';
import { KnowledgePanel } from './KnowledgePanel';

const SESSION: Session = {
  id: 'sess_1',
  workspace_id: 'ws_demo_01',
  owner_user_id: 'user_a',
  document_id: 'doc-1',
  snapshot_id: 'snap_1',
  attachment_ids: [],
  locale: 'zh-CN',
  status: 'active',
  context_stale: false,
  created_at: '2026-01-01T00:00:00+00:00',
};

const ANSWER: Answer = {
  schema_version: '1.0',
  outcome: 'answered',
  language: 'zh-CN',
  support_level: 'strong',
  claims: [
    { id: 'claim_1', text: '提交成功后释放编辑锁。', kind: 'fact', citation_ids: ['cite_1'] },
  ],
  citations: [
    {
      id: 'cite_1',
      source_type: 'product_manual',
      title: '合成产品手册',
      source_version: 'demo-1',
      locator: { section: '提交与锁' },
    },
  ],
  limitations: ['知识来源为合成演示语料（fixture-backed），不是真实法规原文。'],
  clarification_questions: [],
  context_stale: false,
  handoff_target: null,
};

const runSucceeded = (answer: Answer): Run => ({
  id: 'run_1',
  session_id: 'sess_1',
  user_message_id: 'msg_user',
  status: 'succeeded',
  stage: 'completed',
  attempt: 1,
  created_at: '2026-01-01T00:00:00+00:00',
  deadline_at: '2026-01-01T00:02:00+00:00',
  started_at: '2026-01-01T00:00:00+00:00',
  finished_at: '2026-01-01T00:00:01+00:00',
  assistant_message_id: 'msg_assistant',
  result: answer,
  error: null,
});

const queuedRun: Run = {
  ...runSucceeded(ANSWER),
  status: 'queued',
  stage: 'queued',
  result: null,
  assistant_message_id: null,
};

const fakeClient = (overrides: Partial<AssistantClient> = {}) => {
  const client = {
    createSnapshot: vi.fn(async () => ({
      id: 'snap_1',
      workspace_id: 'ws_demo_01',
      document_id: 'doc-1',
      content_sha256: 'a'.repeat(64),
      version_label: null,
      created_by: 'user_a',
      created_at: '2026-01-01T00:00:00+00:00',
    })),
    createSession: vi.fn(async () => SESSION),
    listSessions: vi.fn(async () => ({ items: [], next_cursor: null })),
    getSession: vi.fn(async () => SESSION),
    createRun: vi.fn(async () => ({ ...queuedRun, poll_after_ms: 0 })),
    getRun: vi.fn(async () => runSucceeded(ANSWER)),
    cancelRun: vi.fn(async () => ({
      run_id: 'run_1',
      status: 'cancelled' as const,
      cancelled_at: '2026-01-01T00:00:01+00:00',
    })),
    listMessages: vi.fn(async () => ({ items: [], next_cursor: null })),
    getCitation: vi.fn(async () => ({
      citation_id: 'cite_1',
      source_type: 'product_manual' as const,
      title: '合成产品手册',
      source_version: 'demo-1',
      excerpt: '提交成功后释放编辑锁。',
      locator: { section: '提交与锁' },
      effective_from: '2024-01-01',
      effective_to: null,
      retrieved_at: null,
    })),
    putFeedback: vi.fn(async () => ({
      id: 'fb_1',
      message_id: 'msg_assistant',
      rating: 'helpful' as const,
      categories: [],
      comment: null,
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    })),
    ...overrides,
  };
  return client as unknown as AssistantClient;
};

const renderPanel = (client: AssistantClient = fakeClient(), selection: AssistantSelection | null = null) =>
  render(
    <KnowledgePanel
      documentId="doc-1"
      digest={'a'.repeat(64)}
      text="提交成功后释放编辑锁。"
      selection={selection}
      client={client}
      pollDelayMs={0}
    />,
  );

const ask = async (question = '编辑锁在提交后会释放吗？') => {
  await userEvent.type(screen.getByLabelText('Knowledge question'), question);
  await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
};


describe('KnowledgePanel', () => {
  it('shows a truthful onboarding card and contextual suggestions without starting a run', async () => {
    const client = fakeClient();
    renderPanel(client);

    expect(screen.getByText('What can I ask?')).toBeTruthy();
    expect(screen.getByText('Can:')).toBeTruthy();
    expect(screen.getByText('Cannot:')).toBeTruthy();
    expect(screen.getByText('How:')).toBeTruthy();
    expect(screen.getByText(/Product and operations FAQ/)).toBeTruthy();
    expect(screen.getByText(/No edits/)).toBeTruthy();
    expect(screen.queryByText('Answer · answered')).toBeNull();

    const help = screen.getByRole('button', { name: 'What can you do?' });
    expect(help).toBeTruthy();
    expect(
      screen.getByRole('button', { name: 'What documents are required for the application?' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', {
        name: 'What does URDG 758 article 20 require for claims?',
      }),
    ).toBeTruthy();

    await userEvent.click(help);

    const question = screen.getByLabelText('Knowledge question') as HTMLTextAreaElement;
    expect(question.value).toBe('What can you do?');
    expect(document.activeElement).toBe(question);
    expect(client.createRun).not.toHaveBeenCalled();
    expect(screen.queryByText('Answer · answered')).toBeNull();
  });

  it('offers an explain-selection prompt instead of help when text is selected', () => {
    renderPanel(fakeClient(), {
      nodeId: 'block_0',
      startOffset: 0,
      endOffset: 6,
      selectedText: '提交成功',
    });

    expect(screen.getByRole('button', { name: 'What does this passage mean?' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'What can you do?' })).toBeNull();
    expect(
      screen.getByRole('button', { name: 'What documents are required for the application?' }),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', {
        name: 'What does URDG 758 article 20 require for claims?',
      }),
    ).toBeTruthy();
  });

  it('collapses suggestions after the first answer and lets the user restore them', async () => {
    renderPanel(fakeClient());

    await ask();
    await screen.findByText('Answer · answered');

    expect(screen.queryByRole('button', { name: 'What can you do?' })).toBeNull();
    const show = screen.getByRole('button', { name: 'Show examples' });
    await userEvent.click(show);

    expect(screen.getByRole('button', { name: 'What can you do?' })).toBeTruthy();
  });

  it('reports a completed knowledge run to the activity callback', async () => {
    const onActivity = vi.fn();
    render(
      <KnowledgePanel
        documentId="doc-1"
        digest={'a'.repeat(64)}
        text="text"
        locale="en"
        client={fakeClient()}
        pollDelayMs={0}
        onActivity={onActivity}
      />,
    );

    await ask();
    await waitFor(() =>
      expect(onActivity).toHaveBeenCalledWith(
        'knowledge',
        'Knowledge answer',
        'Knowledge answer: answered',
      ),
    );
  });

  it('labels the answer as fixture-backed and renders claims, citations and limitations', async () => {
    const client = fakeClient();
    renderPanel(client);

    expect(screen.getByText(/Fixture-backed: answers use synthetic demo sources/i)).toBeTruthy();
    await ask();

    await screen.findByText('Answer · answered');
    expect(screen.getByText('Support: strong')).toBeTruthy();
    expect(screen.getByText('提交成功后释放编辑锁。')).toBeTruthy();
    expect(screen.getByText(/合成演示语料/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open citation 合成产品手册' })).toBeTruthy();
    expect(screen.getByText(/Conversation sess_1/)).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Open citation 合成产品手册' }));
    const region = await screen.findByRole('region', { name: 'Citation detail' });
    expect(within(region).getByText('提交成功后释放编辑锁。')).toBeTruthy();
    expect(within(region).getByText(/提交与锁/)).toBeTruthy();
  });

  it('sends the selection and the snapshot digest with the first question', async () => {
    const client = fakeClient();
    renderPanel(client, {
      nodeId: 'block_0',
      startOffset: 0,
      endOffset: 6,
      selectedText: '提交成功',
    });

    expect(screen.getByText(/Selected passage: “提交成功”/)).toBeTruthy();
    await ask('这段文本是什么意思？');

    await screen.findByText('Answer · answered');
    expect(client.createSnapshot).toHaveBeenCalledWith(
      expect.objectContaining({ document_id: 'doc-1', content_sha256: 'a'.repeat(64) }),
      expect.anything(),
    );
    expect(client.createRun).toHaveBeenCalledWith(
      'sess_1',
      expect.objectContaining({
        selection: {
          nodeId: 'block_0',
          startOffset: 0,
          endOffset: 6,
          selectedText: '提交成功',
        },
      }),
      expect.any(String),
      expect.anything(),
    );
  });

  it('saves feedback and says it does not change the answer', async () => {
    const client = fakeClient();
    renderPanel(client);
    await ask();
    await screen.findByText('Answer · answered');

    await userEvent.click(screen.getByRole('button', { name: 'Helpful' }));

    await screen.findByText(/Feedback saved: helpful/);
    expect(client.putFeedback).toHaveBeenCalledWith(
      'msg_assistant',
      { rating: 'helpful' },
      expect.anything(),
    );
  });

  it('shows no citations when the answer says evidence is insufficient', async () => {
    const answer: Answer = {
      ...ANSWER,
      outcome: 'insufficient_evidence',
      support_level: 'insufficient',
      claims: [],
      citations: [],
      limitations: ['没有找到足以支持回答的已发布证据。'],
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(answer)) }));

    await ask();
    await screen.findByText('Answer · insufficient_evidence');
    expect(screen.getByText(/No citation is shown because no evidence supported/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Open citation/ })).toBeNull();
  });

  it('renders clarification questions and handoff without fake citations', async () => {
    const clarification: Answer = {
      ...ANSWER,
      outcome: 'needs_clarification',
      support_level: 'not_applicable',
      claims: [],
      citations: [],
      limitations: [],
      clarification_questions: ['请确认适用的规则版本与法域。'],
    };
    const { unmount } = renderPanel(
      fakeClient({ getRun: vi.fn(async () => runSucceeded(clarification)) }),
    );
    await ask();
    await screen.findByText('Answer · needs_clarification');
    expect(screen.getByText('请确认适用的规则版本与法域。')).toBeTruthy();
    unmount();

    const handoff: Answer = {
      ...clarification,
      outcome: 'needs_handoff',
      support_level: 'not_applicable',
      clarification_questions: [],
      handoff_target: 'automation',
      limitations: ['该请求需要转交 automation 处理。'],
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(handoff)) }));
    await ask('帮我改写这段条款');
    await screen.findByText('Answer · needs_handoff');
    expect(screen.getByText(/belongs to automation/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Open citation/ })).toBeNull();
  });

  it('distinguishes a technical failure from insufficient evidence', async () => {
    const failed: Run = {
      ...queuedRun,
      status: 'failed',
      stage: 'failed',
      error: {
        code: 'ASSISTANT_FAILED',
        message: 'assistant run failed',
        request_id: 'req_1',
        retryable: false,
      },
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => failed) }));

    await ask();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(explainError('ASSISTANT_FAILED'));
    expect(alert.textContent).not.toContain(explainError('insufficient_evidence'));
  });

  it('reports an anchor mismatch and asks for a new selection', async () => {
    const client = fakeClient({
      createRun: vi.fn(async () => {
        throw new ApiError(409, 'ANCHOR_MISMATCH', 'selection does not match');
      }),
    });
    renderPanel(client, {
      nodeId: 'block_0',
      startOffset: 0,
      endOffset: 6,
      selectedText: '提交成功',
    });

    await ask('这段文本是什么意思？');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(explainError('ANCHOR_MISMATCH'));
    expect(screen.getByText(/Select it again/)).toBeTruthy();
  });

  it('cancels an active run and publishes nothing', async () => {
    const running: Run = { ...queuedRun, status: 'running', stage: 'retrieving' };
    const client = fakeClient({ getRun: vi.fn(async () => running) });
    renderPanel(client);

    await ask();
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel run' }));

    await waitFor(() => expect(client.cancelRun).toHaveBeenCalled());
    await screen.findByText(/Run cancelled — no answer was published/);
    expect(screen.queryByText(/Answer ·/)).toBeNull();
  });

  it('shows a not-found error without leaking another user’s data', async () => {
    const client = fakeClient({
      getRun: vi.fn(async () => {
        throw new ApiError(404, 'RESOURCE_NOT_FOUND', 'run not found');
      }),
    });
    renderPanel(client);

    await ask();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(explainError('RESOURCE_NOT_FOUND'));
    expect(screen.queryByText(/合成产品手册/)).toBeNull();
  });

  it('warns that an older snapshot needs a new conversation', async () => {
    const stale = { ...SESSION, context_stale: true };
    renderPanel(fakeClient({ getSession: vi.fn(async () => stale) }));

    await ask();
    await screen.findByText('Answer · answered');
    expect(screen.getByText(/bound to an older document snapshot/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Start new conversation' })).toBeTruthy();
  });
});

describe('web layer opt-in (knowledge-retrieval-layers)', () => {
  const toggle = () =>
    screen.getByRole('checkbox', { name: /Search the web for the latest/i }) as HTMLInputElement;

  it('is off by default, explains the boundary, and sends web_search false', async () => {
    const client = fakeClient();
    renderPanel(client);

    expect(toggle().checked).toBe(false);
    expect(screen.getByText(/Off: only published sources/i)).toBeTruthy();

    await ask();
    expect(client.createRun).toHaveBeenCalledWith(
      'sess_1',
      expect.objectContaining({ web_search: false }),
      expect.any(String),
      expect.anything(),
    );
  });

  it('previews what will and will not be sent when enabled', async () => {
    const client = fakeClient();
    renderPanel(client);

    await userEvent.click(toggle());

    expect(toggle().checked).toBe(true);
    expect(screen.getByText(/Will send: the screened question only/i)).toBeTruthy();
    expect(screen.getByText(/Will not send: document text/i)).toBeTruthy();

    await ask();
    expect(client.createRun).toHaveBeenCalledWith(
      'sess_1',
      expect.objectContaining({ web_search: true }),
      expect.any(String),
      expect.anything(),
    );
  });

  it('shows the blocking reason instead of pretending nothing was found', async () => {
    const blocked: Answer = {
      ...ANSWER,
      retrieval: [
        { layer: 'web', status: 'blocked', detail: 'contains_selection', retrieved_at: null },
      ],
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(blocked)) }));

    await ask();

    expect(await screen.findByText(/Web search blocked \(contains_selection\)/i)).toBeTruthy();
  });

  it('says when the web layer failed instead of implying live verification', async () => {
    const failed: Answer = {
      ...ANSWER,
      retrieval: [{ layer: 'web', status: 'failed', detail: 'timeout', retrieved_at: null }],
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(failed)) }));

    await ask();

    expect(await screen.findByText(/Web search did not complete/i)).toBeTruthy();
  });

  it('groups citations by source and labels web evidence as unverified', async () => {
    const withWeb: Answer = {
      ...ANSWER,
      processor: 'doubao:seed-1',
      retrieval: [
        { layer: 'web', status: 'ok', detail: null, retrieved_at: '2026-11-16T00:00:00Z' },
      ],
      citations: [
        ANSWER.citations[0],
        {
          id: 'cite_web',
          source_type: 'approved_web',
          title: 'ICC guidance on demand guarantee claims',
          source_version: '2026-11-16T00:00:00Z',
          locator: {
            url: 'https://iccwbo.org/opinions/claims',
            domain: 'iccwbo.org',
            retrieved_at: '2026-11-16T00:00:00Z',
          },
        },
      ],
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(withWeb)) }));

    await ask();
    await screen.findByText('Answer · answered');

    expect(screen.getByText('Published corpus (1)')).toBeTruthy();
    expect(screen.getByText('Web (1)')).toBeTruthy();
    expect(screen.getByText(/Unverified third-party/)).toBeTruthy();
    expect(screen.getByText(/Processor: doubao:seed-1/)).toBeTruthy();
    expect(screen.getByText(/Stored question: redacted/i)).toBeTruthy();
    expect(screen.queryByText('Document (1)')).toBeNull();
  });

  it('labels general web answers as unverified and groups them separately', async () => {
    const general: Answer = {
      ...ANSWER,
      processor: 'doubao:seed-1',
      retrieval: [
        { layer: 'web', status: 'ok', detail: 'general_web', retrieved_at: '2026-11-16T00:00:00Z' },
      ],
      citations: [
        {
          id: 'web_1',
          source_type: 'general_web',
          title: 'Market update',
          source_version: '2026-11-16T00:00:00Z',
          locator: {
            url: 'https://iccwbo.org/news/1',
            domain: 'iccwbo.org',
            retrieved_at: '2026-11-16T00:00:00Z',
          },
        },
      ],
      limitations: ['This answer comes from general web search: unverified third-party content.'],
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(general)) }));

    await ask();
    await screen.findByText('Answer · answered');

    expect(screen.getByText('General web (1)')).toBeTruthy();
    expect(screen.getByText(/General web answer — unverified/i)).toBeTruthy();
    expect(screen.queryByText(/^Web \(\d+\)$/)).toBeNull();
    expect(screen.queryByText('Published corpus (1)')).toBeNull();
  });
});

const CAPABILITIES = (over: Partial<Capabilities> = {}): Capabilities => ({
  model: { configured: false, label: null, approved_processor: false },
  layers: { local: true, approved_web: false, general_web: false },
  egress: { policy_version: 'v1', allowed_domains: 5, loaded: true },
  web: { provider: 'off' },
  ...over,
});

describe('capabilities and provenance (assistant-transparency)', () => {
  it('disables the toggle when the server has no web layer', async () => {
    const client = fakeClient({ getCapabilities: vi.fn(async () => CAPABILITIES()) });
    renderPanel(client);

    const toggle = await screen.findByRole('checkbox', { name: /Search the web for the latest/i });
    expect((toggle as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/Web is not available on this server/i)).toBeTruthy();
  });

  it('relabels the toggle when only the general channel exists', async () => {
    const client = fakeClient({
      getCapabilities: vi.fn(async () =>
        CAPABILITIES({ layers: { local: true, approved_web: false, general_web: true } }),
      ),
    });
    renderPanel(client);

    expect(
      await screen.findByRole('checkbox', { name: /Ask general web \(unverified\)/i }),
    ).toBeTruthy();
  });

  it('explains a skipped web search from the answer summary', async () => {
    const skipped: Answer = {
      ...ANSWER,
      route: 'published',
      web: {
        requested: true,
        status: 'skipped',
        reason: 'web_unavailable',
        hint: 'This server has no web provider configured.',
      },
    };
    renderPanel(fakeClient({ getRun: vi.fn(async () => runSucceeded(skipped)) }));

    await ask();

    expect(await screen.findByText(/Web search skipped \(web_unavailable\)/i)).toBeTruthy();
    expect(screen.getByText(/This server has no web provider configured/i)).toBeTruthy();
    expect(screen.getByText(/Answered from published sources · web not needed/i)).toBeTruthy();
  });

  it('does not invent a web explanation for old answers without the summary', async () => {
    renderPanel(fakeClient());

    await ask();
    await screen.findByText('Answer · answered');

    expect(screen.queryByText(/web not needed/i)).toBeNull();
    expect(screen.queryByText(/Web search skipped/i)).toBeNull();
  });
});
