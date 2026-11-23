import { RAIL_ENTRIES, type WorkspaceNavTarget } from '../workspace/workspaceModules';

export interface WorkspaceRailProps {
  /** The active content pane or open module; `null` means no rail entry is active. */
  active: WorkspaceNavTarget | null;
  onOpen: (target: WorkspaceNavTarget) => void;
}

/** Desktop navigation rail; the narrow layout reaches the same entries from the top bar/menu. */
export function WorkspaceRail({ active, onOpen }: WorkspaceRailProps) {
  return (
    <nav className="rail" aria-label="Workspace navigation">
      {RAIL_ENTRIES.map((entry) => {
        const selected = entry.id === active;
        return (
          <button
            key={entry.id}
            type="button"
            className={selected ? 'active' : undefined}
            aria-current={selected ? 'page' : undefined}
            aria-label={entry.label}
            title={entry.label}
            onClick={() => onOpen(entry.id)}
          >
            <span aria-hidden="true">{entry.icon}</span>
            <span className="rail-label">{entry.label}</span>
          </button>
        );
      })}
    </nav>
  );
}