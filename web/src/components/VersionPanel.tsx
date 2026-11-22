import { useEffect, useState } from 'react';

import { shortDigest } from '../snapshot';
import type { VersionEntry } from '../versionStore';
import { EmptyState } from './EmptyState';

export interface VersionFacts {
  documentId?: string;
  draftRevision?: number | null;
}

export interface VersionPanelProps {
  versions: VersionEntry[];
  currentVersionId: string | null;
  onCapture: () => void;
  onRestore: (id: string) => void;
  onClear: () => void;
  /** Called with exactly two selected version ids. */
  onCompare?: (ids: [string, string]) => void;
  /** Real document metadata only; omitted fields are not rendered (design D6). */
  facts?: VersionFacts;
  /** False when the editor is empty: capturing an empty version is not useful. */
  canCapture?: boolean;
}

/**
 * Left pane: browser-local, append-only version history (task 6.1).
 *
 * The list is a timeline and the current entry carries a word as well as a colour. The info block
 * below it lists only metadata the client actually holds — never a sample organisation or workspace.
 */
export function VersionPanel({
  versions,
  currentVersionId,
  onCapture,
  onRestore,
  onClear,
  onCompare,
  facts,
  canCapture = true,
}: VersionPanelProps) {
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);

  useEffect(() => {
    setSelectedForCompare((previous) =>
      previous.filter((id) => versions.some((version) => version.id === id)),
    );
  }, [versions]);

  const toggleCompare = (id: string) => {
    setSelectedForCompare((previous) => {
      if (previous.includes(id)) return previous.filter((selected) => selected !== id);
      if (previous.length >= 2) return previous;
      return [...previous, id];
    });
  };

  const canCompare = selectedForCompare.length === 2 && Boolean(onCompare);

  return (
    <aside className="pane pane--versions" aria-label="Version history">
      <div className="row">
        <h2>Version history</h2>
        <span className="tag tag--muted">{versions.length}</span>
      </div>

      {versions.length === 0 ? (
        <EmptyState
          icon="◌"
          title="No versions yet"
          hint="Capture the current text to start the history."
          action={
            <button
              type="button"
              className="primary"
              onClick={onCapture}
              disabled={!canCapture}
              title={canCapture ? 'Capture the current text' : 'Add text to the editor first'}
            >
              Capture version
            </button>
          }
        />
      ) : (
        <ol className="versions">
          {versions.map((version) => {
            const current = version.id === currentVersionId;
            const selected = selectedForCompare.includes(version.id);
            const selectionFull = selectedForCompare.length >= 2 && !selected;
            return (
              <li className="version" data-current={current} key={version.id}>
                <div className="version-head">
                  <label className="version-select">
                    <input
                      type="checkbox"
                      aria-label={`Select ${version.label} for comparison`}
                      checked={selected}
                      disabled={selectionFull}
                      onChange={() => toggleCompare(version.id)}
                    />
                  </label>
                  <strong>{version.label}</strong>
                  <span className="muted tiny">{version.chars} chars</span>
                </div>
                {current ? <span className="tag tag--ok">current</span> : null}
                <div className="digest" title={version.digest}>
                  {shortDigest(version.digest)}
                </div>
                <div className="muted tiny">{new Date(version.createdAt).toLocaleString()}</div>
                <div className="version-actions">
                  <button type="button" onClick={() => onRestore(version.id)}>
                    Restore into editor
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {versions.length > 0 ? (
        <div className="version-actions">
          <button
            type="button"
            className="primary"
            onClick={onCapture}
            disabled={!canCapture}
            title={canCapture ? 'Capture the current text' : 'Add text to the editor first'}
          >
            Capture version
          </button>
          <button
            type="button"
            disabled={!canCompare}
            title={canCompare ? 'Compare the two selected versions' : 'Select two versions to compare'}
            onClick={() => {
              if (canCompare && onCompare) {
                onCompare([selectedForCompare[0], selectedForCompare[1]]);
              }
            }}
          >
            Compare versions
          </button>
        </div>
      ) : null}
      {versions.length > 0 ? (
        <p className="tiny muted">
          {selectedForCompare.length === 2
            ? 'Two versions selected.'
            : 'Select two versions to compare.'}
        </p>
      ) : null}
      {versions.length > 0 ? (
        <button type="button" className="quiet tiny" onClick={onClear}>
          Clear version history
        </button>
      ) : null}

      <div className="notice tiny">
        History is stored in <strong>this browser only</strong> — it is not signed and not shared.
        Restoring only loads the text into the editor; it never rewrites a captured version.
      </div>

      <div className="document-info">
        <h3>Document info</h3>
        <dl>
          {facts?.documentId ? (
            <div>
              <dt>Document</dt>
              <dd>{facts.documentId}</dd>
            </div>
          ) : null}
          {facts ? (
            <div>
              <dt>Draft</dt>
              <dd>
                {facts.draftRevision === null ? 'no server draft' : `revision ${facts.draftRevision}`}
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Versions</dt>
            <dd>{versions.length}</dd>
          </div>
          <div>
            <dt>History</dt>
            <dd>browser-local</dd>
          </div>
        </dl>
      </div>
    </aside>
  );
}