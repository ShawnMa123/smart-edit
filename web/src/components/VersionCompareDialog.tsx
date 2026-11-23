import type { VersionEntry } from '../versionStore';
import { diffBlocks, hasTextualChanges } from '../workspace/versionDiff';
import { shortDigest } from '../snapshot';
import { WorkspaceDialog } from './WorkspaceDialog';

export interface VersionCompareDialogProps {
  before: VersionEntry;
  after: VersionEntry;
  onClose: () => void;
}

export function VersionCompareDialog({ before, after, onClose }: VersionCompareDialogProps) {
  const rows = diffBlocks(before.text, after.text);
  const changed = hasTextualChanges(rows);

  return (
    <WorkspaceDialog title="Version compare" onClose={onClose} wide>
      <div className="version-compare-head">
        <div>
          <strong>{before.label}</strong>
          <p className="tiny muted">
            {new Date(before.createdAt).toLocaleString()} · {shortDigest(before.digest)}
          </p>
        </div>
        <div>
          <strong>{after.label}</strong>
          <p className="tiny muted">
            {new Date(after.createdAt).toLocaleString()} · {shortDigest(after.digest)}
          </p>
        </div>
      </div>

      <p className="notice tiny">
        Read-only comparison of the projected text. No AI summary and no inferred content.
      </p>

      {changed ? (
        <div className="diff-grid" role="table" aria-label="Version differences">
          {rows.map((row, index) => (
            <div className={`diff-row diff-row--${row.kind}`} role="row" key={`${row.kind}-${index}`}>
              <div className="diff-cell" role="cell">
                {row.before ?? ''}
              </div>
              <div className="diff-cell" role="cell">
                {row.after ?? ''}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="notice tiny">No textual differences in the captured text.</p>
      )}
    </WorkspaceDialog>
  );
}