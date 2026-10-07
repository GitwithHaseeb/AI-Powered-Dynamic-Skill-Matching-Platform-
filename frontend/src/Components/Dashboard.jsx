// src/components/Dashboard.jsx
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import { Link } from 'react-router-dom';
import { projectService } from '../services/api.js';
import { userService } from '../services/api.js';
import { analyticsService } from '../services/api.js';
import { taskService } from '../services/api.js';
import { getApiErrorMessage } from '../services/api.js';
import { normalizeRole } from '../utils/auth.js';
import {
  projectsListPath,
  projectTeamMemberCount,
  formatProjectStatus,
  formatDeadline,
  roleBadgeClass,
  displayRoleFor,
} from '../utils/dashboard.js';
import { taskAssignedToUser } from '../utils/tasks.js';
import AnimatedNumber from './ui/AnimatedNumber.jsx';
import { CardSkeleton } from './ui/Skeleton.jsx';

/** Top-of-page KPI card. Defined at module level so the count-up isn't reset on every render. */
const StatCard = ({ title, value, suffix = '', subtitle, icon, color }) => (
  <div className="lift group relative overflow-hidden bg-white rounded-2xl shadow-card border border-gray-200 p-6">
    <div
      aria-hidden="true"
      className={`absolute -right-8 -top-8 h-24 w-24 rounded-full ${color} opacity-60 transition-transform duration-500 ease-smooth group-hover:scale-150`}
    />
    <div className="relative flex items-center">
      <div className={`w-12 h-12 ${color} rounded-xl flex items-center justify-center mr-4 ring-1 ring-inset ring-black/5`}>
        {icon}
      </div>
      <div>
        <div className="text-2xl font-bold text-gray-900">
          {value == null ? <span className="text-gray-400">—</span> : <AnimatedNumber value={value} suffix={suffix} />}
        </div>
        <div className="text-sm font-medium text-gray-700 mt-1">{title}</div>
        {subtitle && <div className="text-xs text-gray-500 mt-1">{subtitle}</div>}
      </div>
    </div>
  </div>
);

