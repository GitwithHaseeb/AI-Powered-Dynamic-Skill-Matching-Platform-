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

/** Directory of running projects (admin uses same read-only list as PM/dev). */
function projectsListPath(role) {
  const r = normalizeRole(role);
  if (r === 'developer' || r === 'manager' || r === 'admin') return '/projects';
  return '/dashboard';
}

function projectTeamMemberCount(p) {
  const team = p.assigned_team || p.final_team || [];
  const ids = Array.isArray(team)
    ? [...new Set(team.map((x) => (x != null ? String(x) : '')).filter(Boolean))]
    : [];
  const fromTeam = ids.length;
  const ts = typeof p.team_size === 'number' ? Math.max(0, Math.floor(p.team_size)) : 0;
  if (fromTeam > 0) return fromTeam;
  return ts;
}

function formatProjectStatus(status) {
  if (!status) return '—';
  const map = {
    in_progress: 'In Progress',
    planning: 'Planning',
    completed: 'Completed',
    on_hold: 'On Hold',
  };
  return map[status] || String(status).replace(/_/g, ' ');
}

function formatDeadline(d) {
  if (!d) return '—';
  try {
    const x = new Date(d);
    if (Number.isNaN(x.getTime())) return String(d).slice(0, 10);
    return x.toLocaleDateString();
  } catch {
    return '—';
  }
}

function inferDeveloperType(skills = []) {
  const names = (skills || [])
    .map((s) => (typeof s === 'string' ? s : s?.skill_name))
    .filter(Boolean)
    .map((x) => String(x).toLowerCase());

  const hasAny = (arr) => arr.some((k) => names.some((n) => n.includes(k)));
  const fe = hasAny(['react', 'vue', 'angular', 'typescript', 'javascript', 'ui', 'material', 'tailwind', 'next']);
  const be = hasAny(['fastapi', 'django', 'spring', 'node', 'express', 'java', 'python', 'sql', 'mongodb', 'postgres', 'redis', 'api']);
  const qa = hasAny(['test', 'testing', 'qa', 'selenium', 'cypress', 'junit']);
  const ui = hasAny(['ui', 'ux', 'figma', 'material', 'design']);

  if (ui && !be) return 'UI Designer';
  if (qa && !fe && !be) return 'Tester';
  if (fe && be) return 'Full Stack Developer';
  if (be) return 'Backend Developer';
  if (fe) return 'Frontend Developer';
  if (qa) return 'Tester';
  return 'Frontend Developer';
}

function roleBadgeClass(role) {
  const r = String(role || '').toLowerCase();
  if (r.includes('full stack')) return 'bg-purple-600 text-white border-purple-500';
  if (r.includes('frontend')) return 'bg-blue-600 text-white border-blue-500';
  if (r.includes('backend')) return 'bg-emerald-600 text-white border-emerald-500';
  if (r.includes('ui')) return 'bg-pink-600 text-white border-pink-500';
  if (r.includes('tester')) return 'bg-amber-600 text-white border-amber-500';
  return 'bg-indigo-600 text-white border-indigo-500';
}

function displayRoleFor(member) {
  const nameKey = String(member?.name || '').trim().toLowerCase();
  const manual = {
    'kosain ali': 'Full Stack Developer',
    aima: 'Backend Developer',
  };
  if (manual[nameKey]) return manual[nameKey];
  const inferred = inferDeveloperType(member?.skills || []);
  if (
    ['Full Stack Developer', 'Frontend Developer', 'Backend Developer', 'UI Designer', 'Tester'].includes(
      inferred
    )
  ) {
    return inferred;
  }
  return 'Frontend Developer';
}

/** Same rule as DeveloperDashboard: only tasks assigned to the logged-in user. */
function taskAssignedToUser(task, user) {
  if (!user || !task) return false;
  if (task.is_assigned_to_me === true) return true;
  if (task.is_assigned_to_me === false) return false;
  const uid = String(user.id ?? user._id ?? '').trim();
  const aid = String(task.assigned_to ?? '').trim();
  if (uid && aid && uid === aid) return true;
  const userEmail = String(user.email ?? '').trim().toLowerCase();
  if (userEmail && aid.toLowerCase() === userEmail) return true;
  const userName = String(user.username ?? user.name ?? user.full_name ?? '').trim();
  if (userName && aid === userName) return true;
  return false;
}

