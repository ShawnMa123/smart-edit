/** Server automation registry client: URLs, payloads and the project error contract. */

import { describe, expect, it, vi } from 'vitest';

import {
  applyTemplate,
  createConnector,
  createTemplate,
  deleteTemplate,
  duplicateTemplate,
  dispatch,
  listTemplates,
  preparePayload,
  renameTemplate,
  saveMapping,
  saveVariables,
  suggestVariables,
} from './automationRegistry';
import { ApiError } from './errors';

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('automationRegistry client', () => {
  it('posts a template with the CSRF header and keeps the payload', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ template_id: 'tpl_1' }));
    const result = await createTemplate(
      { name: 'Guarantee', text: 'Amount: 1', source_kind: 'edited' },
      { fetchImpl },
    );

    expect(result.template_id).toBe('tpl_1');
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toContain('/automation/templates');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect(init.headers['X-Requested-With']).toBe('smart-edit');
    expect(JSON.parse(init.body).text).toBe('Amount: 1');
  });

  it('turns use_llm off with a query flag and keeps GET reads header-free', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ items: [] }));

    await suggestVariables('tpl_1', false, { fetchImpl });
    await listTemplates({ fetchImpl });

    expect(fetchImpl.mock.calls[0][0]).toContain('/templates/tpl_1/variables/suggest?use_llm=false');
    expect(fetchImpl.mock.calls[1][1].method).toBe('GET');
    expect(fetchImpl.mock.calls[1][1].headers).toBeUndefined();
  });

  it('surfaces the backend error code and message', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        json({ error: { code: 'host_not_allowed', message: 'dispatch refused' } }, 403),
      );

    await expect(
      dispatch({ template_id: 'tpl_1', connector_id: 'con_1' }, { fetchImpl }),
    ).rejects.toMatchObject({ code: 'host_not_allowed', status: 403 });
  });

  it('sends values, prepare input and connector auth as JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ dispatch_id: 'dsp_1' }));

    await preparePayload('tpl_1', { document_id: 'demo-document' }, { fetchImpl });
    await createConnector(
      { name: 'ERP', base_url: 'https://erp.example.com', auth_kind: 'header', secret_env: 'ERP_TOKEN' },
      { fetchImpl },
    );
    await dispatch(
      { template_id: 'tpl_1', connector_id: 'con_1', values: { amount: 'USD 1.00' } },
      { fetchImpl },
    );
    await saveVariables('tpl_1', [], { fetchImpl });

    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      document_id: 'demo-document',
    });
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body).secret_env).toBe('ERP_TOKEN');
    expect(JSON.parse(fetchImpl.mock.calls[2][1].body).values).toEqual({ amount: 'USD 1.00' });
    expect(JSON.parse(fetchImpl.mock.calls[3][1].body)).toEqual({ variables: [] });
  });

  it('posts the OpenAPI spec with the connector and persists the field mapping', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(json({ connector_id: 'con_1' }))
      .mockResolvedValueOnce(json({ connector_id: 'con_1', body_map: { amount: 'amount' } }));

    await createConnector(
      {
        name: 'Trade intake',
        base_url: 'https://intake.example.com',
        spec: { openapi: '3.0.3', paths: {} },
        operation: 'POST /trade/applications',
      },
      { fetchImpl },
    );
    await saveMapping('con_1', { amount: 'amount' }, 'tpl_1', { fetchImpl });

    const [specUrl, specInit] = fetchImpl.mock.calls[0];
    expect(specUrl).toContain('/automation/connectors');
    expect(JSON.parse(specInit.body).operation).toBe('POST /trade/applications');
    expect(JSON.parse(specInit.body).spec.openapi).toBe('3.0.3');

    const [mappingUrl, mappingInit] = fetchImpl.mock.calls[1];
    expect(mappingUrl).toContain('/automation/connectors/con_1/mapping');
    expect(mappingInit.method).toBe('PUT');
    expect(JSON.parse(mappingInit.body)).toEqual({ body_map: { amount: 'amount' }, template_id: 'tpl_1' });
  });

  it('asks prepare for a spec body by passing the connector id', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ request_body: { amount: 1 } }));

    const result = await preparePayload(
      'tpl_1',
      { document_id: 'demo-document', connector_id: 'con_1' },
      { fetchImpl },
    );

    expect(result.request_body).toEqual({ amount: 1 });
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body).connector_id).toBe('con_1');
  });

  it('manages the template lifecycle and applies it to a new document', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(json({ template_id: 'tpl_1', name: 'Alpha' }))
      .mockResolvedValueOnce(json({ template_id: 'tpl_2', name: 'Alpha (copy)' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json({ document_id: 'doc_9' }));

    await renameTemplate('tpl_1', 'Alpha', { fetchImpl });
    await duplicateTemplate('tpl_1', 'Alpha (copy)', { fetchImpl });
    await deleteTemplate('tpl_2', { fetchImpl });
    const applied = await applyTemplate('tpl_1', { values: { amount: 'USD 1.00' } }, { fetchImpl });

    expect(applied.document_id).toBe('doc_9');
    expect(fetchImpl.mock.calls[0][1].method).toBe('PUT');
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({ name: 'Alpha' });
    expect(fetchImpl.mock.calls[1][0]).toContain('/automation/templates/tpl_1/duplicate');
    expect(fetchImpl.mock.calls[2][1].method).toBe('DELETE');
    expect(fetchImpl.mock.calls[3][0]).toContain('/templates/tpl_1/apply');
    expect(JSON.parse(fetchImpl.mock.calls[3][1].body)).toEqual({ values: { amount: 'USD 1.00' } });
  });

  it('wraps network failures in ApiError', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error('boom'));

    await expect(listTemplates({ fetchImpl })).rejects.toBeInstanceOf(ApiError);
  });
});