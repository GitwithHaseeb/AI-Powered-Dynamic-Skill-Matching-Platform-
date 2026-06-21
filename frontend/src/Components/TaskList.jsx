// src/components/TaskList.jsx
import React, { useState } from 'react';
import TaskDescriptionBody from './TaskDescriptionBody.jsx';

const DESCRIPTION_PREVIEW_CHARS = 320;

const TaskList = ({
  tasks,
  listVariant = 'active',
  onUpdateStatus,
  onSubmitForReview,
  isLoading,
  emptyTitle = 'No tasks assigned',
  emptySubtitle = "You don't have any tasks assigned at the moment.",
}) => {
  const [submitModalTask, setSubmitModalTask] = useState(null);
  const [pasteText, setPasteText] = useState('');
  const [comment, setComment] = useState('');
  const [files, setFiles] = useState([]);
  const [submitError, setSubmitError] = useState('');
  /** task.id -> whether full description is shown */
  const [descExpandedByTask, setDescExpandedByTask] = useState({});

  const formatTaskDate = (value) => {
    if (!value) return 'N/A';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return 'N/A';
    return d.toLocaleDateString();
  };

  const getTaskStartDate = (task) => formatTaskDate(task.start_date || task.created_at);
  const getTaskEndDate = (task) => formatTaskDate(task.end_date || task.updated_at);

  const getStatusConfig = (status) => {
    const s = String(status || '').toLowerCase();
    const completedEmphasis =
      listVariant === 'completed' && s === 'completed';
    const config = {
      assigned: { color: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200', label: 'Assigned' },
      in_progress: { color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200', label: 'In Progress' },
      submitted: { color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200', label: 'Submitted' },
      completed: {
        color: completedEmphasis
          ? 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-white shadow-md ring-2 ring-emerald-200/90 dark:ring-emerald-400/45 font-bold tracking-wide'
          : 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
        label: 'Completed',
      },
    };
    return config[s] || config.assigned;
  };

  const openSubmitModal = (task) => {
    setSubmitModalTask(task);
    setPasteText('');
    setComment('');
    setFiles([]);
    setSubmitError('');
  };

  const closeSubmitModal = () => {
    setSubmitModalTask(null);
    setSubmitError('');
  };

  React.useEffect(() => {
    if (!submitModalTask) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') closeSubmitModal();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [submitModalTask]);

  const handleSubmitForReview = async (e) => {
    e.preventDefault();
    if (!submitModalTask) return;
    const form = e.currentTarget;
    const textEl = form.querySelector('textarea[name="text_content"]');
    const commentEl = form.querySelector('textarea[name="comment"]');
    const fileEl = form.querySelector('input[name="files"]');

    // Prefer live DOM .value; fall back to React state (covers edge cases with controlled inputs).
    const fromDomText = String(textEl?.value ?? '').trim();
    const fromDomComment = String(commentEl?.value ?? '').trim();
    const textContent =
      fromDomText.length > 0 ? fromDomText : String(pasteText ?? '').trim();
    const commentVal =
      fromDomComment.length > 0 ? fromDomComment : String(comment ?? '').trim();

    let fileParts = [];
    if (fileEl?.files?.length) {
      fileParts = Array.from(fileEl.files).filter((f) => f.size > 0);
    } else if (files && files.length > 0) {
      fileParts = Array.from(files).filter((f) => f && f.size > 0);
    }

    // At least one of: pasted text, comment, or file (you can mix, e.g. text+comment only).
    const hasWork =
      textContent.length > 0 || commentVal.length > 0 || fileParts.length > 0;
    if (!hasWork) {
      setSubmitError(
        'Please add at least one: pasted text, or a comment, or a file (any mix is OK).'
      );
      return;
    }
    setSubmitError('');
    const result = await onSubmitForReview(submitModalTask.id, {
      textContent,
      comment: commentVal,
      files: fileParts,
    });
    if (result.success) {
      closeSubmitModal();
    } else {
      setSubmitError(result.error || 'Submission failed');
    }
  };

  const handleStatusUpdate = async (taskId, newStatus) => {
    const result = await onUpdateStatus(taskId, newStatus);
    if (!result.success) {
      alert(result.error || 'Failed to update task status');
    }
  };

  if (isLoading && tasks.length === 0) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-gray-100 dark:bg-gray-800 animate-pulse rounded-xl p-6 h-32" />
        ))}
      </div>
    );
  }

  if (tasks.length === 0) {
    const emptyAccent =
      listVariant === 'completed'
        ? 'text-emerald-600/90 dark:text-emerald-400'
        : 'text-blue-600/90 dark:text-blue-400';
    return (
      <div className="bg-white dark:bg-gray-800/80 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-10 sm:p-12 text-center">
        <div className={`${emptyAccent}`}>
          <svg className="mx-auto h-14 w-14 opacity-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h3 className="mt-5 text-lg font-semibold text-gray-900 dark:text-gray-100">{emptyTitle}</h3>
        {emptySubtitle ? (
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400 max-w-md mx-auto leading-relaxed">
            {emptySubtitle}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {submitModalTask && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
          role="dialog"
          aria-modal="true"
          onMouseDown={closeSubmitModal}
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-2xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto border border-gray-200 dark:border-gray-700"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <form
              key={String(submitModalTask.id)}
              onSubmit={handleSubmitForReview}
              className="p-6 space-y-4"
            >
              <h4 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Submit work for review</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Your project manager will receive this submission for <span className="font-medium text-gray-900 dark:text-gray-200">{submitModalTask.title}</span>.
              </p>
              {submitModalTask.description?.trim() ? (
                <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/60 px-3 py-2.5 text-sm text-gray-700 dark:text-gray-300 max-h-64 overflow-y-auto">
                  <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Task description</span>
                  <div className="mt-2">
                    <TaskDescriptionBody text={submitModalTask.description} />
                  </div>
                </div>
              ) : null}

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Paste text / code / notes</label>
                <textarea
                  name="text_content"
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  rows={5}
                  placeholder="Copy and paste excerpts, snippets, or descriptions of what you completed…"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
                  autoComplete="off"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Comment for manager</label>
                <textarea
                  name="comment"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={3}
                  placeholder="Summary, blockers, or instructions…"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
                  autoComplete="off"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Attach files (optional)</label>
                <input
                  type="file"
                  name="files"
                  multiple
                  onChange={(e) => setFiles(e.target.files)}
                  className="block w-full text-sm text-gray-600 dark:text-gray-400 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-800 dark:file:bg-blue-900/40 dark:file:text-blue-200"
                />
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
                  .cpp, .py, .js, .pdf, .doc/.docx, .zip, and other common code/docs (max size per file per server).
                </p>
              </div>

              {submitError && (
                <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg">{submitError}</div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeSubmitModal}
                  className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium disabled:opacity-50"
                >
                  {isLoading ? 'Submitting…' : 'Submit for review'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {tasks.map((task) => {
        const statusConfig = getStatusConfig(task.status);
        const sub = task.submission || {};
        // Developer Dashboard passes listVariant and only includes the signed-in assignee (no teammate rows).
        const canAct =
          listVariant === 'active' || listVariant === 'completed'
            ? true
            : task.is_assigned_to_me !== false;
        const isDoneCard =
          listVariant === 'completed' &&
          String(task.status || '').toLowerCase() === 'completed';
        const completedOnRaw = task.end_date || task.completed_at || task.updated_at;
        const completedOnLabel = formatTaskDate(completedOnRaw);

        return (
          <div
            key={task.id}
            className={`min-w-0 rounded-xl shadow-sm p-6 transition-shadow duration-200 hover:shadow-md ${
              isDoneCard
                ? 'bg-gradient-to-br from-emerald-50 via-white to-slate-50/80 dark:from-emerald-950/25 dark:via-gray-800/95 dark:to-gray-800/85 border border-emerald-200/70 dark:border-emerald-800/55 border-l-[5px] border-l-emerald-500 dark:border-l-emerald-400'
                : 'bg-white dark:bg-gray-800/80 border border-gray-200 dark:border-gray-700'
            }`}
          >
            {!canAct && (
              <div className="mb-4 text-sm text-amber-800 dark:text-amber-200/90 bg-amber-50 dark:bg-amber-900/25 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
                View only — this task is assigned to a teammate. You can follow progress on shared projects.
              </div>
            )}
            <div className="flex flex-col gap-3 sm:flex-row sm:justify-between sm:items-start mb-4">
              <div className="min-w-0 flex-1 space-y-3">
                <h4 className="text-lg font-semibold text-gray-900 dark:text-gray-100 leading-snug">{task.title}</h4>
                <div className="rounded-lg border border-slate-200/80 dark:border-slate-600/60 bg-slate-50/80 dark:bg-slate-900/40 px-3 py-2.5">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1">
                    Description
                  </p>
                  {(() => {
                    const raw = String(task.description || '').trim();
                    if (!raw) {
                      return (
                        <p className="text-sm text-slate-500 dark:text-slate-500 italic">—</p>
                      );
                    }
                    const long = raw.length > DESCRIPTION_PREVIEW_CHARS;
                    const expanded = !!descExpandedByTask[task.id];
                    if (long && !expanded) {
                      const preview = `${raw.slice(0, DESCRIPTION_PREVIEW_CHARS)}…`;
                      return (
                        <div className="space-y-2">
                          <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap break-words">
                            {preview}
                          </p>
                          <button
                            type="button"
                            onClick={() =>
                              setDescExpandedByTask((prev) => ({
                                ...prev,
                                [task.id]: true,
                              }))
                            }
                            className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                          >
                            Show full description
                          </button>
                        </div>
                      );
                    }
                    return (
                      <div className="space-y-2">
                        <TaskDescriptionBody text={raw} />
                        {long && expanded ? (
                          <button
                            type="button"
                            onClick={() =>
                              setDescExpandedByTask((prev) => ({
                                ...prev,
                                [task.id]: false,
                              }))
                            }
                            className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                          >
                            Show less
                          </button>
                        ) : null}
                      </div>
                    );
                  })()}
                </div>
                {isDoneCard && (
                  <div className="flex items-start gap-3 rounded-xl border border-emerald-200/90 dark:border-emerald-700/70 bg-emerald-50/90 dark:bg-emerald-950/45 px-4 py-3">
                    <span
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-600/15 dark:bg-emerald-400/20 text-emerald-700 dark:text-emerald-300"
                      aria-hidden
                    >
                      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                        />
                      </svg>
                    </span>
                    <div>
                      <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-800/90 dark:text-emerald-300/90">
                        Completed on
                      </p>
                      <p className="text-base font-semibold text-emerald-900 dark:text-emerald-100 tabular-nums">
                        {completedOnLabel}
                      </p>
                    </div>
                  </div>
                )}
              </div>
              <span
                className={`inline-flex shrink-0 items-center rounded-full font-medium ${
                  isDoneCard
                    ? 'uppercase tracking-wide px-3.5 py-1.5 text-xs sm:text-sm shadow-sm'
                    : 'px-3 py-1 text-xs'
                } ${statusConfig.color}`}
              >
                {statusConfig.label}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm text-gray-600 dark:text-gray-400 mb-4">
              <div>
                <span className="font-medium text-gray-700 dark:text-gray-300">Project:</span> {task.project_title || task.project}
              </div>
              <div>
                <span className="font-medium text-gray-700 dark:text-gray-300">Project Manager:</span>{' '}
                {task.project_manager_name || 'N/A'}
              </div>
              <div>
                <span className="font-medium text-gray-700 dark:text-gray-300">Start Date:</span> {getTaskStartDate(task)}
              </div>
              <div>
                <span className="font-medium text-gray-700 dark:text-gray-300">End Date:</span> {getTaskEndDate(task)}
              </div>
              {task.match_score && (
                <div>
                  <span className="font-medium text-gray-700 dark:text-gray-300">Match Score:</span> {task.match_score}%
                </div>
              )}
            </div>

            {task.status !== 'completed' && sub && (sub.text_content || sub.comment || (sub.files && sub.files.length)) && (
              <div className="mb-4 min-w-0 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 text-sm">
                <p className="font-medium text-amber-900 dark:text-amber-200 mb-2">
                  {canAct ? 'Your last submission' : 'Latest submission (assignee)'}
                </p>
                {sub.text_content && (
                  <div className="mb-2 min-w-0">
                    <span className="text-gray-600 dark:text-gray-400 text-xs uppercase">Pasted text</span>
                    <pre className="mt-1 whitespace-pre-wrap text-gray-800 dark:text-gray-200 text-xs max-h-32 max-w-full overflow-auto bg-white/50 dark:bg-white/5 p-2 rounded">
                      {sub.text_content}
                    </pre>
                  </div>
                )}
                {sub.comment && (
                  <div className="mb-2 min-w-0">
                    <span className="text-gray-600 dark:text-gray-400 text-xs uppercase">Comment</span>
                    <pre className="mt-1 whitespace-pre-wrap text-gray-800 dark:text-gray-200 text-xs max-h-32 max-w-full overflow-auto bg-white/50 dark:bg-white/5 p-2 rounded">
                      {sub.comment}
                    </pre>
                  </div>
                )}
                {sub.files?.length > 0 && (
                  <p className="text-gray-600 dark:text-gray-400 mt-2 text-xs">{sub.files.length} file(s) attached for your manager.</p>
                )}
                {task.status === 'submitted' ? (
                  <p className="text-amber-800 dark:text-amber-300/90 mt-2 text-xs">Awaiting project manager review.</p>
                ) : (
                  <p className="text-amber-800 dark:text-amber-300/90 mt-2 text-xs">Use this as reference, apply requested fixes, then submit again.</p>
                )}
              </div>
            )}

            {task.review_feedback?.comment && task.status === 'in_progress' && (
              <div className="mb-4 min-w-0 bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg p-4 text-sm">
                <p className="font-medium text-orange-900 dark:text-orange-200 mb-1">Changes requested by project manager</p>
                <pre className="mt-1 whitespace-pre-wrap text-gray-800 dark:text-gray-200 text-xs max-h-32 max-w-full overflow-auto bg-white/50 dark:bg-white/5 p-2 rounded">
                  {task.review_feedback.comment}
                </pre>
                {task.review_feedback.requested_at && (
                  <p className="text-xs text-orange-800 dark:text-orange-300/90 mt-2">
                    Requested at: {formatTaskDate(task.review_feedback.requested_at)}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              {canAct && task.status === 'assigned' && (
                <button
                  type="button"
                  onClick={() => handleStatusUpdate(task.id, 'in_progress')}
                  disabled={isLoading}
                  className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg transition-colors disabled:opacity-50 text-sm"
                >
                  Start Working
                </button>
              )}

              {canAct && task.status === 'in_progress' && (
                <button
                  type="button"
                  onClick={() => openSubmitModal(task)}
                  disabled={isLoading}
                  className="bg-amber-500 hover:bg-amber-600 text-white font-medium py-2 px-4 rounded-lg transition-colors disabled:opacity-50 text-sm"
                >
                  Submit for Review
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default TaskList;
