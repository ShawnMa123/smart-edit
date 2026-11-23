/** Server automation panel: template → AI variables → values → real dispatch (mocked client). */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AutomationServerPanel } from './AutomationServerPanel';
import type {
  Connector,
  DispatchReceipt,
  PreparedPayload,
  RegistryClient,
  ServerTemplate,
  TemplateSuggestion,
  TemplateVariable,
} from '../api/automationRegistry';

const amountVariable: TemplateVariable = {
  key: 'amount',
  label: 'amount',
  value_type: 'amount',
  required: true,
  quote: 'Amount: {{amount}}',
  source: 'deterministic',
};

const aiVariable: TemplateVariable = {
  key: 'advising_bank',
  label: 'advising_bank',
  value_type: 'string',
  required: false,
  quote: null,
  source: 'llm',
};

function template(overrides: Partial<ServerTemplate> = {}): ServerTemplate {
  return {
    template_id: 'tpl_1',
    name: 'Demand guarantee',
    version: '1.0.0',
    source_kind: 'edited',
    text_chars: 120,
    variables: [],
    variables_source: null,
    created_by: 'usr_demo',
    created_at: '2026-11-20T00:00:00Z',
    updated_at: '2026-11-20T00:00:00Z',
    ...overrides,
  };
}

const connector: Connector = {
  connector_id: 'con_1',
  name: 'ERP',
  base_url: 'https://erp.example.com',
  path: '/hooks/smart-edit',
  method: 'POST',
  auth_kind: 'header',
  auth_header: 'X-Api-Key',
  secret_env: 'ERP_TOKEN',
  secret_configured: true,
  timeout_seconds: 10,
  extra_headers: {},
  created_at: '2026-11-20T00:00:00Z',
  request_fields: [],
  body_map: {},
  spec_warnings: [],
};

const prepared: PreparedPayload = {
  template_id: 'tpl_1',
  template_name: 'Demand guarantee',
  template_version: '1.0.0',
  document_id: 'demo-document',
  values: {
    amount: { value: 'USD 750,000.00', quote: 'Amount: USD 750,000.00', source: 'document' },
  },
  payload: {
    template: { template_id: 'tpl_1', name: 'Demand guarantee', version: '1.0.0' },
    values: { amount: 'USD 750,000.00' },
  },
  missing_required: [],
  body_mapping: {},
  body_issues: [],
  unmapped_required: [],
};

const receipt: DispatchReceipt = {
  dispatch_id: 'dsp_1',
  template_id: 'tpl_1',
  connector_id: 'con_1',
  status: 'succeeded',
  status_code: 200,
  latency_ms: 42,
  request: { values: { amount: 'USD 750,000.00' } },
  response_excerpt: '{"downstream_id":"down-1"}',
  error_code: null,
  created_at: '2026-11-20T00:00:01Z',
};

