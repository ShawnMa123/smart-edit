export type UnavailableModule = 'people' | 'identity' | 'approval' | 'comments';

interface Detail {
  summary: string;
  missing: string;
  boundary: string;
}

const DETAILS: Record<UnavailableModule, Detail> = {
  people: {
    summary: 'Organisation membership is not available in this build.',
    missing: 'an authentication service, organisation directory, membership model and invitation flow',
    boundary:
      'No member rows, organisation names, roles or invitation controls are shown because this build holds no such data.',
  },
  identity: {
    summary: 'Authentication is not configured in this build.',
    missing: 'an approved identity provider and a bound session principal',
    boundary:
      'The workspace runs as a neutral local demo session; no name, email, avatar, role or organisation is presented as a current identity.',
  },
  approval: {
    summary: 'The approval workflow is not available in this build.',
    missing: 'a fixed-snapshot approval workflow, independent reviewer checks and a host Workflow Command',
    boundary:
      'No approvers, approval steps, decisions or handoff receipts are shown, and no document is submitted.',
  },
  comments: {
    summary: 'Comments are not available in this build.',
    missing: 'a comment service with anchored threads and resolution state',
    boundary: 'No sample comments, authors or anchors are shown.',
  },
};

/** Explicit, side-effect-free placeholder for a capability this build does not serve. */
export function UnavailableModuleDialog({ module }: { module: UnavailableModule }) {
  const detail = DETAILS[module];
  return (
    <div>
      <p className="notice notice--warn">
        <strong>{detail.summary}</strong>
      </p>
      <p className="tiny">
        This surface would require {detail.missing}. It is intentionally a placeholder, not a
        simulated capability.
      </p>
      <p className="tiny muted">{detail.boundary}</p>
    </div>
  );
}