const Dashboard = () => {
  const { user, logout } = useAuth();
  const STATS_CACHE_KEY = `dashboard_stats_${normalizeRole(user?.role || 'developer')}`;
  const [activeTab, setActiveTab] = useState('overview');
  const [projects, setProjects] = useState([]);
  const [completedProjects, setCompletedProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState(null);
  const [teamMembers, setTeamMembers] = useState([]);
  const [projectStats, setProjectStats] = useState(() => {
    try {
      const raw = localStorage.getItem(`dashboard_stats_${normalizeRole(user?.role || 'developer')}`);
      if (raw) return JSON.parse(raw);
    } catch {}
    return {
      completionRate: 0,
      matchAccuracy: 0,
      productivityGain: 0,
      activeProjects: 0,
    };
  });

  const topTeamMembers = useMemo(() => {
    const preferred = ['muhammad haseeb', 'ghania tanveer'];
    const byName = (teamMembers || []).reduce((acc, m) => {
      const k = String(m?.name || '').trim().toLowerCase();
      if (k) acc.set(k, m);
      return acc;
    }, new Map());
    const ordered = [];
    for (const p of preferred) {
      const hit = byName.get(p);
      if (hit) ordered.push(hit);
    }
    for (const m of teamMembers || []) {
      if (!ordered.find((x) => x.id === m.id)) ordered.push(m);
    }
    return ordered.slice(0, 3);
  }, [teamMembers]);

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
      let matchAccuracy = 0;
      if (scores.length > 0) {
        matchAccuracy = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
      } else {
        const sm = Number(user.skill_match_score);
        if (Number.isFinite(sm) && sm > 0) {
          matchAccuracy = Math.round(sm);
        } else {
          const skills = Array.isArray(user.skills) ? user.skills : [];
          const profs = skills
            .map((s) => Number(s.proficiency_level))
            .filter((n) => Number.isFinite(n) && n > 0);
          if (profs.length > 0) {
            const avg = profs.reduce((a, b) => a + b, 0) / profs.length;
            matchAccuracy = Math.round((avg / 5) * 100);
          }
        }
      }

      setProjectStats((s) => {
        const productivityGain =
          total > 0 ? Math.max(0, Math.min(100, Math.round((activeMine.length / total) * 100))) : 0;
        const next = {
          ...s,
          completionRate,
          matchAccuracy,
          activeProjects,
          productivityGain,
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
          if (isDeveloper) {
            next.productivityGain =
              active > 0 ? Math.max(5, Math.min(100, active * 10)) : 0;
          } else {
            next.completionRate = completionRate;
          }
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
      const utilization = Number(dash?.skill_utilization_pct || 0);
      const openActive = Number(dash?.tasks?.open_or_active || 0);
      const totalTasks = Number(dash?.tasks?.total || 0);
      const blendedMatch = Math.round(completion * 0.55 + utilization * 0.45);
      setProjectStats((s) => {
        const next = {
          ...s,
          completionRate: Math.round(completion),
          matchAccuracy:
            matchFromSummary > 0 ? Math.round(matchFromSummary) : blendedMatch,
          productivityGain: totalTasks > 0 ? Math.round((openActive / totalTasks) * 100) : 0,
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
      fetchDashboardStats();
    }, 30000);
    return () => clearInterval(id);
  }, [fetchDashboardStats]);

  const StatCard = ({ title, value, subtitle, icon, color }) => (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 transition-colors duration-300 hover:shadow-md">
      <div className="flex items-center">
        <div className={`w-12 h-12 ${color} rounded-lg flex items-center justify-center mr-4`}>
          {icon}
        </div>
        <div>
          <div className="text-2xl font-bold text-gray-900">{value}</div>
          <div className="text-sm font-medium text-gray-700 mt-1">{title}</div>
          {subtitle && <div className="text-xs text-gray-500 mt-1">{subtitle}</div>}
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Welcome Section */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Welcome back, {user?.name || user?.email}!</h1>
          <p className="text-gray-600 mt-2">AI-Powered Dynamic Skill Matching Platform Dashboard</p>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard 
            title="Completion Rate" 
            value={`${projectStats.completionRate}%`}
            subtitle="Tasks completed on time"
            icon={<svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
            color="bg-green-50"
          />
          <StatCard 
            title="Match Accuracy" 
            value={`${projectStats.matchAccuracy}%`}
            subtitle="AI recommendation accuracy"
            icon={<svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>}
            color="bg-blue-50"
          />
          <StatCard 
            title="Productivity Gain" 
            value={`${projectStats.productivityGain}% faster`}
            subtitle="Team formation speed"
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
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8 transition-colors duration-300 hover:shadow-md">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h2 className="text-xl font-bold text-gray-900">AI Powered Dynamic Skill Matching Platform</h2>
              <p className="text-gray-600 mt-1">BSCS Final Project | Fall 2025 | Advisor: M. REHAN SALEEM</p>
            </div>
            <div className="px-4 py-2 bg-blue-50 text-blue-700 rounded-lg font-medium transition-colors duration-300">
              Progress: 75%
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Project Description</h3>
              <p className="text-gray-600 mb-4">
                This project aims to develop a web-based platform that uses AI to dynamically match employees 
                to collaborative projects based on real-time skills, availability, and project requirements.
              </p>
              
              <h4 className="font-semibold text-gray-900 mb-2 mt-6">Expected Results:</h4>
              <ul className="text-gray-600 space-y-2">
                <li className="flex items-center">
                  <svg className="w-4 h-4 text-green-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
                  30% faster team formation compared to manual processes
                </li>
                <li className="flex items-center">
                  <svg className="w-4 h-4 text-green-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
                  20% improvement in project success rates
                </li>
                <li className="flex items-center">
                  <svg className="w-4 h-4 text-green-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
                  15% reduction in managerial workload via automation
                </li>
                <li className="flex items-center">
                  <svg className="w-4 h-4 text-green-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>
                  Increased employee satisfaction by aligning work with individual skills
                </li>
              </ul>
            </div>

            <div>
              <h3 className="font-semibold text-gray-900 mb-4">Tools & Technologies</h3>
              <div className="flex flex-wrap gap-2 mb-6">
                {['React.js', 'Node.js', 'MongoDB', 'Python', 'Scikit-learn', 'Docker', 'AWS EC2', 'Git/GitHub', 'Material-UI', 'Express.js'].map((tool) => (
                  <span key={tool} className="px-3 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm transition-colors duration-300">
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
        <div className="mb-8">
          <div className="flex justify-between items-center mb-6 flex-wrap gap-2">
            <h2 className="text-xl font-bold text-gray-900">Team Members</h2>
            <div className="flex items-center gap-3">
              <span className="px-3 py-1 bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200 rounded-full text-sm font-medium">
                {teamMembers.length} developers
              </span>
              <Link
                to="/developers"
                className="text-blue-600 hover:text-blue-700 font-medium transition-colors duration-300"
              >
                View all developers →
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {topTeamMembers.map((member) => (
              <div key={member.id} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:shadow-md transition-all duration-300">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="font-bold text-gray-900">{member.name}</h3>
                  </div>
                  <span className="px-3 py-1 bg-green-50 text-green-700 text-sm rounded-lg transition-colors duration-300">
                    Active
                  </span>
                </div>

                <div className="mb-4">
                  <span
                    className={`inline-flex px-2.5 py-1 rounded-md border text-xs font-semibold tracking-wide ${roleBadgeClass(member.role)}`}
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
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 transition-colors duration-300 hover:shadow-md dark:bg-gray-800 dark:border-gray-700">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Recent Projects</h2>
            <Link
              to={projectsListPath(user?.role)}
              className="text-blue-600 hover:text-blue-700 dark:text-blue-400 font-medium transition-colors duration-300"
            >
              View All Projects →
            </Link>
          </div>

          {projectsLoading && (
            <p className="text-gray-600 text-sm py-4">Loading projects…</p>
          )}
          {projectsError && (
            <p className="text-red-600 text-sm py-2">{projectsError}</p>
          )}

          <div className="space-y-4">
            {!projectsLoading && !projects.length && !projectsError && (
              <p className="text-gray-600 text-sm py-4 dark:text-gray-400">
                No active projects to show yet, or none visible for your account.
              </p>
            )}
            {projects.map((project) => (
              <div key={project.id} className="border border-gray-100 rounded-lg p-6 hover:bg-gray-50 transition-colors duration-300">
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
                        <div className="w-32 bg-gray-200 rounded-full h-2 mr-3">
                          <div 
                            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
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
          <div className="bg-white dark:bg-gray-800/95 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 transition-colors duration-300 hover:shadow-md">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Completed Projects</h2>
              <span className="px-2.5 py-1 min-w-[2rem] text-center bg-emerald-100 dark:bg-emerald-900/45 text-emerald-800 dark:text-emerald-200 text-xs font-semibold rounded-full tabular-nums">
                {completedProjects.length}
              </span>
            </div>
            {!completedProjects.length ? (
              <p className="text-gray-600 dark:text-gray-400 text-sm">No completed projects yet.</p>
            ) : (
              <div className="space-y-3">
                {completedProjects.map((project) => (
                  <div
                    key={project.id}
                    className="flex items-center justify-between gap-4 rounded-xl border border-emerald-200/90 dark:border-emerald-800/60 bg-emerald-50/95 dark:bg-emerald-950/40 p-4 shadow-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-gray-900 dark:text-gray-100 leading-snug">
                        {project.title}
                      </p>
                      <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                        Deadline: {project.deadline}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs font-bold text-emerald-800 dark:text-emerald-400">
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