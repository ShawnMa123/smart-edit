/** Automation workbench: three areas, mock template/variable/mapping flows, boundary labels. */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AutomationPanel } from './AutomationPanel';
import type { AssistantSelection } from '../api/assistantTypes';
import type { DraftView } from '../api/documents';
import openapiFixture from '../../../fixtures/automation/openapi_sample.json';
import {
  TEMPLATE_STORAGE_KEY,
  createTemplateStore,
  type TemplateRecord,
  type TemplateStore,
} from '../automation/templateStore';
import type { InlineNode, RichDocument } from '../rich/richDocument';
import { projectDocument } from '../rich/projection';
import { collectVariables } from '../rich/variableOperations';
import { memoryStorage } from '../versionStore';

const draft: DraftView = {
  document_id: 'doc-1',
  draft_id: 'draft-1',
  title: 'Guarantee',
  revision: 3,
  etag: 'draft-1',
  content: { type: 'doc', content: [] },
  text: '',
  content_sha256: 'a'.repeat(64),
  variables: {},
  variables_version: 1,
  updated_at: null,
};

const paragraph = (text: string): RichDocument['content'][number] => ({
  type: 'paragraph',
  content: [{ type: 'text', text }],
});

const doc = (...content: RichDocument['content']): RichDocument => ({ type: 'doc', content });

const variable = (
  text: string,
  attrs: {
    variableId: string;
    label: string;
    valueType?: 'string' | 'amount' | 'date' | 'currency';
    required?: boolean;
    displayValue?: string | null;
    occurrenceId?: string;
  },
): InlineNode => ({
  type: 'variableReference',
  attrs: {
    variableId: attrs.variableId,
    label: attrs.label,
    valueType: attrs.valueType ?? 'string',
    required: attrs.required ?? false,
    displayValue: attrs.displayValue === undefined ? text : attrs.displayValue,
    occurrenceId: attrs.occurrenceId,
  },
});

const selectionIn = (document: RichDocument, text: string): AssistantSelection => {
  const projection = projectDocument(document);
  const start = projection.text.indexOf(text);
  if (start < 0) throw new Error(`missing ${text}`);
  return {
    nodeId: 'b0',
    startOffset: start,
    endOffset: start + Array.from(text).length,
    selectedText: text,
  };
};

type PanelProps = Parameters<typeof AutomationPanel>[0];

let props: PanelProps;
let storage: Storage;
let templateStore: TemplateStore;

const seedTemplate = (document: RichDocument, name = 'Seed template'): TemplateRecord => {
  const result = templateStore.capture({
    name,
    document,
    source: { kind: 'edited' },
    revision: draft.revision,
    charCount: projectDocument(document).text.length,
    variables: collectVariables(document).map((variable) => ({
      label: variable.label,
      valueType: variable.valueType,
      required: variable.required,
    })),
    now: new Date('2026-11-15T10:00:00Z'),
  });
  if (!result.ok) throw new Error('seed failed');
  return result.record;
};

beforeEach(() => {
  storage = memoryStorage();
  templateStore = createTemplateStore(storage);
  props = {
    draft,
    document: doc(paragraph('Amount: USD 500,000.00')),
    selection: null,
    pendingVariable: null,
    digest: 'b'.repeat(64),
    templateStore,
    onChange: vi.fn(),
    onVariableHandled: vi.fn(),
  };
});

