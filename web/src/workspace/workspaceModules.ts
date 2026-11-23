export type WorkspaceModule =
  | 'activity'
  | 'inbox'
  | 'people'
  | 'identity'
  | 'developer'
  | 'approval'
  | 'comments';

export type WorkspaceNavTarget = 'document' | 'versions' | WorkspaceModule;

export interface RailEntry {
  id: WorkspaceNavTarget;
  label: string;
  icon: string;
}

/** The rail order follows the reference prototype: document, versions, approval, comments, people, developer. */
export const RAIL_ENTRIES: RailEntry[] = [
  { id: 'document', label: 'Document', icon: '▤' },
  { id: 'versions', label: 'Versions', icon: '◷' },
  { id: 'approval', label: 'Approval', icon: '✓' },
  { id: 'comments', label: 'Comments', icon: '≡' },
  { id: 'people', label: 'People', icon: '♙' },
  { id: 'developer', label: 'Developer', icon: '⌘' },
];

export const TOPBAR_ENTRIES: RailEntry[] = [
  { id: 'activity', label: 'Activity', icon: '◷' },
  { id: 'approval', label: 'Approval', icon: '✓' },
  { id: 'people', label: 'People', icon: '♙' },
  { id: 'inbox', label: 'Inbox', icon: '☷' },
  { id: 'developer', label: 'Developer', icon: '⌘' },
];

export const MODULE_LABELS: Record<WorkspaceModule, string> = {
  activity: 'Activity',
  inbox: 'Inbox',
  people: 'People',
  identity: 'Identity',
  developer: 'Developer',
  approval: 'Approval',
  comments: 'Comments',
};

export const MODULE_TITLES: Record<WorkspaceModule, string> = {
  activity: 'Activity',
  inbox: 'Inbox',
  people: 'Organisation & members — not available in this build',
  identity: 'Authentication is not configured',
  developer: 'Implementation map',
  approval: 'Approval workflow — not available in this build',
  comments: 'Comments — not available in this build',
};