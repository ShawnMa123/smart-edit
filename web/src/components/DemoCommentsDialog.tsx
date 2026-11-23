import { useState } from 'react';

import { demoUser, type DemoState } from '../demo/demoData';

export interface DemoCommentsDialogProps {
  state: DemoState;
  quote: string | null;
  onAdd: (text: string, quote: string | null) => void;
  onResolve: (id: string) => void;
}

export function DemoCommentsDialog({ state, quote, onAdd, onResolve }: DemoCommentsDialogProps) {
  const [text, setText] = useState('');
  const current = demoUser(state.currentUserId);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    onAdd(value, quote);
    setText('');
  };

  return (
    <div>
      <p className="notice notice--warn tiny">
        <strong>Sample data.</strong> Comments are stored in the browser-local demo state, not a
        comment service. The author is the current demo identity.
      </p>
      <p className="tiny muted">
        Current demo author: <strong>{current.name}</strong> · {current.org}
      </p>
      {quote ? (
        <blockquote className="demo-comment-quote">Selected passage: “{quote}”</blockquote>
      ) : (
        <p className="tiny muted">No selection — the comment will not carry a passage quote.</p>
      )}
      <label className="field-label" htmlFor="demo-comment-text">
        New sample comment
      </label>
      <textarea
        id="demo-comment-text"
        value={text}
        maxLength={1000}
        placeholder="Record a sample review note"
        onChange={(event) => setText(event.target.value)}
      />
      <div className="dialog-actions">
        <button type="button" className="primary" disabled={!text.trim()} onClick={submit}>
          Add sample comment
        </button>
      </div>

      <ul className="demo-comment-list">
        {state.comments.map((comment) => {
          const author = demoUser(comment.authorId);
          return (
            <li className="demo-comment" key={comment.id}>
              <div className="row">
                <strong>{author.name}</strong>
                <span className="tag tag--muted">{author.role}</span>
                <span className={`tag ${comment.resolved ? 'tag--ok' : 'tag--warn'}`}>
                  {comment.resolved ? 'Resolved' : 'Open'}
                </span>
              </div>
              {comment.quote ? (
                <blockquote className="demo-comment-quote">{comment.quote}</blockquote>
              ) : null}
              <p>{comment.text}</p>
              <p className="tiny muted">
                v{comment.version} · {new Date(comment.createdAt).toLocaleString()}
              </p>
              {!comment.resolved ? (
                <button type="button" className="small" onClick={() => onResolve(comment.id)}>
                  Resolve
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}