function client(overrides: Partial<RegistryClient> = {}): RegistryClient {
  return {
    listTemplates: vi.fn().mockResolvedValue({ items: [] }),
    createTemplate: vi.fn().mockResolvedValue(template()),
    renameTemplate: vi.fn().mockResolvedValue(template()),
    duplicateTemplate: vi.fn().mockResolvedValue({ ...template(), template_id: 'tpl_2' }),
    deleteTemplate: vi.fn().mockResolvedValue(undefined),
    applyTemplate: vi.fn().mockResolvedValue({
      document_id: 'doc_new',
      draft_id: 'draft_new',
      title: 'Demand guarantee',
      text_chars: 120,
      filled: {},
      missing: [],
    }),
    writeBackTemplate: vi.fn().mockResolvedValue({
      document_id: 'demo-document',
      draft_id: 'draft_1',
      revision: 4,
      applied: { amount: 'USD 750,000.00' },
      skipped: [],
    }),
    buildSpecBody: vi.fn().mockResolvedValue({
      operation: 'POST /trade/applications',
      body: { amount: 750000 },
      mapping: { amount: 'amount' },
      issues: [],
      missing: [],
      invalid: [],
      ready: true,
    }),
    parseSpec: vi.fn().mockResolvedValue({ title: 'Trade Intake API', version: '1.4.0', operations: [] }),
    suggestVariables: vi.fn().mockResolvedValue({} as TemplateSuggestion),
    saveVariables: vi.fn().mockResolvedValue(template()),
    preparePayload: vi.fn().mockResolvedValue(prepared),
    listConnectors: vi.fn().mockResolvedValue({ items: [connector] }),
    createConnector: vi.fn().mockResolvedValue(connector),
    updateConnector: vi.fn().mockResolvedValue(connector),
    disableConnector: vi.fn().mockResolvedValue({ ...connector, disabled_at: '2026-11-20T00:00:02Z' }),
    readConnectorSpec: vi.fn().mockResolvedValue({
      connector_id: 'con_1',
      operation: null,
      spec: {},
    }),
    readMapping: vi.fn().mockResolvedValue({ template_id: "tpl_1", connector_id: "con_1", body_map: {}, configured: false }),
    saveMapping: vi.fn().mockResolvedValue(connector),
    getDocumentTemplate: vi.fn().mockResolvedValue({
      document_id: "demo-document",
      template_id: null,
      template_name: null,
    }),
    bindDocumentTemplate: vi.fn().mockResolvedValue({
      document_id: "demo-document",
      template_id: "tpl_1",
      template_name: "Demand guarantee",
    }),
    listDispatches: vi.fn().mockResolvedValue({ items: [] }),
    previewDispatch: vi.fn().mockResolvedValue({
      url: 'https://erp.example.com/hooks/smart-edit',
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Api-Key': '***' },
      body: { amount: 750000 },
      content_type: 'application/json',
      operation: 'POST /trade/applications',
      schema_kind: 'openapi',
      issues: [],
      refusal: null,
    }),
    dispatch: vi.fn().mockResolvedValue(receipt),
    ...overrides,
  };
}

