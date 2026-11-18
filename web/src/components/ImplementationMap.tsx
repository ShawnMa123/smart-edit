export type ImplementationStatus = 'Available' | 'Partial' | 'Unavailable';

export interface ImplementationRow {
  module: string;
  status: ImplementationStatus;
  limitation: string;
}

export const IMPLEMENTATION_MAP: ImplementationRow[] = [
  { module: 'Document', status: 'Available', limitation: 'Rich editor, page view and autosave.' },
  {
    module: 'Versions',
    status: 'Available',
    limitation: 'Browser-local capture and restore; comparison is local.',
  },
  {
    module: 'Version compare',
    status: 'Available',
    limitation: 'Read-only text diff; no AI summary.',
  },
  {
    module: 'Activity',
    status: 'Available',
    limitation: 'Browser-local log; not a server audit trail.',
  },
  {
    module: 'Notifications',
    status: 'Available',
    limitation: 'Derived from real local activity only.',
  },
  {
    module: 'Knowledge Q&A',
    status: 'Available',
    limitation: 'Published corpus plus the configured model provider.',
  },
  { module: 'Rule audit', status: 'Available', limitation: 'Fixed-snapshot audit with visible coverage.' },
  {
    module: 'Automation',
    status: 'Partial',
    limitation: 'Fixture-backed templates and mapping; no real downstream send.',
  },
  {
    module: 'People / Identity',
    status: 'Unavailable',
    limitation: 'No authentication or organisation service is configured.',
  },
  {
    module: 'Approval',
    status: 'Unavailable',
    limitation: 'No fixed-snapshot approval workflow or host command.',
  },
  {
    module: 'Comments',
    status: 'Unavailable',
    limitation: 'No comment service with anchored threads.',
  },
  { module: 'Export', status: 'Unavailable', limitation: 'No export adapter in this build.' },
  { module: 'Voice', status: 'Unavailable', limitation: 'Not implemented in this build.' },
];

const TONE: Record<ImplementationStatus, string> = {
  Available: 'tag tag--ok',
  Partial: 'tag tag--warn',
  Unavailable: 'tag tag--muted',
};

/** Read-only map of the reference modules and this build's real boundaries. */
export function ImplementationMap() {
  return (
    <div>
      <p className="notice tiny">
        Read-only implementation map. It names the boundary of this build; it does not describe a
        hidden API or a capability that is not wired.
      </p>
      <table className="implementation-map">
        <thead>
          <tr>
            <th>Module</th>
            <th>Status</th>
            <th>Limitation</th>
          </tr>
        </thead>
        <tbody>
          {IMPLEMENTATION_MAP.map((row) => (
            <tr key={row.module}>
              <td>{row.module}</td>
              <td>
                <span className={TONE[row.status]}>{row.status}</span>
              </td>
              <td>{row.limitation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}