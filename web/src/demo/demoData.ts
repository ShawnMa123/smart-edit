export type DemoUserId = 'applicant' | 'ops' | 'compliance' | 'lawyer';
export type GuestStatus = 'invited' | 'active' | 'revoked';
export type ApprovalStatus = 'DRAFT' | 'IN_REVIEW' | 'APPROVED' | 'HANDED_OFF';

export interface DemoCapabilities {
  startApproval: boolean;
  approve: boolean;
  comment: boolean;
  manageGuest: boolean;
}

export interface DemoUser {
  id: DemoUserId;
  name: string;
  initials: string;
  org: string;
  role: string;
  capabilities: DemoCapabilities;
}

export interface DemoOrg {
  id: string;
  name: string;
  members: DemoUserId[];
}

export interface DemoComment {
  id: string;
  authorId: DemoUserId;
  text: string;
  quote: string | null;
  version: number;
  createdAt: string;
  resolved: boolean;
}

export interface DemoApprovalStep {
  role: 'ops' | 'compliance';
  assigneeId: DemoUserId;
  decision: 'approved' | 'rejected' | null;
  at: string | null;
}

export interface DemoApproval {
  status: ApprovalStatus;
  version: number;
  requesterId: DemoUserId;
  steps: DemoApprovalStep[];
  receipt: string | null;
}

export interface DemoActivity {
  id: string;
  actorId: DemoUserId;
  action: string;
  detail: string;
  at: string;
  read: boolean;
  notifiable: boolean;
}

export interface DemoState {
  schemaVersion: 1;
  currentUserId: DemoUserId;
  guestStatus: GuestStatus;
  comments: DemoComment[];
  approval: DemoApproval;
  activity: DemoActivity[];
}

export const DEMO_USERS: DemoUser[] = [
  {
    id: 'applicant',
    name: 'Chen Rui',
    initials: 'CR',
    org: 'Alpha Tech Ltd.',
    role: 'Applicant',
    capabilities: { startApproval: true, approve: false, comment: true, manageGuest: false },
  },
  {
    id: 'ops',
    name: 'Emma Wong',
    initials: 'EW',
    org: 'HSBC Trade Operations',
    role: 'Bank operations / first approver',
    capabilities: { startApproval: false, approve: true, comment: true, manageGuest: true },
  },
  {
    id: 'compliance',
    name: 'Daniel Lee',
    initials: 'DL',
    org: 'HSBC Compliance',
    role: 'Compliance / second approver',
    capabilities: { startApproval: false, approve: true, comment: true, manageGuest: true },
  },
  {
    id: 'lawyer',
    name: 'Lin Yan',
    initials: 'LY',
    org: 'Harbour Legal Partners',
    role: 'External counsel / guest',
    capabilities: { startApproval: false, approve: false, comment: true, manageGuest: false },
  },
];

export const DEMO_ORGS: DemoOrg[] = [
  { id: 'alpha', name: 'Alpha Tech Ltd.', members: ['applicant'] },
  { id: 'hsbc-ops', name: 'HSBC Trade Operations', members: ['ops'] },
  { id: 'hsbc-compliance', name: 'HSBC Compliance', members: ['compliance'] },
  { id: 'harbour', name: 'Harbour Legal Partners', members: ['lawyer'] },
];

export function demoUser(id: DemoUserId): DemoUser {
  return DEMO_USERS.find((user) => user.id === id) ?? DEMO_USERS[0];
}

export function seedDemoState(): DemoState {
  return {
    schemaVersion: 1,
    currentUserId: 'applicant',
    guestStatus: 'active',
    comments: [
      {
        id: 'demo-comment-1',
        authorId: 'ops',
        text: 'Please confirm the demand period against the underlying contract before approval.',
        quote: 'Payment will be made within a reasonable time after examination.',
        version: 3,
        createdAt: '2026-11-02T14:45:00.000Z',
        resolved: false,
      },
      {
        id: 'demo-comment-2',
        authorId: 'lawyer',
        text: 'Guest review: the governing law sentence remains subject to confirmation.',
        quote: 'Applicable rules, governing law and execution details remain subject to authorized human confirmation.',
        version: 3,
        createdAt: '2026-11-03T09:20:00.000Z',
        resolved: true,
      },
    ],
    approval: {
      status: 'DRAFT',
      version: 3,
      requesterId: 'applicant',
      steps: [
        { role: 'ops', assigneeId: 'ops', decision: null, at: null },
        { role: 'compliance', assigneeId: 'compliance', decision: null, at: null },
      ],
      receipt: null,
    },
    activity: [
      {
        id: 'demo-activity-1',
        actorId: 'applicant',
        action: 'Version captured',
        detail: 'Version 3 captured for review',
        at: '2026-11-03T10:10:00.000Z',
        read: true,
        notifiable: false,
      },
      {
        id: 'demo-activity-2',
        actorId: 'ops',
        action: 'Comment added',
        detail: 'Comment added to the payment clause',
        at: '2026-11-02T14:45:00.000Z',
        read: false,
        notifiable: true,
      },
      {
        id: 'demo-activity-3',
        actorId: 'applicant',
        action: 'Approval requested',
        detail: 'Sample approval requested for version 3',
        at: '2026-11-03T10:15:00.000Z',
        read: false,
        notifiable: true,
      },
      {
        id: 'demo-activity-4',
        actorId: 'compliance',
        action: 'Audit completed',
        detail: 'Sample audit completed with no findings in the checks that ran',
        at: '2026-11-03T10:18:00.000Z',
        read: true,
        notifiable: true,
      },
    ],
  };
}