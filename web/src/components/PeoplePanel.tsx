/** People: department tree, members, inherited roles and invite links (task 6.3). */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { ApiError } from '../api/errors';
import * as api from '../api/identity';
import type { Department, Invite, Member } from '../api/identityTypes';
import { useToast } from './ToastProvider';

const ROLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'applicant', label: 'Applicant' },
  { value: 'bank_ops', label: 'Bank Operations (First Approver)' },
  { value: 'compliance', label: 'Compliance (Second Approver)' },
  { value: 'member', label: 'Member' },
  { value: 'auditor', label: 'Auditor' },
  { value: 'dept_admin', label: 'Department admin' },
  { value: 'org_admin', label: 'Organisation admin' },
];

interface PeoplePanelProps {
  orgId: string;
  fetchImpl?: typeof fetch;
}

function orderedTree(departments: Department[]): Array<Department & { depth: number }> {
  const byParent = new Map<string | null, Department[]>();
  for (const department of departments) {
    const list = byParent.get(department.parent_id) ?? [];
    list.push(department);
    byParent.set(department.parent_id, list);
  }
  const out: Array<Department & { depth: number }> = [];
  const walk = (parent: string | null, depth: number, seen: Set<string>) => {
    for (const department of byParent.get(parent) ?? []) {
      if (seen.has(department.department_id)) continue;
      seen.add(department.department_id);
      out.push({ ...department, depth });
      walk(department.department_id, depth + 1, seen);
    }
  };
  walk(null, 0, new Set());
  return out;
}