describe('AutomationServerPanel', () => {
  it('saves the draft as a server template and confirms AI variables', async () => {
    const saveVariables = vi.fn().mockResolvedValue(
      template({ variables: [amountVariable, aiVariable], variables_source: 'manual' }),
    );
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValueOnce({ items: [] })
        .mockResolvedValue({ items: [template()] }),
      suggestVariables: vi.fn().mockResolvedValue({
        template_id: 'tpl_1',
        variables: [amountVariable, aiVariable],
        suggested_by: 'merged',
        model: 'doubao:test',
        warnings: ['quote_not_found:advising_bank'],
      }),
      saveVariables,
    });
    render(
      <AutomationServerPanel
        documentId="demo-document"
        text={"DEMAND GUARANTEE\nAmount: {{amount}}"}
        client={fake}
      />,
    );

    await waitFor(() => expect(screen.getByText(/No server template yet/)).toBeTruthy());
    // The name is derived from the draft's first line; type a deliberate one to prove it wins.
    const nameInput = screen.getByLabelText('Template name');
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, 'Demand guarantee');
    await userEvent.click(screen.getByRole('button', { name: 'Save current draft as template' }));

    await waitFor(() =>
      expect(fake.createTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'Demand guarantee',
          text: 'DEMAND GUARANTEE\nAmount: {{amount}}',
          document_id: 'demo-document',
        }),
      ),
    );

    await userEvent.click(screen.getByRole('button', { name: 'Find variables with AI' }));
    await waitFor(() => expect(screen.getByText('amount', { selector: 'strong' })).toBeTruthy());
    expect(screen.getByText('AI')).toBeTruthy();
    expect(screen.getByText(/quote_not_found:advising_bank/)).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: /Confirm 2 variables/ }));
    await waitFor(() =>
      expect(saveVariables).toHaveBeenCalledWith('tpl_1', [amountVariable, aiVariable]),
    );
  });

  it('shows the downstream OpenAPI mapping and persists a change', async () => {
    const specConnector: Connector = {
      ...connector,
      operation: 'POST /trade/applications',
      operation_method: 'POST',
      operation_path: '/trade/applications',
      spec_title: 'Trade Intake API',
      spec_version: '1.4.0',
      content_type: 'application/json',
      request_fields: [
        { path: 'amount', type: 'number', required: true, enum: [] },
        { path: 'beneficiary.name', type: 'string', required: true, enum: [] },
      ],
      body_map: { amount: 'amount' },
    };
    const saveMapping = vi.fn().mockResolvedValue(specConnector);
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      listConnectors: vi.fn().mockResolvedValue({ items: [specConnector] }),
      saveMapping,
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() =>
      expect(screen.getByTestId('spec-operation').textContent).toContain('POST /trade/applications'),
    );
    expect(screen.getByTestId('spec-operation').textContent).toContain('Trade Intake API 1.4.0');
    // The editable mapping moved to "3 · Downstream" behind a disclosure.
    await userEvent.click(screen.getByText(/^Field mapping ·/));
    await waitFor(() =>
      expect((screen.getByLabelText('Variable for amount') as HTMLSelectElement).value).toBe('amount'),
    );

    await userEvent.selectOptions(screen.getByLabelText('Variable for beneficiary.name'), 'amount');
    await userEvent.click(screen.getByRole('button', { name: 'Save mapping' }));

    await waitFor(() =>
      expect(saveMapping).toHaveBeenCalledWith(
        'con_1',
        {
          amount: 'amount',
          'beneficiary.name': 'amount',
        },
        'tpl_1',
      ),
    );
  });

  it('previews the spec body and blocks Send while the body is incomplete', async () => {
    const specConnector: Connector = {
      ...connector,
      operation: 'POST /trade/applications',
      spec_title: 'Trade Intake API',
      spec_version: '1.4.0',
      request_fields: [{ path: 'amount', type: 'number', required: true, enum: [] }],
      body_map: { amount: 'amount' },
    };
    const blocked: PreparedPayload = {
      ...prepared,
      connector_id: 'con_1',
      content_type: 'application/json',
      request_body: {},
      body_mapping: { amount: 'amount' },
      body_issues: [{ path: 'amount', reason: 'missing', message: 'Required field is empty.' }],
      unmapped_required: ['amount'],
    };
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      listConnectors: vi.fn().mockResolvedValue({ items: [specConnector] }),
      preparePayload: vi.fn().mockResolvedValue(blocked),
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByText(/1 confirmed/)).toBeTruthy());

    await waitFor(() => expect(screen.getByTestId('spec-body-issues').textContent).toContain('amount'));
    expect(screen.getByTestId('spec-body-note').textContent).toContain('POST /trade/applications');
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('send-blocked').textContent).toContain('amount');
    expect(screen.getByTestId('automation-next').textContent).toContain('request-body issue');
  });

  it('keeps the receipt informational — Send is the only action', async () => {
    const dispatch = vi.fn().mockResolvedValue(receipt);
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      dispatch,
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByLabelText('Payload preview')).toBeTruthy());
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(screen.getByLabelText('Dispatch receipt')).toBeTruthy());

    const receiptCard = screen.getByLabelText('Dispatch receipt');
    expect(receiptCard.textContent).toContain('succeeded');
    expect(within(receiptCard).queryByRole('button')).toBeNull();

    // Sending again is still possible with the one Send button.
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(2));
  });

  it('filters the dispatch history by status', async () => {
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      listDispatches: vi.fn().mockResolvedValue({
        items: [
          { ...receipt, dispatch_id: 'dsp_ok', status: 'succeeded' },
          { ...receipt, dispatch_id: 'dsp_no', status: 'refused' },
        ],
      }),
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByTestId('dispatch-history')).toBeTruthy());
    expect(screen.getByTestId('dispatch-history').textContent).toContain('succeeded');
    expect(screen.getByTestId('dispatch-history').textContent).toContain('refused');

    await userEvent.click(screen.getByText(/^Recent dispatches/));
    await userEvent.selectOptions(screen.getByLabelText('Receipt filter'), 'refused');
    expect(screen.getByTestId('dispatch-history').textContent).not.toContain('succeeded ·');
    expect(screen.getByTestId('dispatch-history').textContent).toContain('refused');
  });

  it('offers only Review, Preview request and Send in the Review & send card', async () => {
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByText(/1 confirmed/)).toBeTruthy());
    const review = screen.getByLabelText('Review and send');

    // Review is a read-only summary; the only controls are preview and send.
    expect(within(review).getAllByRole('button').map((item) => item.textContent)).toEqual([
      'Preview request',
      'Send',
    ]);
    expect(within(review).queryByText(/More actions/)).toBeNull();
    // The removed setup actions are gone from the whole panel, not just Review & send.
    expect(screen.queryByRole('button', { name: 'Fill from current draft' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Apply values to draft' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Use as new document' })).toBeNull();
    expect(screen.queryByTestId('draft-actions')).toBeNull();
  });

  it('previews the outbound request without sending anything', async () => {
    const previewDispatch = vi.fn().mockResolvedValue({
      url: 'https://erp.example.com/hooks/smart-edit',
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Api-Key': '***' },
      body: { amount: 750000 },
      content_type: 'application/json',
      operation: 'POST /trade/applications',
      schema_kind: 'openapi',
      issues: [],
      refusal: null,
    });
    const dispatch = vi.fn();
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      previewDispatch,
      dispatch,
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByText(/1 confirmed/)).toBeTruthy());
    // Values are filled from the draft automatically; only the preview button is needed.
    await waitFor(() => expect(screen.getByLabelText('Payload preview')).toBeTruthy());
    await userEvent.click(screen.getByTestId('preview-request'));

    await waitFor(() =>
      expect(screen.getByTestId('request-preview').textContent).toContain('erp.example.com'),
    );
    expect(screen.getByTestId('request-preview').textContent).toContain('X-Api-Key');
    expect(screen.getByLabelText('Preview body').textContent).toContain('750000');
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('renames and duplicates the selected template', async () => {
    const renameTemplate = vi.fn().mockResolvedValue(template({ name: 'Renamed' }));
    const duplicateTemplate = vi.fn().mockResolvedValue({
      ...template({ variables: [amountVariable] }),
      template_id: 'tpl_2',
      name: 'Copy',
    });
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      renameTemplate,
      duplicateTemplate,
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByText(/1 confirmed/)).toBeTruthy());
    const renameInput = screen.getByLabelText('Rename template');
    await userEvent.clear(renameInput);
    await userEvent.type(renameInput, 'Renamed');
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }));
    await waitFor(() => expect(renameTemplate).toHaveBeenCalledWith('tpl_1', 'Renamed'));

    await userEvent.click(screen.getByRole('button', { name: 'Duplicate' }));
    await waitFor(() => expect(duplicateTemplate).toHaveBeenCalled());
  });

  it('binds the current document to a template as its document type', async () => {
    const bindDocumentTemplate = vi.fn().mockResolvedValue({
      document_id: 'demo-document',
      template_id: 'tpl_1',
      template_name: 'Demand guarantee',
    });
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      getDocumentTemplate: vi.fn().mockResolvedValue({
        document_id: 'demo-document',
        template_id: 'tpl_old',
        template_name: 'Old kind',
      }),
      bindDocumentTemplate,
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() =>
      expect(screen.getByTestId('document-template-name').textContent).toContain('Old kind'),
    );
    await userEvent.selectOptions(screen.getByLabelText('Document template'), 'tpl_1');
    await userEvent.click(screen.getByTestId('bind-document-template'));

    await waitFor(() =>
      expect(bindDocumentTemplate).toHaveBeenCalledWith('demo-document', 'tpl_1'),
    );
    await waitFor(() =>
      expect(screen.getByTestId('document-template-name').textContent).toContain(
        'Demand guarantee',
      ),
    );
  });

  it('derives the template name from the draft and warns about a new version', async () => {
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ name: 'PURCHASE ORDER' })] }),
    });
    render(<AutomationServerPanel documentId={null} text={'PURCHASE ORDER\nBuyer: ACME'} client={fake} />);

    await waitFor(() =>
      expect((screen.getByLabelText('Template name') as HTMLInputElement).value).toBe(
        'PURCHASE ORDER',
      ),
    );
    expect(screen.getByTestId('template-version-note').textContent).toContain('adds a new version');
  });

  it('keeps mapping, values, preview and Send in one Review & send card', async () => {
    const specConnector: Connector = {
      ...connector,
      operation: 'POST /trade/applications',
      spec_title: 'Trade Intake API',
      spec_version: '1.4.0',
      request_fields: [{ path: 'amount', type: 'number', required: true, enum: [] }],
      body_map: { amount: 'amount' },
    };
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      listConnectors: vi.fn().mockResolvedValue({ items: [specConnector] }),
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByText(/1 confirmed/)).toBeTruthy());
    await waitFor(() => expect(screen.getByLabelText('Payload preview')).toBeTruthy());

    const review = await screen.findByLabelText('Review and send');
    expect(review.contains(screen.getByTestId('spec-mapping'))).toBe(true);
    expect(review.contains(screen.getByLabelText('Payload preview'))).toBe(true);
    expect(review.contains(screen.getByRole('button', { name: 'Send' }))).toBe(true);
    expect(screen.queryByLabelText('Dispatch receipt')).toBeNull(); // appears only after a send
  });

  it('starts the guide at the template step when the server has none', async () => {
    const fake = client({ listTemplates: vi.fn().mockResolvedValue({ items: [] }) });
    render(<AutomationServerPanel documentId={null} text="draft" client={fake} />);

    await waitFor(() =>
      expect(screen.getByTestId('automation-next').textContent).toContain('Pick or save a template'),
    );
    expect(screen.getByTestId('automation-next').textContent).toContain('Step 1/5');
  });

  it('fills values from the draft and sends them to the selected connector', async () => {
    const dispatch = vi.fn().mockResolvedValue(receipt);
    const fake = client({
      listTemplates: vi
        .fn()
        .mockResolvedValue({ items: [template({ variables: [amountVariable] })] }),
      dispatch,
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByText(/1 confirmed/)).toBeTruthy());

    // No "fill" click: the values are built from the draft as soon as Review is ready.
    await waitFor(() =>
      expect(fake.preparePayload).toHaveBeenCalledWith('tpl_1', {
        document_id: 'demo-document',
        text: undefined,
        connector_id: 'con_1',
      }),
    );
    expect(screen.getByLabelText('Payload preview').textContent).toContain('USD 750,000.00');

    await userEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith(
        expect.objectContaining({
          template_id: 'tpl_1',
          connector_id: 'con_1',
          document_id: 'demo-document',
          values: { amount: 'USD 750,000.00' },
        }),
      ),
    );
    await waitFor(() => expect(screen.getByLabelText('Dispatch receipt')).toBeTruthy());
    expect(screen.getByText('succeeded')).toBeTruthy();
    expect(screen.getByText(/42 ms/)).toBeTruthy();
  });

  it('shows the backend error instead of pretending the call worked', async () => {
    const fake = client({
      listTemplates: vi.fn().mockRejectedValue(new Error('denied')),
    });
    render(<AutomationServerPanel documentId="demo-document" text="draft" client={fake} />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.getByRole('alert').textContent).not.toBe('');
  });
});