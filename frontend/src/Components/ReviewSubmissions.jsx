// src/components/ReviewSubmissions.jsx — PM: developer work submitted for review
import React, { useState, useEffect, useCallback } from 'react';
import { taskService, getApiErrorMessage } from '../services/api.js';

async function downloadFile(taskId, fileIndex, suggestedName) {
  const blob = await taskService.downloadSubmissionFile(taskId, fileIndex);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = suggestedName || `file_${fileIndex}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const ReviewSubmissions = ({ onMarkComplete, isLoading: parentLoading }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionId, setActionId] = useState(null);
  const [changeRequestFor, setChangeRequestFor] = useState(null);
  const [changeComment, setChangeComment] = useState('');

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError('');
      const data = await taskService.getReviewSubmissions();
      setRows(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(getApiErrorMessage(e, 'Could not load submissions'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const markComplete = async (row) => {
    const taskId = row?.id;
    if (!taskId) return;
    if (!window.confirm('Mark this task complete after review?')) return;
    try {
      setActionId(taskId);
      await taskService.updateTaskStatus(taskId, 'completed');
      await load();
      if (onMarkComplete) onMarkComplete({ taskId, projectId: row?.project_id });
    } catch (e) {
      alert(getApiErrorMessage(e, 'Could not update task'));
    } finally {
      setActionId(null);
    }
  };

  const requestChanges = async (taskId) => {
    const msg = String(changeComment || '').trim();
    if (msg.length < 3) {
      alert('Please enter clear feedback for the developer.');
      return;
    }
    try {
      setActionId(taskId);
      await taskService.requestTaskChanges(taskId, msg);
      setChangeRequestFor(null);
      setChangeComment('');
      await load();
      const hit = rows.find((r) => r.id === taskId);
      if (onMarkComplete) onMarkComplete({ taskId, projectId: hit?.project_id });
    } catch (e) {
      alert(getApiErrorMessage(e, 'Could not request changes'));
    } finally {
      setActionId(null);
    }
  };

  const busy = loading || parentLoading;

  return (
    <div className="bg-white dark:bg-gray-800/80 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 mb-8">
      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Submissions for review</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Work submitted by developers on your projects (text, comments, and files).
          </p>
        </div>
        <button
          type="button"
          onClick={() => load()}
          disabled={busy}
          className="text-sm px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {loading && rows.length === 0 ? (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading…</div>
      ) : rows.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm py-4">No tasks waiting for review.</p>
      ) : (
        <ul className="space-y-4">
          {rows.map((row) => {
            const sub = row.submission || {};
            const files = sub.files || [];
            return (
              <li
                key={row.id}
                className="min-w-0 border border-gray-200 dark:border-gray-600 rounded-xl p-4 bg-gray-50 dark:bg-gray-900/50"
              >
                <div className="flex flex-wrap justify-between gap-2 mb-2">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">{row.title}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-900 dark:bg-yellow-900/40 dark:text-yellow-200">
                    Submitted
                  </span>
                </div>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                  <span className="font-medium text-gray-700 dark:text-gray-300">Project:</span> {row.project_title || row.project_id}
                  {' · '}
                  <span className="font-medium text-gray-700 dark:text-gray-300">Developer:</span> {row.developer_name || row.assigned_to}
                </p>
                {sub.text_content && (
                  <div className="mb-2 min-w-0">
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-500 uppercase">Pasted text</p>
                    <pre className="mt-1 text-xs whitespace-pre-wrap max-h-40 max-w-full overflow-auto bg-white dark:bg-gray-800 p-2 rounded border border-gray-200 dark:border-gray-600 text-gray-800 dark:text-gray-200">
                      {sub.text_content}
                    </pre>
                  </div>
                )}
                {sub.comment && (
                  <div className="mb-2 min-w-0">
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-500 uppercase">Comment</p>
                    <pre className="mt-1 text-xs whitespace-pre-wrap max-h-40 max-w-full overflow-auto bg-white dark:bg-gray-800 p-2 rounded border border-gray-200 dark:border-gray-600 text-gray-800 dark:text-gray-200">
                      {sub.comment}
                    </pre>
                  </div>
                )}
                {files.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {files.map((f, idx) => (
                      <button
                        key={`${row.id}-${idx}`}
                        type="button"
                        disabled={busy || actionId}
                        onClick={() => downloadFile(row.id, idx, f.original_name)}
                        className="text-xs px-3 py-1.5 rounded-lg bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 hover:opacity-90 disabled:opacity-50"
                      >
                        Download: {f.original_name || `file_${idx}`}
                      </button>
                    ))}
                  </div>
                )}
                <div className="mt-3 flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    disabled={busy || !!actionId}
                    onClick={() => {
                      setChangeRequestFor(row.id);
                      setChangeComment('');
                    }}
                    className="text-sm px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium disabled:opacity-50"
                  >
                    Request changes
                  </button>
                  <button
                    type="button"
                    disabled={busy || actionId === row.id}
                    onClick={() => markComplete(row)}
                    className="text-sm px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white font-medium disabled:opacity-50"
                  >
                    {actionId === row.id ? '…' : 'Mark complete (reviewed)'}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {changeRequestFor && (
        <div className="modal-backdrop fixed inset-0 z-50 bg-black/60 p-4 flex items-center justify-center" role="dialog" aria-modal="true">
          <div className="modal-panel bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-xl w-full max-w-lg p-5">
            <h4 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-2">Request changes from developer</h4>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
              Add clear feedback. Task will move back to <span className="font-medium">In Progress</span> so developer can fix and resubmit.
            </p>
            <textarea
              value={changeComment}
              onChange={(e) => setChangeComment(e.target.value)}
              rows={5}
              placeholder="What should be changed? Mention exact fixes..."
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={() => {
                  setChangeRequestFor(null);
                  setChangeComment('');
                }}
                className="text-sm px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy || actionId === changeRequestFor}
                onClick={() => requestChanges(changeRequestFor)}
                className="text-sm px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium disabled:opacity-50"
              >
                {actionId === changeRequestFor ? 'Sending…' : 'Send change request'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReviewSubmissions;