export function PeoplePanel({ orgId, fetchImpl }: PeoplePanelProps) {
  const toast = useToast();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [selected, setSelected] = useState<Member | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('member');
  const [departmentId, setDepartmentId] = useState('');
  const [departmentName, setDepartmentName] = useState('');
  const [parentId, setParentId] = useState('');

  const load = useCallback(async () => {
    setError(null);
    setForbidden(false);
    try {
      const [nextDepartments, nextMembers, nextInvites] = await Promise.all([
        api.listDepartments(orgId, { fetchImpl }),
        api.listMembers(orgId, { fetchImpl }),
        api.listInvites(orgId, { fetchImpl }).catch(() => []),
      ]);
      setDepartments(nextDepartments);
      setMembers(nextMembers);
      setInvites(nextInvites);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 403) {
        setForbidden(true);
      } else {
        setError(caught instanceof Error ? caught.message : 'could not load organisation');
      }
    }
  }, [fetchImpl, orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const tree = useMemo(() => orderedTree(departments), [departments]);
  const departmentNames = useMemo(
    () => new Map(departments.map((item) => [item.department_id, item.name])),
    [departments],
  );

  const createDepartment = async () => {
    if (!departmentName.trim()) return;
    try {
      await api.createDepartment(orgId, departmentName.trim(), parentId || null, { fetchImpl });
      setDepartmentName('');
      setParentId('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'could not create department');
    }
  };

  const sendInvite = async () => {
    if (!email.trim()) return;
    try {
      const created = await api.createInvite(
        orgId,
        { email: email.trim(), role_key: role, department_id: departmentId || null },
        { fetchImpl },
      );
      setInviteLink(created.accept_path ?? null);
      setEmail('');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'could not create invite');
    }
  };

  const copyInvite = async () => {
    if (!inviteLink) return;
    const absolute = new URL(inviteLink, window.location.origin).toString();
    const clipboard = navigator.clipboard;
    if (!clipboard?.writeText) {
      toast.warning('Clipboard is unavailable — copy the link manually.');
      return;
    }
    try {
      await clipboard.writeText(absolute);
      toast.success('Invite link copied');
    } catch {
      // Clipboard access is optional; the link stays visible for manual copying.
      toast.warning('Could not copy the invite link — copy it manually.');
    }
  };

  if (forbidden) {
    return (
      <div className="empty-state" role="status">
        <strong>No access to members</strong>
        <p className="tiny">Your role does not include member management for this organisation.</p>
      </div>
    );
  }

  return (
    <div className="people-panel">
      {error ? <p className="notice notice--warn">{error}</p> : null}
      <div className="people-grid">
        <section aria-label="Departments">
          <h3>Departments</h3>
          {tree.length === 0 ? <p className="tiny">No departments yet.</p> : null}
          <ul className="department-tree">
            {tree.map((department) => (
              <li
                key={department.department_id}
                style={{ paddingLeft: `${department.depth * 16}px` }}
              >
                {department.name}
              </li>
            ))}
          </ul>
          <div className="stack">
            <input
              aria-label="New department name"
              placeholder="Department name"
              value={departmentName}
              onChange={(event) => setDepartmentName(event.target.value)}
            />
            <select
              aria-label="Parent department"
              value={parentId}
              onChange={(event) => setParentId(event.target.value)}
            >
              <option value="">Organisation root</option>
              {departments.map((department) => (
                <option key={department.department_id} value={department.department_id}>
                  {department.name}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => void createDepartment()}>
              Add department
            </button>
          </div>
        </section>

        <section aria-label="Members">
          <h3>Members</h3>
          <ul className="member-list">
            {members.map((member) => (
              <li key={member.user_id}>
                <button type="button" className="link" onClick={() => setSelected(member)}>
                  {member.display_name}
                </button>
                <span className="tiny"> {member.email}</span>
                <span className="chip">
                  {member.department_name ??
                    departmentNames.get(member.department_id ?? '') ??
                    'Organisation'}
                </span>
                {member.status !== 'active' ? <span className="chip">{member.status}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section aria-label="Invite a member">
        <h3>Invite</h3>
        <div className="inline-form">
          <input
            aria-label="Invite email"
            type="email"
            placeholder="colleague@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <select
            aria-label="Invite role"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {ROLE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Invite department"
            value={departmentId}
            onChange={(event) => setDepartmentId(event.target.value)}
          >
            <option value="">Organisation-level</option>
            {departments.map((department) => (
              <option key={department.department_id} value={department.department_id}>
                {department.name}
              </option>
            ))}
          </select>
          <button type="button" className="primary" onClick={() => void sendInvite()}>
            Create invite link
          </button>
        </div>
        <p className="tiny">
          Version 1 does not send email. Copy the one-time link and share it through your own channel.
        </p>
        {inviteLink ? (
          <div className="notice" role="status">
            <code>{new URL(inviteLink, window.location.origin).toString()}</code>
            <button type="button" onClick={() => void copyInvite()}>
              Copy link
            </button>
          </div>
        ) : null}
        {invites.length > 0 ? (
          <ul className="tiny">
            {invites.map((invite) => (
              <li key={invite.invite_id}>
                {invite.email} · {invite.role_key} ·{' '}
                {invite.accepted_at ? 'accepted' : invite.revoked_at ? 'revoked' : 'pending'}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {selected ? (
        <section aria-label={`Roles for ${selected.display_name}`} className="role-drawer">
          <header>
            <h3>{selected.display_name}</h3>
            <button type="button" onClick={() => setSelected(null)}>
              Close
            </button>
          </header>
          <ul>
            {selected.role_assignments.length === 0 ? (
              <li className="tiny">No roles assigned.</li>
            ) : null}
            {selected.role_assignments.map((assignment) => {
              const inherited =
                assignment.scope_type === 'department' &&
                assignment.scope_id !== selected.department_id;
              return (
                <li key={assignment.assignment_id}>
                  <strong>{assignment.role_name ?? assignment.role_key}</strong>{' '}
                  <span className="tiny">
                    {assignment.scope_type === 'org'
                      ? 'organisation-wide'
                      : departmentNames.get(assignment.scope_id) ?? assignment.scope_id}
                  </span>{' '}
                  {inherited ? <span className="chip">inherited · read-only</span> : null}
                </li>
              );
            })}
          </ul>
          <p className="tiny">
            Roles are additive: inherited permissions come from ancestor departments and cannot be
            denied here. Revoke a grant through the API/administration flow.
          </p>
        </section>
      ) : null}
    </div>
  );
}