describe('AutomationWorkbench', () => {
  it('shows the three areas and the fixture-backed boundary', () => {
    render(<AutomationPanel {...props} />);

    expect(screen.getByRole('tab', { name: 'Template' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Variables & Fill' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Downstream Mapping' })).toBeTruthy();

    const boundary = screen.getByTestId('automation-boundary').textContent ?? '';
    expect(boundary).toContain('Fixture-backed workbench');
    expect(boundary).toContain('Not implemented');
    expect(boundary).toContain('payload delivery');

    const context = screen.getByTestId('workbench-context').textContent ?? '';
    expect(context).toContain('Draft rev 3');
    expect(context).toContain('document bbbbbbbbbbbb');
    expect(context).toContain('0 variable(s)');
  });

  it('keeps mock state when switching areas', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.click(screen.getByRole('tab', { name: 'Template' }));

    expect(screen.getByTestId('template-item')).toBeTruthy();
  });

  it('captures the current document with a preview and stores it in this browser', async () => {
    const user = userEvent.setup();
    const document = doc({
      type: 'paragraph',
      content: [
        { type: 'text', text: 'Amount: ' },
        variable('USD 500,000.00', { variableId: 'var_1', label: 'amount' }),
      ],
    });
    render(<AutomationPanel {...props} document={document} />);

    const preview = screen.getByTestId('capture-preview').textContent ?? '';
    expect(preview).toContain('Edited in this browser');
    expect(preview).toContain('Revision 3');
    expect(preview).toContain('22 characters');
    expect(preview).toContain('1 variable(s)');
    expect(preview).toContain('v1');
    expect(preview).toContain('amount (string)');

    await user.click(screen.getByRole('button', { name: 'Save as template' }));

    const item = screen.getByTestId('template-item').textContent ?? '';
    expect(item).toContain('Demand guarantee template');
    expect(item).toContain('v1');
    expect(item).toContain('Edited in this browser');
    expect(screen.getByTestId('template-detail').textContent).toContain('amount (string)');
    expect(screen.getByTestId('template-boundary').textContent).toContain(
      'Saved in this browser — not on the server',
    );
    expect(screen.getByTestId('template-boundary').textContent).toContain('Up to 20 templates');
    expect(screen.getByTestId('workbench-status').textContent).toContain('not on the server');
    expect(screen.getByTestId('template-detail').textContent).toContain('Captured content');
    expect(screen.getByTestId('template-excerpt').textContent).toContain('USD 500,000.00');
  });

  it('keeps Template capture available without a server draft, but not server-bound actions', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} draft={null} />);

    expect(screen.getByTestId('no-draft')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Save as template' }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(screen.getByTestId('capture-preview').textContent).toContain('No server draft');

    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    expect(screen.getByTestId('template-item')).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    expect(
      (screen.getByRole('button', { name: 'Mark selection as variable' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByTestId('variable-list').textContent).toContain('No variables yet');

    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    expect(
      (screen.getByRole('button', { name: 'Match document' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('explains why mark-as-variable is unavailable without a selection', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));

    expect(
      (screen.getByRole('button', { name: 'Mark selection as variable' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByTestId('selection-hint').textContent).toContain(
      'non-empty selection inside one paragraph or heading',
    );
  });

  it('marks a selection as a variable, keeping the projected text stable', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onVariableHandled = vi.fn();
    const document = doc(paragraph('Amount: USD 500,000.00'));
    render(
      <AutomationPanel
        {...props}
        document={document}
        selection={selectionIn(document, 'USD 500,000.00')}
        onChange={onChange}
        onVariableHandled={onVariableHandled}
      />,
    );

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    await user.click(screen.getByRole('button', { name: 'Mark selection as variable' }));

    const dialog = screen.getByTestId('variable-dialog');
    const label = within(dialog).getByLabelText('Variable label');
    expect((label as HTMLInputElement).value).toBe('USD 500,000.00');

    await user.clear(label);
    await user.type(label, 'amount');
    await user.selectOptions(within(dialog).getByLabelText('Variable type'), 'amount');
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(within(dialog).getByRole('button', { name: 'Create variable' }));

    expect(onVariableHandled).toHaveBeenCalled();
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as RichDocument;
    const variables = collectVariables(next);
    expect(variables).toHaveLength(1);
    expect(variables[0].label).toBe('amount');
    expect(variables[0].valueType).toBe('amount');
    expect(variables[0].required).toBe(true);
    expect(variables[0].displayValue).toBe('USD 500,000.00');
    expect(projectDocument(next).text).toBe('Amount: USD 500,000.00');
  });

  it('opens the variable dialog from a right-click selection and closes it with Escape', async () => {
    const user = userEvent.setup();
    const onVariableHandled = vi.fn();
    const rich = doc(paragraph('Amount: USD 500,000.00'));
    render(
      <AutomationPanel
        {...props}
        document={rich}
        pendingVariable={selectionIn(rich, 'Amount')}
        onVariableHandled={onVariableHandled}
      />,
    );

    const dialog = screen.getByTestId('variable-dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(globalThis.document.activeElement).toBe(within(dialog).getByLabelText('Variable label'));

    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('variable-dialog')).toBeNull();
    expect(onVariableHandled).toHaveBeenCalled();
  });

  it('fills every occurrence together without touching same-named ordinary text', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const attrs = { variableId: 'var_amount', label: 'amount', valueType: 'amount' as const, required: true };
    const document = doc(
      {
        type: 'paragraph',
        content: [
          { type: 'text', text: 'Amount: ' },
          variable('USD 500,000.00', { ...attrs, occurrenceId: 'occ_1' }),
          { type: 'text', text: ' (amount)' },
        ],
      },
      {
        type: 'paragraph',
        content: [
          { type: 'text', text: 'Repeats: ' },
          variable('USD 500,000.00', { ...attrs, occurrenceId: 'occ_2' }),
        ],
      },
    );
    render(<AutomationPanel {...props} document={document} onChange={onChange} />);

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    await user.click(screen.getByRole('button', { name: /amount · amount/ }));

    const detail = screen.getByTestId('variable-detail');
    expect(within(detail).getAllByRole('listitem')).toHaveLength(2);
    expect(detail.textContent).toContain('→ USD 500,000.00');

    const input = screen.getByLabelText('Variable value');
    await user.clear(input);
    await user.type(input, 'USD 750,000.00');
    expect(screen.getByTestId('variable-detail').textContent).toContain('→ USD 750,000.00');
    await user.click(screen.getByRole('button', { name: 'Fill all occurrences' }));

    const next = onChange.mock.calls[0][0] as RichDocument;
    const variables = collectVariables(next);
    expect(variables[0].occurrences).toHaveLength(2);
    expect(variables[0].displayValue).toBe('USD 750,000.00');
    expect(projectDocument(next).text).toBe(
      'Amount: USD 750,000.00 (amount)\n\nRepeats: USD 750,000.00',
    );
  });

  it('shows matched candidates with evidence, requires confirmation and never sends the payload', async () => {
    const user = userEvent.setup();
    const document = doc(paragraph('This demand guarantee expires on 2027-01-01.'));
    render(<AutomationPanel {...props} document={document} />);

    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.click(screen.getByRole('button', { name: 'Match document' }));

    const fields = screen.getByTestId('mapping-fields');
    expect(fields.textContent).toContain('status: matched');
    expect(fields.textContent).toContain('evidence:');
    expect(fields.textContent).toContain('Not confirmed — stays out of the payload.');

    const preview = screen.getByTestId('payload-preview');
    expect(preview.getAttribute('data-state')).toBe('mapping_not_ready');
    expect(preview.textContent).toContain('Not sent');
    expect(preview.textContent).toContain('missing application_type');
    expect(within(preview).getByText('{}')).toBeTruthy();
    expect(within(preview).queryByRole('button')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Confirm guarantee' }));

    const ready = screen.getByTestId('payload-preview');
    expect(ready.getAttribute('data-state')).toBe('ready');
    expect(ready.textContent).toContain('"application_type": "guarantee"');
    expect(ready.textContent).toContain('document digest bbbbbbbbbbbb');
    expect(screen.getByTestId('mapping-coverage').textContent).toContain('1/1 required');
  });

  it('keeps an ambiguous field unresolved until the operator corrects it', async () => {
    const user = userEvent.setup();
    const document = doc(paragraph('This may be a guarantee or a standby facility.'));
    render(<AutomationPanel {...props} document={document} />);

    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.click(screen.getByRole('button', { name: 'Match document' }));

    expect(screen.getByTestId('mapping-fields').textContent).toContain('status: ambiguous');
    expect(screen.getByTestId('payload-preview').getAttribute('data-state')).toBe(
      'mapping_not_ready',
    );
    expect(screen.queryByRole('button', { name: /Confirm guarantee/ })).toBeNull();

    await user.selectOptions(screen.getByLabelText('Application type value'), 'standby_dc');

    const preview = screen.getByTestId('payload-preview');
    expect(preview.getAttribute('data-state')).toBe('ready');
    expect(preview.textContent).toContain('"application_type": "standby_dc"');
  });

  it('reports a missing required mapping without inventing a payload', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} document={doc(paragraph('No relevant wording here.'))} />);

    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.click(screen.getByRole('button', { name: 'Match document' }));

    expect(screen.getByTestId('mapping-fields').textContent).toContain('status: missing');
    const preview = screen.getByTestId('payload-preview');
    expect(preview.getAttribute('data-state')).toBe('mapping_not_ready');
    expect(preview.textContent).toContain('missing application_type');
    expect(preview.textContent).not.toContain('"application_type"');
  });

  it('disables variable actions when the editor is in the textarea fallback', async () => {
    const user = userEvent.setup();
    const document = doc(paragraph('Amount: USD 500,000.00'));
    render(
      <AutomationPanel
        {...props}
        document={document}
        richEditorAvailable={false}
        selection={selectionIn(document, 'Amount')}
      />,
    );

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));

    expect(screen.getByTestId('fallback-variables').textContent).toContain('rich editor');
    expect(
      (screen.getByRole('button', { name: 'Mark selection as variable' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it('reports a deleted required variable instead of dropping it silently', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const document = doc(paragraph('Amount: USD 500,000.00'));
    const { rerender } = render(
      <AutomationPanel
        {...props}
        document={document}
        selection={selectionIn(document, 'USD 500,000.00')}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    await user.click(screen.getByRole('button', { name: 'Mark selection as variable' }));
    const dialog = screen.getByTestId('variable-dialog');
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(within(dialog).getByRole('button', { name: 'Create variable' }));
    const created = onChange.mock.calls[0][0] as RichDocument;

    // The parent applies the edit, so the variable is present and nothing is reported as missing.
    rerender(
      <AutomationPanel {...props} document={created} onChange={onChange} />,
    );
    expect(screen.queryByTestId('missing-required')).toBeNull();

    // The editor deleted the node; the session registry still knows it was required.
    rerender(
      <AutomationPanel {...props} document={doc(paragraph('Amount: '))} onChange={onChange} />,
    );

    expect(screen.getByTestId('missing-required').textContent).toContain('USD 500,000.00');
    expect(screen.getByTestId('missing-required').textContent).toContain('reported as missing');
  });

  it('moves between areas with the keyboard', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('tab', { name: 'Template' }));
    await user.keyboard('{ArrowRight}');
    expect(
      screen.getByRole('tab', { name: 'Variables & Fill' }).getAttribute('aria-selected'),
    ).toBe('true');

    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Downstream Mapping' }).getAttribute('aria-selected')).toBe(
      'true',
    );
    expect(screen.getByRole('tabpanel')).toBeTruthy();
  });

  it('shows imported provenance and its note before saving', () => {
    const document = {
      ...doc(paragraph('Amount: USD 500,000.00')),
      provenance: 'heuristic' as const,
      provenanceNote: 'font_size_1.42x',
    };
    render(<AutomationPanel {...props} document={document} />);

    const preview = screen.getByTestId('capture-preview').textContent ?? '';
    expect(preview).toContain('Imported · heuristic');
    expect(preview).toContain('font_size_1.42x');
  });

  it('disables capture for an empty document and rejects a blank name', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<AutomationPanel {...props} document={doc()} />);

    expect(screen.getByTestId('template-empty-document')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Save as template' }) as HTMLButtonElement).disabled,
    ).toBe(true);

    rerender(<AutomationPanel {...props} />);
    await user.clear(screen.getByLabelText('Template name'));

    expect(screen.getByTestId('template-name-error').textContent).toContain(
      'Enter a template name',
    );
    expect(
      (screen.getByRole('button', { name: 'Save as template' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(templateStore.list()).toEqual([]);
  });

  it('warns that a duplicate name adds a version instead of overwriting', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    const first = templateStore.list()[0];
    await user.click(screen.getByRole('button', { name: 'Save as template' }));

    expect(screen.getByTestId('duplicate-warning').textContent).toContain('already exists');
    expect(screen.getByTestId('duplicate-warning').textContent).toContain(
      templateStore.nextVersion(),
    );
    const templates = templateStore.list();
    expect(templates).toHaveLength(2);
    expect(templates.find((item) => item.id === first.id)?.version).toBe('v1');
    expect(templates.map((item) => item.version).sort()).toEqual(['v1', 'v2']);
  });

  it('keeps the captured snapshot in the detail after the document changes', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    expect(screen.getByTestId('template-excerpt').textContent).toContain(
      'Amount: USD 500,000.00',
    );

    rerender(<AutomationPanel {...props} document={doc(paragraph('Changed text'))} />);

    expect(screen.getByTestId('template-excerpt').textContent).toContain(
      'Amount: USD 500,000.00',
    );
    expect(screen.getByTestId('template-excerpt').textContent).not.toContain('Changed text');
  });

  it('selects a card and shows its detail', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    await user.click(screen.getByRole('button', { name: 'Save as template' }));

    await user.click(screen.getByRole('button', { name: 'Demand guarantee template · v1' }));
    expect(screen.getByTestId('template-detail').textContent).toContain('v1');

    await user.click(screen.getByRole('button', { name: 'Demand guarantee template · v2' }));
    expect(screen.getByTestId('template-detail').textContent).toContain('v2');
  });

  it('renames a template without changing its id, version or content', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    const before = templateStore.list()[0];

    await user.click(screen.getByRole('button', { name: 'Rename' }));
    const input = screen.getByLabelText('Rename template');
    await user.clear(input);
    await user.click(screen.getByRole('button', { name: 'Save name' }));

    expect(screen.getByTestId('workbench-status').textContent).toContain(
      'Enter a template name',
    );
    expect(templateStore.list()[0].name).toBe('Demand guarantee template');

    await user.type(input, 'Reviewed guarantee');
    await user.click(screen.getByRole('button', { name: 'Save name' }));

    const after = templateStore.list()[0];
    expect(after).toMatchObject({
      id: before.id,
      version: before.version,
      name: 'Reviewed guarantee',
    });
    expect(after.rich).toEqual(before.rich);
    expect(screen.getByTestId('template-item').textContent).toContain('Reviewed guarantee');
    expect(screen.getByTestId('workbench-status').textContent).toContain('Renamed to');
  });

  it('deletes only after explicit confirmation and can cancel', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('button', { name: 'Save as template' }));

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.getByText(/from this browser\?/)).toBeTruthy();
    expect(templateStore.list()).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(templateStore.list()).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(templateStore.list()).toEqual([]);
    expect(screen.getByTestId('template-empty')).toBeTruthy();
    expect(screen.getByTestId('workbench-status').textContent).toContain('Deleted');
  });

  it('restores templates and version numbering after a remount with the same storage', async () => {
    const user = userEvent.setup();
    const first = render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('button', { name: 'Save as template' }));
    first.unmount();

    const reloaded = createTemplateStore(storage);
    render(<AutomationPanel {...props} templateStore={reloaded} />);

    expect(screen.getByTestId('template-item').textContent).toContain(
      'Demand guarantee template',
    );
    expect(screen.getByTestId('capture-preview').textContent).toContain('v2');
    expect(screen.getByTestId('template-boundary').textContent).toContain(
      'Saved in this browser',
    );
  });

  it('reports unreadable stored templates without fabricating any', () => {
    storage.setItem(TEMPLATE_STORAGE_KEY, '{oops');
    render(<AutomationPanel {...props} templateStore={createTemplateStore(storage)} />);

    expect(screen.getByTestId('template-storage-issue').textContent).toContain(
      'could not be read',
    );
    expect(screen.getByTestId('template-empty')).toBeTruthy();
    expect(screen.queryAllByTestId('template-item')).toHaveLength(0);
  });

  it('marks a capture as session-only when browser storage rejects writes', async () => {
    const user = userEvent.setup();
    const blocked = {
      ...memoryStorage(),
      setItem: () => {
        throw new Error('quota');
      },
    } as Storage;
    render(<AutomationPanel {...props} templateStore={createTemplateStore(blocked)} />);

    await user.click(screen.getByRole('button', { name: 'Save as template' }));

    expect(screen.getByTestId('template-item').textContent).toContain(
      'Session only — browser storage failed',
    );
    expect(screen.getByTestId('template-storage-issue').textContent).toContain(
      'Browser storage is unavailable',
    );
    expect(screen.getByTestId('workbench-status').textContent).toContain('session only');
  });

  it('labels template controls and supports rename/delete from the keyboard', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('button', { name: 'Save as template' }));

    const card = screen.getByRole('button', { name: 'Demand guarantee template · v1' });
    expect(card.getAttribute('aria-pressed')).toBe('true');
    card.focus();
    await user.keyboard('{Enter}');

    const rename = screen.getByRole('button', { name: 'Rename' });
    rename.focus();
    await user.keyboard('{Enter}');
    const input = screen.getByLabelText('Rename template');
    expect(globalThis.document.activeElement).toBe(input);
    await user.keyboard('{Escape}');
    expect(screen.queryByLabelText('Rename template')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    const confirmation = screen.getByText(/from this browser\?/);
    expect(confirmation.getAttribute('aria-live')).toBe('polite');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).toBeNull();
  });

  it('applies a template to the editor only after confirmation', async () => {
    const user = userEvent.setup();
    const onApplyTemplate = vi.fn();
    const captured = seedTemplate(doc(paragraph('Template content')));
    render(<AutomationPanel {...props} onApplyTemplate={onApplyTemplate} />);

    await user.click(screen.getByRole('button', { name: `${captured.name} · ${captured.version}` }));
    await user.click(screen.getByRole('button', { name: 'Apply to editor' }));

    expect(onApplyTemplate).not.toHaveBeenCalled();
    expect(screen.getByText(/Replace the current document/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Replace document' }));

    expect(onApplyTemplate).toHaveBeenCalledTimes(1);
    const next = onApplyTemplate.mock.calls[0][0] as RichDocument;
    expect(projectDocument(next).text).toBe('Template content');
    expect(screen.getByTestId('workbench-status').textContent).toContain('Applied');
  });

  it('keeps the document when template apply is cancelled', async () => {
    const user = userEvent.setup();
    const onApplyTemplate = vi.fn();
    const captured = seedTemplate(doc(paragraph('Template content')));
    render(<AutomationPanel {...props} onApplyTemplate={onApplyTemplate} />);

    await user.click(screen.getByRole('button', { name: `${captured.name} · ${captured.version}` }));
    await user.click(screen.getByRole('button', { name: 'Apply to editor' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onApplyTemplate).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Apply to editor' })).toBeTruthy();
  });

  it('applies directly to an empty document without asking for confirmation', async () => {
    const user = userEvent.setup();
    const onApplyTemplate = vi.fn();
    const captured = seedTemplate(doc(paragraph('Template content')));
    render(<AutomationPanel {...props} document={doc()} onApplyTemplate={onApplyTemplate} />);

    await user.click(screen.getByRole('button', { name: `${captured.name} · ${captured.version}` }));
    await user.click(screen.getByRole('button', { name: 'Apply to editor' }));

    expect(onApplyTemplate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Replace document' })).toBeNull();
  });

  it('disables apply when the rich editor is in the textarea fallback', async () => {
    const user = userEvent.setup();
    const captured = seedTemplate(doc(paragraph('Template content')));
    render(
      <AutomationPanel
        {...props}
        richEditorAvailable={false}
        onApplyTemplate={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: `${captured.name} · ${captured.version}` }));

    expect(screen.getByTestId('apply-fallback').textContent).toContain('needs the rich editor');
    expect(
      (screen.getByRole('button', { name: 'Apply to editor' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('tracks applied required variables so deleting them is reported', async () => {
    const user = userEvent.setup();
    const onApplyTemplate = vi.fn();
    const template = doc({
      type: 'paragraph',
      content: [
        { type: 'text', text: 'Amount: ' },
        variable('USD 500,000.00', {
          variableId: 'var_amount',
          label: 'amount',
          required: true,
        }),
      ],
    });
    const captured = seedTemplate(template);
    const { rerender } = render(
      <AutomationPanel {...props} onApplyTemplate={onApplyTemplate} />,
    );

    await user.click(screen.getByRole('button', { name: `${captured.name} · ${captured.version}` }));
    await user.click(screen.getByRole('button', { name: 'Apply to editor' }));
    await user.click(screen.getByRole('button', { name: 'Replace document' }));

    rerender(<AutomationPanel {...props} onApplyTemplate={onApplyTemplate} />);
    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));

    expect(screen.getByTestId('missing-required').textContent).toContain('amount');
  });

  it('updates an existing template with the current document after confirmation', async () => {
    const user = userEvent.setup();
    const onApplyTemplate = vi.fn();
    const captured = seedTemplate(doc(paragraph('Old snapshot')));
    render(<AutomationPanel {...props} onApplyTemplate={onApplyTemplate} />);

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    await user.click(screen.getByRole('button', { name: 'Save to template' }));

    expect(screen.getByText(/previous snapshot will be replaced/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Update template' }));

    const updated = templateStore.get(captured.id);
    expect(updated).toMatchObject({
      id: captured.id,
      name: captured.name,
      version: 'v2',
      boundRevision: draft.revision,
    });
    expect(updated?.rich).toEqual(props.document);
    expect(screen.getByTestId('workbench-status').textContent).toContain('Updated');

    await user.click(screen.getByRole('tab', { name: 'Template' }));
    expect(screen.getByTestId('template-item').textContent).toContain('v2');
    await user.click(screen.getByRole('button', { name: 'Apply to editor' }));
    await user.click(screen.getByRole('button', { name: 'Replace document' }));
    expect(projectDocument(onApplyTemplate.mock.calls[0][0] as RichDocument).text).toBe(
      'Amount: USD 500,000.00',
    );
  });

  it('keeps the template when saving to it is cancelled', async () => {
    const user = userEvent.setup();
    const captured = seedTemplate(doc(paragraph('Old snapshot')));
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    await user.click(screen.getByRole('button', { name: 'Save to template' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(templateStore.get(captured.id)?.version).toBe('v1');
    expect(templateStore.get(captured.id)?.rich).toEqual(doc(paragraph('Old snapshot')));
  });

  it('explains when there is no template or no content to save', async () => {
    const user = userEvent.setup();
    const first = render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    expect(
      (screen.getByRole('button', { name: 'Save to template' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByTestId('save-to-template').textContent).toContain(
      'No template yet — capture one in Template first',
    );
    first.unmount();

    seedTemplate(doc(paragraph('Seed')));
    render(<AutomationPanel {...props} document={doc()} />);
    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    expect(
      (screen.getByRole('button', { name: 'Save to template' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByTestId('save-to-template').textContent).toContain(
      'A template needs document content',
    );
  });

  it('marks a failed template update as session-only', async () => {
    const user = userEvent.setup();
    const backing = memoryStorage();
    const seedStore = createTemplateStore(backing);
    const captured = seedStore.capture({
      name: 'Seed',
      document: doc(paragraph('Old snapshot')),
      source: { kind: 'edited' },
      revision: draft.revision,
      charCount: 12,
      variables: [],
      now: new Date('2026-11-15T10:00:00Z'),
    });
    if (!captured.ok) throw new Error('seed failed');
    const blocked = createTemplateStore({
      ...backing,
      setItem: () => {
        throw new Error('quota');
      },
    } as Storage);
    render(<AutomationPanel {...props} templateStore={blocked} />);

    await user.click(screen.getByRole('tab', { name: 'Variables & Fill' }));
    await user.click(screen.getByRole('button', { name: 'Save to template' }));
    await user.click(screen.getByRole('button', { name: 'Update template' }));

    expect(screen.getByTestId('workbench-status').textContent).toContain('session only');
    expect(blocked.list()[0].persisted).toBe(false);
    expect(createTemplateStore(backing).list()[0].version).toBe('v1');
  });

  it('parses an OpenAPI spec, maps variables and downloads a request JSON', async () => {
    const user = userEvent.setup();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    Object.defineProperty(URL, 'createObjectURL', {
      value: vi.fn(() => 'blob:mock'),
      configurable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true });
    const contractDocument = doc({
      type: 'paragraph',
      content: [
        { type: 'text', text: 'Amount ' },
        variable('500000', { variableId: 'v_amount', label: 'Amount', valueType: 'amount' }),
        { type: 'text', text: ' type ' },
        variable('guarantee', { variableId: 'v_type', label: 'application_type' }),
        { type: 'text', text: ' name ' },
        variable('ACME', { variableId: 'v_name', label: 'Beneficiary Name' }),
      ],
    });
    render(<AutomationPanel {...props} document={contractDocument} />);

    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.selectOptions(screen.getByLabelText('Downstream source'), 'openapi');
    fireEvent.change(screen.getByLabelText('OpenAPI JSON'), {
      target: { value: JSON.stringify(openapiFixture) },
    });
    await user.click(screen.getByRole('button', { name: 'Parse OpenAPI' }));

    expect(screen.getByTestId('openapi-title').textContent).toContain('Trade Intake API');
    expect((screen.getByLabelText('OpenAPI operation') as HTMLSelectElement).value).toBe(
      'POST /trade/applications',
    );
    expect(screen.getByTestId('openapi-fields').textContent).toContain('application_type');
    expect(screen.getByTestId('openapi-fields').textContent).toContain('beneficiary.name');

    const payload = screen.getByTestId('openapi-payload');
    expect(payload.getAttribute('data-state')).toBe('ready');
    expect(payload.textContent).toContain('"amount": 500000');
    expect(payload.textContent).toContain('"application_type": "guarantee"');
    expect(payload.textContent).toContain('"beneficiary"');
    expect(payload.textContent).toContain('Not sent');

    await user.click(screen.getByRole('button', { name: 'Download JSON' }));

    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('workbench-status').textContent).toContain('Downloaded');
    click.mockRestore();
  });

  it('keeps download disabled while required OpenAPI fields are missing', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);

    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.selectOptions(screen.getByLabelText('Downstream source'), 'openapi');
    fireEvent.change(screen.getByLabelText('OpenAPI JSON'), {
      target: { value: JSON.stringify(openapiFixture) },
    });
    await user.click(screen.getByRole('button', { name: 'Parse OpenAPI' }));

    const payload = screen.getByTestId('openapi-payload');
    expect(payload.getAttribute('data-state')).toBe('not_ready');
    expect(payload.textContent).toContain('missing application_type');
    expect(
      (screen.getByRole('button', { name: 'Download JSON' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('rejects unsupported OpenAPI input with a readable error', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.selectOptions(screen.getByLabelText('Downstream source'), 'openapi');
    fireEvent.change(screen.getByLabelText('OpenAPI JSON'), {
      target: { value: '{"swagger":"2.0","paths":{}}' },
    });
    await user.click(screen.getByRole('button', { name: 'Parse OpenAPI' }));

    expect(screen.getByTestId('openapi-error').textContent).toContain(
      'Swagger 2.0 is not supported',
    );
    expect(screen.queryByTestId('openapi-title')).toBeNull();
  });

  it('loads an OpenAPI file and switches operations', async () => {
    const user = userEvent.setup();
    render(<AutomationPanel {...props} />);
    await user.click(screen.getByRole('tab', { name: 'Downstream Mapping' }));
    await user.selectOptions(screen.getByLabelText('Downstream source'), 'openapi');

    const file = new File([JSON.stringify(openapiFixture)], 'openapi.json', {
      type: 'application/json',
    });
    if (typeof file.text !== 'function') {
      Object.defineProperty(file, 'text', {
        value: async () => JSON.stringify(openapiFixture),
      });
    }
    await user.upload(screen.getByLabelText('OpenAPI JSON file'), file);

    await waitFor(() => expect(screen.getByTestId('openapi-title')).toBeTruthy());
    await user.selectOptions(
      screen.getByLabelText('OpenAPI operation'),
      'POST /trade/preview',
    );

    expect(screen.getByTestId('openapi-fields').textContent).toContain('amount');
    expect(screen.getByTestId('openapi-fields').textContent).not.toContain('application_type');
    expect(screen.getByTestId('openapi-payload').getAttribute('data-state')).toBe('not_ready');
  });
});