const Dashboard = () => {
  const { user } = useAuth();
  const STATS_CACHE_KEY = `dashboard_stats_v2_${normalizeRole(user?.role || 'developer')}`;
  const [projects, setProjects] = useState([]);
  const [completedProjects, setCompletedProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState(null);
  const [teamMembers, setTeamMembers] = useState([]);
  const [projectStats, setProjectStats] = useState(() => {
    try {
      const raw = localStorage.getItem(`dashboard_stats_v2_${normalizeRole(user?.role || 'developer')}`);
      if (raw) return JSON.parse(raw);
    } catch {}
    return {
      completionRate: 0,
      matchAccuracy: null, // null = no AI match scores recorded yet
      openTasks: 0,
      activeProjects: 0,
    };
  });

  // Preview: available developers first, then by number of skills, then name — all from the directory data.
  const topTeamMembers = useMemo(
    () =>
      [...(teamMembers || [])]
        .sort(
          (a, b) =>
            (b.availability === 'Full Time') - (a.availability === 'Full Time') ||
            (b.skills?.length || 0) - (a.skills?.length || 0) ||
            String(a.name).localeCompare(String(b.name))
        )
        .slice(0, 3),
    [teamMembers]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await userService.getDeveloperDirectory();
        if (cancelled) return;
        const raw = Array.isArray(rows) ? rows : [];
        const devOnly = raw.filter((d) => String(d.role || 'developer').toLowerCase() === 'developer');
        const byKey = new Map();
        for (const d of devOnly) {
          const email = String(d.email || '').trim().toLowerCase();
          const key = email || String(d.id || '').trim();
          if (!key) continue;
          if (!byKey.has(key)) byKey.set(key, d);
        }
        const mapped = [...byKey.values()].map((d) => ({
          id: d.id,
          name: d.full_name || d.name || d.username || d.email || 'Developer',
          skills: Array.isArray(d.skills) ? d.skills : [],
          availability: d.availability === false ? 'Part Time' : 'Full Time',
          contact: d.contact || d.email || '—',
        }));
        setTeamMembers(mapped.map((m) => ({ ...m, role: displayRoleFor(m) })));
      } catch {
        if (!cancelled) setTeamMembers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Live task-based metrics for developers (project-level completion is often 0% if no project is "completed"). */
  const refreshDeveloperTaskMetrics = useCallback(async () => {
    if (normalizeRole(user?.role) !== 'developer' || !user) return;
    if (!String(user.id ?? user._id ?? '').trim()) return;
    try {
      const taskData = await taskService.getTasks();
      const rows = Array.isArray(taskData) ? taskData : [];
      const mine = rows.filter((t) => {
        if (t.is_assigned_to_me === true) return true;
        if (t.is_assigned_to_me === false) return false;
        return taskAssignedToUser(t, user);
      });
      const completed = mine.filter(
        (t) => String(t.status || '').toLowerCase() === 'completed'
      ).length;
      const activeMine = mine.filter(
        (t) => String(t.status || '').toLowerCase() !== 'completed'
      );
      const total = mine.length;
      const completionRate = total > 0 ? Math.round((completed / total) * 100) : 0;
      const activeProjectIds = new Set(
        activeMine
          .map((t) => String(t.project_id ?? t.project ?? '').trim())
          .filter(Boolean)
      );
      const activeProjects = activeProjectIds.size;

      const scores = mine
        .map((t) => Number(t.match_score))
        .filter((n) => Number.isFinite(n) && n > 0);
      // Only real AI match scores (per task, else the profile score) — never derived from proficiency.
      let matchAccuracy = null;
      if (scores.length > 0) {
        matchAccuracy = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
      } else {
        const sm = Number(user.skill_match_score);
        if (Number.isFinite(sm) && sm > 0) matchAccuracy = Math.round(sm);
      }

      setProjectStats((s) => {
        const next = {
          ...s,
          completionRate,
          matchAccuracy,
          activeProjects,
          openTasks: activeMine.length,
        };
        try {
          localStorage.setItem(STATS_CACHE_KEY, JSON.stringify(next));
        } catch {
          /* ignore */
        }
        return next;
      });
    } catch {
      /* keep existing stats */
    }
  }, [user, STATS_CACHE_KEY]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setProjectsLoading(true);
      setProjectsError(null);
      try {
        const normalizedRole = normalizeRole(user?.role);
        const isDeveloper = normalizedRole === 'developer';
        const isManager = normalizedRole === 'manager';
        const isAdmin = normalizedRole === 'admin';

        let list;
        let completedList;
        if (isAdmin) {
          const all = await projectService.getProjects({ limit: 150 });
          if (cancelled) return;
          const arr = Array.isArray(all) ? all : [];
          list = arr.filter((p) => p.status !== 'completed');
          completedList = arr.filter((p) => p.status === 'completed');
        } else {
          [list, completedList] = await Promise.all([
            projectService.getProjects({ limit: 50 }),
            (isDeveloper || isManager)
              ? projectService.getProjects({ limit: 50, status: 'completed' })
              : Promise.resolve([]),
          ]);
        }
        if (cancelled) return;
        const rows = Array.isArray(list) ? list : [];
        const fromCompletedEndpoint = Array.isArray(completedList) ? completedList : [];
        const isProjectCompleted = (p) =>
          String(p?.status || '').toLowerCase() === 'completed';

        // Recent Projects: only non-completed (manager/dev "all" list can still include completed).
        const activeRows = rows.filter((p) => !isProjectCompleted(p));

        const completedById = new Map();
        for (const p of fromCompletedEndpoint) {
          if (p?.id) completedById.set(p.id, p);
        }
        for (const p of rows) {
          if (p?.id && isProjectCompleted(p)) completedById.set(p.id, p);
        }
        const completedMerged = [...completedById.values()];

        const isPm = isManager || isAdmin;
        setProjects(
          activeRows.map((p) => ({
            id: p.id,
            title: p.title,
            description: p.description || '',
            statusLabel: formatProjectStatus(p.status),
            statusRaw: p.status,
            progress: typeof p.progress === 'number' ? p.progress : 0,
            deadline: formatDeadline(p.deadline),
            members: projectTeamMemberCount(p),
            skills: Array.isArray(p.require_skills) ? p.require_skills : [],
            type: p.department || '—',
            createdByName: p.created_by_name || null,
            matchAccuracy:
              isPm && typeof p.avg_match_accuracy_pct === 'number'
                ? p.avg_match_accuracy_pct
                : null,
          }))
        );
        setCompletedProjects(
          completedMerged.map((p) => ({
            id: p.id,
            title: p.title,
            deadline: formatDeadline(p.deadline),
          }))
        );
        const active = activeRows.filter((p) => p.status === 'in_progress').length;
        const completed = completedMerged.length;
        const total = activeRows.length + completedMerged.length;
        const completionRate = total > 0 ? Math.round((completed / total) * 100) : 0;
        setProjectStats((s) => {
          const next = {
            ...s,
            activeProjects: active,
          };
          if (!isDeveloper) next.completionRate = completionRate;
          try {
            localStorage.setItem(STATS_CACHE_KEY, JSON.stringify(next));
          } catch {
            /* ignore */
          }
          return next;
        });
      } catch (e) {
        if (!cancelled) {
          setProjectsError(getApiErrorMessage(e, 'Could not load projects'));
          setProjects([]);
          setCompletedProjects([]);
        }
      } finally {
        if (!cancelled) setProjectsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.role]);

  useEffect(() => {
    if (normalizeRole(user?.role) !== 'developer') return;
    void refreshDeveloperTaskMetrics();
  }, [refreshDeveloperTaskMetrics]);

  const fetchDashboardStats = useCallback(async () => {
    const role = normalizeRole(user?.role);
    if (role === 'developer') {
      await refreshDeveloperTaskMetrics();
      return;
    }
    if (!['manager', 'admin'].includes(role)) {
      return;
    }
    let matchFromSummary = 0;
    try {
      const summary = await projectService.getStatsSummary();
      const ma = Number(summary?.avg_match_score_pct ?? 0);
      if (Number.isFinite(ma) && ma > 0) matchFromSummary = ma;
    } catch {
      /* use analytics blend below */
    }
    try {
      const dash = await analyticsService.getDashboard('all');
      const completion = Number(dash?.tasks?.completion_rate_pct || 0);
      const openActive = Number(dash?.tasks?.open_or_active || 0);
      setProjectStats((s) => {
        const next = {
          ...s,
          completionRate: Math.round(completion),
          matchAccuracy: matchFromSummary > 0 ? Math.round(matchFromSummary) : null,
          openTasks: openActive,
        };
        try {
          localStorage.setItem(STATS_CACHE_KEY, JSON.stringify(next));
        } catch {}
        return next;
      });
    } catch {
      if (matchFromSummary > 0) {
        setProjectStats((s) => {
          const next = { ...s, matchAccuracy: Math.round(matchFromSummary) };
          try {
            localStorage.setItem(STATS_CACHE_KEY, JSON.stringify(next));
          } catch {}
          return next;
        });
      }
    }
  }, [user?.role, STATS_CACHE_KEY, refreshDeveloperTaskMetrics]);

  useEffect(() => {
    fetchDashboardStats();
  }, [fetchDashboardStats]);

  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) fetchDashboardStats();
    }, 30000);
    return () => clearInterval(id);
  }, [fetchDashboardStats]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Welcome Section */}
        <div className="mb-8">
          <p className="text-sm font-medium text-blue-600 dark:text-blue-400">
            {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
          <h1 className="mt-1 text-3xl sm:text-4xl font-bold text-gray-900">
            Welcome back, <span className="text-gradient">{user?.name || user?.email}</span>
          </h1>
          <p className="text-gray-600 mt-2">Here&apos;s what is happening across your projects and teams.</p>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8 stagger">
          <StatCard
            title="Completion Rate"
            value={projectStats.completionRate}
            suffix="%"
            subtitle="Share of tasks marked completed"
            icon={<svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
            color="bg-green-50"
          />
          <StatCard 
            title="Match Accuracy" 
            value={projectStats.matchAccuracy}
            suffix="%"
            subtitle={projectStats.matchAccuracy == null ? 'No AI match scores yet' : 'Average AI match score'}
            icon={<svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>}
            color="bg-blue-50"
          />
          <StatCard 
            title="Open Tasks"
            value={projectStats.openTasks ?? 0}
            subtitle="Assigned or in progress"
            icon={<svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
            color="bg-purple-50"
          />
          <StatCard 
            title="Active Projects" 
            value={projectStats.activeProjects}
            subtitle="Currently in development"
            icon={<svg className="w-6 h-6 text-orange-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>}
            color="bg-orange-50"
          />
        </div>

        {/* Project Overview */}
        <div data-reveal className="bg-white rounded-2xl shadow-card border border-gray-200 p-6 sm:p-8 mb-8 transition-shadow duration-300 hover:shadow-card-hover">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h2 className="text-xl font-bold text-gray-900">AI Powered Dynamic Skill Matching Platform</h2>
              <p className="text-gray-600 mt-1">BSCS Final Project | Fall 2025 | Advisor: M. REHAN SALEEM</p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Project Description</h3>
              <p className="text-gray-600 mb-4">
                This project aims to develop a web-based platform that uses AI to dynamically match employees 
                to collaborative projects based on real-time skills, availability, and project requirements.
              </p>
              
              <h4 className="font-semibold text-gray-900 mb-2 mt-6">What the platform does</h4>
              <ul className="text-gray-600 space-y-2">
                {[
                  'Recommends project teams from developer skills, availability and current workload',
                  'Extracts required skills and tasks from an uploaded SRS document',
                  'Tracks tasks from assignment through PM review to completion',
                  'Answers project and team questions in English or Roman Urdu',
                ].map((item) => (
                  <li key={item} className="flex items-start">
                    <svg className="w-4 h-4 text-green-500 mr-2 mt-1 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Tools & Technologies</h3>
              <div className="flex flex-wrap gap-2 mb-6">
                {['React', 'Vite', 'Tailwind CSS', 'Material-UI', 'FastAPI', 'Python', 'MongoDB', 'scikit-learn', 'spaCy', 'Docker', 'Git/GitHub'].map((tool) => (
                  <span key={tool} className="px-3 py-1.5 bg-gray-100 text-gray-700 rounded-lg text-sm transition-all duration-300 ease-smooth hover:-translate-y-0.5 hover:bg-gray-200">
                    {tool}
                  </span>
                ))}
              </div>

              <h3 className="font-semibold text-gray-900 mb-4">Project Type</h3>
              <div className="flex flex-wrap gap-2">
                <span className="px-3 py-2 bg-blue-100 text-blue-700 rounded-lg text-sm transition-colors duration-300">Research based</span>
                <span className="px-3 py-2 bg-blue-100 text-blue-700 rounded-lg text-sm transition-colors duration-300">Software Development</span>
                <span className="px-3 py-2 bg-blue-100 text-blue-700 rounded-lg text-sm transition-colors duration-300">Artificial Intelligence (AI)</span>
                <span className="px-3 py-2 bg-blue-100 text-blue-700 rounded-lg text-sm transition-colors duration-300">Web Application</span>
              </div>
            </div>
          </div>
        </div>

        {/* Team Members Section */}
        <div data-reveal className="mb-8">
          <div className="flex justify-between items-center mb-6 flex-wrap gap-2">
            <h2 className="text-xl font-bold text-gray-900">Team Members</h2>
            <div className="flex items-center gap-3">
              <span className="px-3 py-1 bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200 rounded-full text-sm font-medium">
                {teamMembers.length} developers
              </span>
              <Link
                to="/developers"
                className="group inline-flex items-center text-blue-600 hover:text-blue-700 font-medium transition-colors duration-300"
              >
                View all developers
                <span aria-hidden="true" className="ml-1 transition-transform duration-300 ease-smooth group-hover:translate-x-1">→</span>
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 stagger">
            {topTeamMembers.map((member) => (
              <div key={member.id} className="lift bg-white rounded-2xl shadow-card border border-gray-200 p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="h-11 w-11 shrink-0 rounded-full bg-gradient-to-br from-sky-400 to-indigo-600 text-white flex items-center justify-center text-sm font-semibold shadow-sm">
                      {String(member.name || '?')
                        .split(' ')
                        .map((w) => w[0])
                        .join('')
                        .slice(0, 2)
                        .toUpperCase()}
                    </div>
                    <h3 className="font-bold text-gray-900 truncate">{member.name}</h3>
                  </div>
                  {/* Badge reflects the developer's stored availability flag. */}
                  <span
                    className={`shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full ring-1 ring-inset ${
                      member.availability === 'Full Time'
                        ? 'bg-green-50 text-green-700 ring-green-600/15'
                        : 'bg-amber-50 text-amber-700 ring-amber-600/20'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${member.availability === 'Full Time' ? 'bg-green-500' : 'bg-amber-500'}`}
                      aria-hidden="true"
                    />
                    {member.availability === 'Full Time' ? 'Available' : 'Limited'}
                  </span>
                </div>

                <div className="mb-4">
                  <span
                    className={`inline-flex mb-2 px-2.5 py-1 rounded-md border text-xs font-semibold tracking-wide ${roleBadgeClass(member.role)}`}
                  >
                    {member.role}
                  </span>
                  <p className="text-sm text-gray-600">Availability: {member.availability}</p>
                  <p className="text-sm text-gray-600 mt-1">Contact: {member.contact}</p>
                </div>

                <div>
                  <p className="text-sm text-gray-700 mb-2">Skills:</p>
                  <div className="flex flex-wrap gap-1">
                    {member.skills.map((skill, idx) => {
                      const label =
                        typeof skill === 'string' ? skill : skill.skill_name;
                      const key =
                        typeof skill === 'string' ? `${skill}-${idx}` : `${skill.skill_name}-${idx}`;
                      return (
                        <span
                          key={key}
                          className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs transition-colors duration-300"
                        >
                          {label}
                        </span>
                      );
                    })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent projects: active / in-progress only; completed only in section below */}
        <div data-reveal className="bg-white rounded-2xl shadow-card border border-gray-200 p-6 sm:p-8 mb-8 dark:bg-gray-800 dark:border-gray-700">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Recent Projects</h2>
            <Link
              to={projectsListPath(user?.role)}
              className="group inline-flex items-center text-blue-600 hover:text-blue-700 dark:text-blue-400 font-medium transition-colors duration-300"
            >
              View All Projects
              <span aria-hidden="true" className="ml-1 transition-transform duration-300 ease-smooth group-hover:translate-x-1">→</span>
            </Link>
          </div>

          {projectsLoading && !projects.length && (
            <div className="space-y-4">
              <CardSkeleton />
              <CardSkeleton />
            </div>
          )}
          {projectsError && (
            <p className="text-red-600 text-sm py-2">{projectsError}</p>
          )}

          <div className="space-y-4 stagger">
            {!projectsLoading && !projects.length && !projectsError && (
              <p className="text-gray-600 text-sm py-4 dark:text-gray-400">
                No active projects to show yet, or none visible for your account.
              </p>
            )}
            {projects.map((project) => (
              <div key={project.id} className="lift border border-gray-200 rounded-xl p-6 hover:border-blue-200 dark:hover:border-blue-800">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <h3 className="font-semibold text-gray-900">{project.title}</h3>
                    <p className="text-gray-600 mt-1">{project.description}</p>
                    {project.createdByName && (
                      <p className="text-gray-500 text-sm mt-2">
                        Created by: <span className="font-medium text-gray-700">{project.createdByName}</span>
                      </p>
                    )}
                  </div>
                  <div className="text-right">
                    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium transition-colors duration-300 ${
                      project.statusRaw === 'completed' ? 'bg-green-100 text-green-800' :
                      project.statusRaw === 'in_progress' ? 'bg-blue-100 text-blue-800' :
                      'bg-yellow-100 text-yellow-800'
                    }`}>
                      {project.statusLabel}
                    </span>
                    <p className="text-sm text-gray-600 mt-1">Due: {project.deadline}</p>
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-6">
                    <div>
                      <div className="text-sm text-gray-600">Progress</div>
                      <div className="flex items-center">
                        <div className="w-32 bg-gray-200 rounded-full h-2 mr-3 overflow-hidden">
                          <div
                            className="progress-fill bg-gradient-to-r from-blue-500 to-indigo-600 h-2 rounded-full"
                            style={{ width: `${project.progress}%` }}
                          ></div>
                        </div>
                        <span className="text-sm font-medium text-gray-900">{project.progress}%</span>
                      </div>
                    </div>

                    <div>
                      <div className="text-sm text-gray-600">Team Size</div>
                      <div className="font-medium text-gray-900">{project.members} members</div>
                    </div>

                    {typeof project.matchAccuracy === 'number' && (
                      <div>
                        <div className="text-sm text-gray-600 dark:text-gray-400">Avg. match accuracy</div>
                        <div className="font-medium text-sky-700 dark:text-sky-400">
                          {Math.round(project.matchAccuracy)}%
                        </div>
                      </div>
                    )}

                    <div>
                      <div className="text-sm text-gray-600">Type</div>
                      <div className="font-medium text-gray-900">{project.type}</div>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-1">
                    {project.skills.slice(0, 3).map((skill) => (
                      <span key={skill} className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs transition-colors duration-300">
                        {skill}
                      </span>
                    ))}
                    {project.skills.length > 3 && (
                      <span className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs transition-colors duration-300">
                        +{project.skills.length - 3}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {['developer', 'manager', 'admin'].includes(normalizeRole(user?.role)) && (
          <div data-reveal className="bg-white dark:bg-gray-800/95 rounded-2xl shadow-card border border-gray-200 dark:border-gray-700 p-6 sm:p-8">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Completed Projects</h2>
              <span className="px-2.5 py-1 min-w-[2rem] text-center bg-emerald-100 dark:bg-emerald-900/45 text-emerald-800 dark:text-emerald-200 text-xs font-semibold rounded-full tabular-nums">
                {completedProjects.length}
              </span>
            </div>
            {!completedProjects.length ? (
              <p className="text-gray-600 dark:text-gray-400 text-sm">No completed projects yet.</p>
            ) : (
              <div className="space-y-3 stagger">
                {completedProjects.map((project) => (
                  <div
                    key={project.id}
                    className="lift flex items-center justify-between gap-4 rounded-xl border border-emerald-200/90 dark:border-emerald-800/60 bg-emerald-50/95 dark:bg-emerald-950/40 p-4 shadow-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-gray-900 dark:text-gray-100 leading-snug">
                        {project.title}
                      </p>
                      <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                        Deadline: {project.deadline}
                      </p>
                    </div>
                    <span className="shrink-0 inline-flex items-center gap-1 text-xs font-bold text-emerald-800 dark:text-emerald-400">
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                      </svg>
                      Completed
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Dashboard;