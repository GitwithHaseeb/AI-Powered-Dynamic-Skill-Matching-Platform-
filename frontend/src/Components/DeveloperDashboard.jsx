// src/components/DeveloperDashboard.jsx
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import TaskList from './TaskList.jsx';
import SkillProfile from './SkillProfile.jsx';
import { taskService, projectService, userService } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { taskAssignedToUser } from '../utils/tasks.js';
import AnimatedNumber from './ui/AnimatedNumber.jsx';

const DeveloperDashboard = () => {
  const [tasks, setTasks] = useState([]);
  const [showSkillForm, setShowSkillForm] = useState(false);
  const [showCompletedTasksModal, setShowCompletedTasksModal] = useState(false);
  /** 'active' = assigned / in progress / submitted (anything not yet completed by PM). */
  const [projectTasksTab, setProjectTasksTab] = useState('active');
  const [, setDeveloperStats] = useState({
    completedTasks: 0,
    currentWorkload: 0,
    skillMatchScore: 0,
    performanceScore: 0
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isBackgroundRefreshing, setIsBackgroundRefreshing] = useState(false);
  const [error, setError] = useState('');
  const { user, updateUser } = useAuth();

  const fetchTasks = useCallback(async (opts = {}) => {
    const background = opts.background === true;
    try {
      if (background) {
        setIsBackgroundRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setError('');
      const normId = (x) => String(x ?? '');
      const [taskData, projectData] = await Promise.all([
        taskService.getTasks(),
        projectService.getProjects(),
      ]);
      const allProjects = Array.isArray(projectData) ? projectData : [];

      const projectMap = new Map();
      for (const p of allProjects) {
        projectMap.set(normId(p.id), p.title);
      }

      const enrichedTasks = (taskData || []).map((t) => ({
        ...t,
        project_title:
          projectMap.get(normId(t.project_id ?? t.project)) ||
          t.project_title ||
          normId(t.project_id ?? t.project),
      }));
      setTasks(enrichedTasks);
    } catch (err) {
      setError('Failed to load tasks');
      console.error('Error fetching tasks:', err);
    } finally {
      if (background) {
        setIsBackgroundRefreshing(false);
      } else {
        setIsLoading(false);
      }
    }
  }, []);

  const fetchDeveloperStats = useCallback(async () => {
    if (!user) return;
    try {
      const completedTasks = tasks.filter(
        (t) => taskAssignedToUser(t, user) && String(t.status || '').toLowerCase() === 'completed'
      ).length;
      const mine = tasks.filter((t) => taskAssignedToUser(t, user));
      const performanceHistory = user.performance_history || [4.0];
      const avgPerformance =
        performanceHistory.reduce((a, b) => a + b, 0) / performanceHistory.length;

      setDeveloperStats({
        completedTasks,
        currentWorkload: mine.length,
        skillMatchScore: user.skill_match_score || 85,
        performanceScore: avgPerformance.toFixed(1),
      });
    } catch (err) {
      console.error('Error fetching developer stats:', err);
    }
  }, [tasks, user]);

  useEffect(() => {
    void fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    void fetchDeveloperStats();
  }, [fetchDeveloperStats]);

  useEffect(() => {
    if (!showCompletedTasksModal) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setShowCompletedTasksModal(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showCompletedTasksModal]);

  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) void fetchTasks({ background: true });
    }, 10000);
    return () => clearInterval(id);
  }, [fetchTasks]);

  // Refetch when returning to this tab/window so PM-approved completions show up without a full reload.
  useEffect(() => {
    let t;
    const scheduleRefetch = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        void fetchTasks({ background: true });
      }, 200);
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') scheduleRefetch();
    };
    const onPageShow = (e) => {
      if (e.persisted) scheduleRefetch();
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', scheduleRefetch);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      clearTimeout(t);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', scheduleRefetch);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [fetchTasks]);

  const updateTaskStatus = async (taskId, newStatus) => {
    try {
      setIsLoading(true);
      setError('');

      await taskService.updateTaskStatus(taskId, newStatus);

      setTasks((prev) =>
        prev.map((task) => (task.id === taskId ? { ...task, status: newStatus } : task))
      );

      await fetchDeveloperStats();

      return { success: true };
    } catch (err) {
      const message = err.response?.data?.detail || 'Failed to update task';
      setError(message);
      return { success: false, error: message };
    } finally {
      setIsLoading(false);
    }
  };

  const submitForReview = async (taskId, payload) => {
    try {
      setIsLoading(true);
      setError('');
      await taskService.submitTaskForReview(taskId, payload);
      await fetchTasks();
      await fetchDeveloperStats();
      return { success: true };
    } catch (err) {
      const message = err.response?.data?.detail || 'Failed to submit for review';
      setError(message);
      return { success: false, error: message };
    } finally {
      setIsLoading(false);
    }
  };

  const updateSkills = async (skillsToAdd) => {
    try {
      setIsLoading(true);
      setError('');

      const response = await userService.updateSkills(user.id, skillsToAdd);

      updateUser({ ...user, skills: response.skills });

      setShowSkillForm(false);
      return { success: true };
    } catch (err) {
      const message = err.response?.data?.detail || 'Failed to update skills';
      setError(message);
      return { success: false, error: message };
    } finally {
      setIsLoading(false);
    }
  };

  const myCompletedTasks = tasks
    .filter(
      (t) =>
        taskAssignedToUser(t, user) && String(t.status || '').toLowerCase() === 'completed'
    )
    .sort((a, b) => {
      const da = new Date(a.end_date || a.updated_at || a.created_at || 0).getTime();
      const db = new Date(b.end_date || b.updated_at || b.created_at || 0).getTime();
      return db - da;
    });

  const formatCompletedDate = (task) => {
    const raw = task.end_date || task.updated_at || task.created_at;
    if (!raw) return 'N/A';
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return 'N/A';
    return d.toLocaleDateString();
  };

  const { activeTasks, completedTasksList } = useMemo(() => {
    const active = [];
    const done = [];
    const completionTime = (t) =>
      new Date(
        t.end_date || t.completed_at || t.updated_at || t.created_at || 0
      ).getTime();
    for (const t of tasks) {
      if (!taskAssignedToUser(t, user)) continue;
      if (String(t.status || '').toLowerCase() === 'completed') {
        done.push(t);
      } else {
        active.push(t);
      }
    }
    done.sort((a, b) => completionTime(b) - completionTime(a));
    return { activeTasks: active, completedTasksList: done };
  }, [tasks, user]);

  const tasksForProjectTab =
    projectTasksTab === 'completed' ? completedTasksList : activeTasks;
  const taskListVariant = projectTasksTab === 'completed' ? 'completed' : 'active';

  return (
    <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h2 className="text-3xl font-bold text-gray-900 dark:text-gray-50 tracking-tight">
            Developer Dashboard
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mt-2 text-sm sm:text-base max-w-2xl">
            Manage your tasks; add new skills (levels update when tasks complete)
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowSkillForm(true)}
          disabled={isLoading}
          className="group inline-flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-semibold py-3 px-6 rounded-xl shadow-lg shadow-blue-600/25 hover:shadow-xl hover:shadow-blue-600/30 disabled:opacity-50"
        >
          <svg className="h-5 w-5 transition-transform duration-300 ease-smooth group-hover:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" d="M12 5v14M5 12h14" />
          </svg>
          Add skills
        </button>
      </div>

      {error && (
        <div className="mb-6 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-300 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* Developer Stats — counted from the tasks and profile already on screen */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-8 stagger">
        {[
          ['Active tasks', activeTasks.length, 'from-blue-500 to-indigo-600', 'M13 10V3L4 14h7v7l9-11h-7z'],
          ['Completed tasks', completedTasksList.length, 'from-emerald-500 to-teal-600', 'M5 13l4 4L19 7'],
          ['Skills on profile', (user?.skills || []).length, 'from-violet-500 to-fuchsia-600', 'M11.48 3.5a.56.56 0 011.04 0l2.12 5.11 5.52.44c.5.04.7.66.32.98l-4.2 3.6 1.28 5.38a.56.56 0 01-.84.61L12 16.73l-4.72 2.89a.56.56 0 01-.84-.61l1.28-5.38-4.2-3.6a.56.56 0 01.32-.98l5.52-.44 2.12-5.11z'],
        ].map(([label, value, gradient, path]) => (
          <div
            key={label}
            className="lift flex items-center gap-4 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 shadow-card"
          >
            <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${gradient} text-white shadow-md`}>
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={path} />
              </svg>
            </span>
            <div>
              <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                <AnimatedNumber value={value} />
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">{label}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div>
          <div className="flex flex-col gap-3 mb-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
              <div>
                <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Project tasks</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {tasks.length} visible on your projects ·{' '}
                  {tasks.filter((t) => taskAssignedToUser(t, user)).length} assigned to you
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowCompletedTasksModal(true)}
                className="shrink-0 w-full sm:w-auto text-center px-4 py-2 rounded-xl text-sm font-semibold border border-emerald-600/80 text-emerald-700 dark:text-emerald-300 dark:border-emerald-500/60 bg-emerald-50/50 dark:bg-emerald-950/30 hover:bg-emerald-100/80 dark:hover:bg-emerald-900/40 transition-colors duration-200"
              >
                My completed history
              </button>
            </div>

            <div className="rounded-2xl border border-gray-200/90 dark:border-gray-700 bg-gray-50/90 dark:bg-gray-900/55 shadow-sm overflow-hidden">
              <nav
                className="flex flex-col sm:flex-row sm:items-stretch divide-y sm:divide-y-0 sm:divide-x divide-gray-200/90 dark:divide-gray-700"
                role="tablist"
                aria-label="Task filter"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={projectTasksTab === 'active'}
                  onClick={() => setProjectTasksTab('active')}
                  className={`relative flex-1 text-left sm:text-center px-5 py-4 text-[0.95rem] font-semibold outline-none transition-all duration-200 ease-out focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${
                    projectTasksTab === 'active'
                      ? 'text-gray-900 dark:text-white bg-white dark:bg-gray-950/40 shadow-[inset_0_-3px_0_0_rgb(59,130,246)] dark:shadow-[inset_0_-3px_0_0_rgb(96,165,250)]'
                      : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-white/70 dark:hover:bg-gray-800/65 active:scale-[0.99]'
                  }`}
                >
                  <span className="block sm:inline">
                    <span
                      className={
                        projectTasksTab === 'active'
                          ? 'text-gray-900 dark:text-white'
                          : ''
                      }
                    >
                      Active Tasks
                    </span>{' '}
                    <span
                      className={`tabular-nums ${
                        projectTasksTab === 'active'
                          ? 'text-blue-600 dark:text-blue-300 font-bold'
                          : 'text-gray-400 dark:text-gray-500 font-semibold'
                      }`}
                    >
                      ({activeTasks.length})
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={projectTasksTab === 'completed'}
                  onClick={() => setProjectTasksTab('completed')}
                  className={`relative flex-1 text-left sm:text-center px-5 py-4 text-[0.95rem] font-semibold outline-none transition-all duration-200 ease-out focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-500 ${
                    projectTasksTab === 'completed'
                      ? 'text-gray-900 dark:text-white bg-white dark:bg-gray-950/40 shadow-[inset_0_-3px_0_0_rgb(16,185,129)] dark:shadow-[inset_0_-3px_0_0_rgb(52,211,153)]'
                      : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-white/70 dark:hover:bg-gray-800/65 active:scale-[0.99]'
                  }`}
                >
                  <span className="block sm:inline">
                    <span
                      className={
                        projectTasksTab === 'completed'
                          ? 'text-gray-900 dark:text-white'
                          : ''
                      }
                    >
                      Completed Tasks
                    </span>{' '}
                    <span
                      className={`tabular-nums ${
                        projectTasksTab === 'completed'
                          ? 'text-emerald-600 dark:text-emerald-300 font-bold'
                          : 'text-gray-400 dark:text-gray-500 font-semibold'
                      }`}
                    >
                      ({completedTasksList.length})
                    </span>
                  </span>
                </button>
              </nav>
            </div>

            {isBackgroundRefreshing && (
              <div
                className="flex items-center gap-2 px-1 text-xs font-medium text-blue-600 dark:text-blue-400"
                role="status"
                aria-live="polite"
              >
                <span
                  className="inline-block h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent animate-spin shrink-0 opacity-90"
                  aria-hidden
                />
                Refreshing...
              </div>
            )}
          </div>

          {isLoading && tasks.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-12 h-12 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
              <div className="text-gray-600">Loading tasks...</div>
            </div>
          ) : (
            <TaskList
              tasks={tasksForProjectTab}
              listVariant={taskListVariant}
              onUpdateStatus={updateTaskStatus}
              onSubmitForReview={submitForReview}
              isLoading={isLoading}
              emptyTitle={
                projectTasksTab === 'completed'
                  ? "You haven't completed any tasks yet. Keep going!"
                  : 'No active tasks right now. All tasks are completed!'
              }
              emptySubtitle={
                projectTasksTab === 'completed'
                  ? 'Approved work will show here, newest first.'
                  : 'Switch to Completed Tasks to review finished work, or wait for new assignments from your manager.'
              }
            />
          )}
        </div>

        <div>
          <SkillProfile
            showForm={showSkillForm}
            onOpenForm={() => setShowSkillForm(true)}
            onCloseForm={() => setShowSkillForm(false)}
            onUpdateSkills={updateSkills}
            userSkills={user?.skills || []}
            isLoading={isLoading}
          />
        </div>
      </div>

      {showCompletedTasksModal && (
        <div
          className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
          role="dialog"
          aria-modal="true"
          onMouseDown={() => setShowCompletedTasksModal(false)}
        >
          <div
            className="modal-panel bg-white dark:bg-gray-900 rounded-2xl shadow-xl max-w-3xl w-full max-h-[90vh] overflow-hidden border border-gray-200 dark:border-gray-700"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <h4 className="text-lg font-semibold text-gray-900 dark:text-gray-100">My Completed Tasks</h4>
              <button
                type="button"
                onClick={() => setShowCompletedTasksModal(false)}
                className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                Close
              </button>
            </div>

            <div className="p-5 overflow-y-auto max-h-[calc(90vh-76px)]">
              {myCompletedTasks.length === 0 ? (
                <div className="text-center py-10 text-gray-500 dark:text-gray-400">
                  No completed tasks yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {myCompletedTasks.map((task) => (
                    <div
                      key={task.id}
                      className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{task.title}</p>
                          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                            Project: {task.project_title || task.project || 'N/A'}
                          </p>
                          <p className="text-xs text-gray-600 dark:text-gray-400">
                            Completion Date: {formatCompletedDate(task)}
                          </p>
                          {task.description ? (
                            <p className="text-xs text-gray-500 dark:text-gray-400 mt-2 line-clamp-2">{task.description}</p>
                          ) : null}
                        </div>
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200">
                          Completed
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DeveloperDashboard;