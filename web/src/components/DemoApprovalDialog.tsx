import { demoUser, type DemoApproval, type DemoUserId } from '../demo/demoData';
import {
  activeStep,
  canConfirmHandoff,
  canDecideApproval,
  canStartApproval,
  type DemoDecision,
} from '../demo/demoApproval';

export interface DemoApprovalDialogProps {
  approval: DemoApproval;
  currentUserId: DemoUserId;
  onStart: () => void;
  onDecide: (decision: DemoDecision) => void;
  onHandoff: () => void;
}

export function DemoApprovalDialog({
  approval,
  currentUserId,
  onStart,
  onDecide,
  onHandoff,
}: DemoApprovalDialogProps) {
  const step = activeStep(approval);
  const canStart = canStartApproval(approval, currentUserId);
  const canDecide = canDecideApproval(approval, currentUserId);
  const canHandoff = canConfirmHandoff(approval);

  return (
    <div>
      <div className="row">
        <span className={`tag ${approval.status === 'APPROVED' || approval.status === 'HANDED_OFF' ? 'tag--ok' : 'tag--warn'}`}>
          {approval.status}
        </span>
        <span className="tag tag--muted">Simulated</span>
        <span className="tiny muted">Version {approval.version}</span>
      </div>
      <p className="notice notice--warn tiny">
        <strong>Sample approval.</strong> This workflow is local demo data; it does not submit a
        shared version, call a backend or represent a real approval.
      </p>
      <p className="tiny">
        Requester: <strong>{demoUser(approval.requesterId).name}</strong>
      </p>

      <ol className="demo-approval-steps">
        {approval.steps.map((item) => (
          <li key={item.role} className="demo-approval-step">
            <div>
              <strong>{item.role === 'ops' ? 'Bank operations' : 'Compliance'}</strong>
              <p className="tiny muted">{demoUser(item.assigneeId).name}</p>
            </div>
            <span className={`tag ${item.decision === 'approved' ? 'tag--ok' : item.decision === 'rejected' ? 'tag--bad' : 'tag--muted'}`}>
              {item.decision ?? (step === item ? 'Active' : 'Waiting')}
            </span>
            {item.at ? <span className="tiny muted">{new Date(item.at).toLocaleString()}</span> : null}
          </li>
        ))}
      </ol>

      {approval.receipt ? (
        <p className="notice tiny">
          <strong>{approval.receipt}</strong>
        </p>
      ) : null}

      <div className="dialog-actions">
        <button type="button" disabled={!canStart} onClick={onStart}>
          Start approval
        </button>
        <button type="button" disabled={!canDecide} onClick={() => onDecide('approved')}>
          Approve
        </button>
        <button type="button" disabled={!canDecide} onClick={() => onDecide('rejected')}>
          Reject
        </button>
        <button type="button" className="primary" disabled={!canHandoff} onClick={onHandoff}>
          Confirm sample handoff
        </button>
      </div>
      {approval.status === 'IN_REVIEW' && !canDecide ? (
        <p className="tiny muted">
          Only the active step assignee can decide. The requester cannot approve their own request.
        </p>
      ) : null}
    </div>
  );
}