import { shortDigest } from '../snapshot';
import type { VersionEntry } from '../versionStore';

export interface VersionPanelProps {
  versions: VersionEntry[];
  currentVersionId: string | null;
  onCapture: () => void;
  onRestore: (id: string) => void;
  onClear: () => void;
}

/** Left pane: browser-local, append-only version history (task 6.1). */
export function VersionPanel({
  versions,
  currentVersionId,
  onCapture,
  onRestore,
  onClear,
}: VersionPanelProps) {
  return (
    <aside className="pane" aria-label="Version history">
      <div className="row">
        <h2>Version history</h2>
        <span className="muted tiny">{versions.length}</span>
      </div>

      {versions.length === 0 ? (
        <p className="muted tiny">No versions yet. Capture the current text to start the history.</p>
      ) : (
        <ul className="versions">
          {versions.map((version) => (
            <li className="version" data-current={version.id === currentVersionId} key={version.id}>
              <div className="row">
                <strong>{version.label}</strong>
                <span className="muted tiny">{version.chars} chars</span>
              </div>
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
          ))}
        </ul>
      )}

      <div className="version-actions">
        <button type="button" className="primary" onClick={onCapture}>
          Capture version
        </button>
        <button
          type="button"
          disabled
          aria-disabled="true"
          title="Structural version comparison (VER-04) is not implemented in this build"
        >
          Compare versions — not implemented
        </button>
      </div>
      <button type="button" className="muted tiny" onClick={onClear}>
        Clear version history
      </button>

      <div className="notice tiny">
        History is stored in <strong>this browser only</strong> — it is not signed and not shared.
        Restoring only loads the text into the editor; it never rewrites a captured version.
      </div>
    </aside>
  );
}