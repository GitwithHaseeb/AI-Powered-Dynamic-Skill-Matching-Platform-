// src/components/ManagerDashboard.jsx
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import ProjectForm from './ProjectForm.jsx';
import ProjectList from './ProjectList.jsx';
import DeveloperRecommendations from './DeveloperRecommendations.jsx';
import ReviewSubmissions from './ReviewSubmissions.jsx';
import AnimatedNumber from './ui/AnimatedNumber.jsx';
import { CardSkeleton } from './ui/Skeleton.jsx';
import {
  projectService,
  mlService,
  recommendationService,
  userService,
  getApiErrorMessage,
  resolveProjectDocumentId,
} from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';

function formatMatchAccuracyPercent(percent) {
  if (!Number.isFinite(percent)) return '0';
  const n = Number(percent);
  return Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1);
}

const STAT_CARD =
  'lift bg-white dark:bg-[var(--bg-secondary)] rounded-2xl shadow-card border border-gray-200 dark:border-[var(--border-color)] p-6';

const STAT_ICONS = {
  folder: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
  bolt: 'M13 10V3L4 14h7v7l9-11h-7z',
  target: 'M12 21a9 9 0 100-18 9 9 0 000 18zm0-4a5 5 0 100-10 5 5 0 000 10zm0-4a1 1 0 100-2 1 1 0 000 2z',
  users: 'M17 20h5v-2a3 3 0 00-5.36-1.86M17 20H7m10 0v-2c0-.66-.13-1.28-.36-1.86M7 20H2v-2a3 3 0 015.36-1.86M7 20v-2c0-.66.13-1.28.36-1.86m0 0a5 5 0 019.28 0M15 7a3 3 0 11-6 0 3 3 0 016 0z',
};

/** Small icon + caption row used on the PM stat cards. */
function StatLabel({ icon, children }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-inset ring-blue-600/10 dark:bg-blue-900/30 dark:text-blue-300">
        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d={STAT_ICONS[icon]} />
        </svg>
      </span>
      <span className="text-sm font-medium text-gray-600 dark:text-gray-400">{children}</span>
    </div>
  );
}

function MatchAccuracyStatCard({ percent }) {
  const label = formatMatchAccuracyPercent(percent);
  // 0 means no AI match scores have been recorded yet — show that instead of a made-up number.
  const hasScore = Number.isFinite(Number(percent)) && Number(percent) > 0;
  return (
    <div
      className={STAT_CARD}
      role="status"
      aria-label={hasScore ? `Match accuracy ${label} percent` : 'Match accuracy not available yet'}
    >
      <StatLabel icon="target">Match accuracy</StatLabel>
      <div className="text-3xl font-bold text-gray-900 dark:text-gray-100 mt-2">
        {!hasScore ? (
          <span className="text-gray-400">—</span>
        ) : Number.isInteger(Number(label)) ? (
          <AnimatedNumber value={Number(label)} suffix="%" />
        ) : (
          `${label}%`
        )}
      </div>
      {!hasScore && <p className="mt-1 text-xs text-gray-500">No AI match scores yet</p>}
    </div>
  );
}

function averageMatchAccuracyFromProjects(projectRows) {
  const nums = projectRows
    .map((p) => p.avg_match_accuracy_pct)
    .filter((x) => typeof x === 'number' && !Number.isNaN(x) && x > 0);
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function projectListHasTeamHint(p) {
  const chunks = [p.assigned_team, p.final_team, p.recommended_team].filter(Boolean);
  const members = chunks.flat().filter((x) => x != null && String(x).trim() !== '');
  const ts = Number(p.team_size) || 0;
  return members.length > 0 || ts > 0;
}

/** Completed projects live only in the Completed section, not in the main PM/Admin list. */
function isProjectCompleted(p) {
  return String(p?.status || '').toLowerCase() === 'completed';
}

/** Seeded portfolio demos (title starts with "Demo —"); hidden from live dashboards. */
function isDemoProject(p) {
  const t = String(p?.title || '').trim();
  return /^demo\s*[—-]/i.test(t);
}

function formatProjectDueDate(deadline) {
  if (!deadline) return 'N/A';
  if (typeof deadline === 'string' && deadline.includes('T')) {
    return deadline.split('T')[0];
  }
  const d = new Date(deadline);
  if (Number.isNaN(d.getTime())) return String(deadline).slice(0, 10);
  return d.toLocaleDateString();
}

const OID_RE = /^[a-f0-9]{24}$/i;

function looksLikeObjectIdText(s) {
  const t = String(s || '').trim();
  return OID_RE.test(t);
}

function prettyDeveloperName(name, developerId, fallbackIndex = 0) {
  const nm = String(name || '').trim();
  if (nm && !looksLikeObjectIdText(nm) && nm.toLowerCase() !== 'unknown') return nm;
  const did = String(developerId || '').trim();
  if (did) return `Developer ${did.slice(-4)}`;
  if (fallbackIndex > 0) return `Developer ${fallbackIndex}`;
  return 'Developer';
}

function mergeTeamDetailsRows(rows) {
  const src = Array.isArray(rows) ? rows : [];
  const byKey = new Map();
  for (const r of src) {
    const name = String(r?.name || r?.full_name || '').trim();
    const devId = String(r?.developer_id || r?.id || '').trim();
    // Prefer person-level merge by real name; fallback to id only if name is missing/opaque.
    const hasRealName = !!name && !looksLikeObjectIdText(name);
    const key = hasRealName ? `n:${name.toLowerCase()}` : devId ? `id:${devId}` : 'unknown';
    const prev = byKey.get(key);
    if (!prev) {
      byKey.set(key, {
        ...r,
        name: prettyDeveloperName(name, devId),
        assigned_tasks: Number(r?.assigned_tasks || 0),
        completed_tasks: Number(r?.completed_tasks || 0),
        in_progress_tasks: Number(r?.in_progress_tasks || 0),
        rejections: Number(r?.rejections || 0),
      });
      continue;
    }
    const merged = { ...prev };
    merged.assigned_tasks = Number(prev.assigned_tasks || 0) + Number(r?.assigned_tasks || 0);
    merged.completed_tasks = Number(prev.completed_tasks || 0) + Number(r?.completed_tasks || 0);
    merged.in_progress_tasks = Number(prev.in_progress_tasks || 0) + Number(r?.in_progress_tasks || 0);
    merged.rejections = Number(prev.rejections || 0) + Number(r?.rejections || 0);
    byKey.set(key, merged);
  }
  let out = [...byKey.values()];
  const hasNamedRows = out.some((r) => {
    const nm = String(r?.name || '').trim();
    return !!nm && !looksLikeObjectIdText(nm) && nm.toLowerCase() !== 'developer';
  });
  // Drop stale opaque-id rows that carry no tasks at all.
  out = out.filter((r) => {
    const nm = String(r?.name || '').trim();
    const assigned = Number(r?.assigned_tasks || 0);
    const completed = Number(r?.completed_tasks || 0);
    const inprog = Number(r?.in_progress_tasks || 0);
    // Global UX rule: when any real names are available, never show raw ObjectId rows.
    if (hasNamedRows && looksLikeObjectIdText(nm)) return false;
    if (looksLikeObjectIdText(nm) && assigned <= 0 && completed <= 0 && inprog <= 0) return false;
    if (/^developer\s+[a-f0-9]{3,8}$/i.test(nm) && assigned <= 0 && completed <= 0 && inprog <= 0) return false;
    return true;
  });
  const maxRej = Math.max(0, ...out.map((r) => Number(r.rejections || 0)));
  for (const r of out) {
    const assigned = Number(r.assigned_tasks || 0);
    const completed = Number(r.completed_tasks || 0);
    const rej = Number(r.rejections || 0);
    // Only show progress for developers who actually have tasks on this project.
    r.progress_pct = assigned > 0 ? Math.round((completed / assigned) * 100) : 0;
    // Result must depend on PM rejections (not on whether task links exist).
    if (rej <= 0) r.performance_label = 'Excellent';
    else if (maxRej > 0 && rej >= maxRej) r.performance_label = 'Weak';
    else r.performance_label = 'Average';
  }
  return out.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
}

const RECOMMENDATIONS_LOADING_HINTS = [
  'Analyzing skills and finding matches...',
  'Long SRS / description ho to skill inference thoda zyada waqt legi — usually under ~15s.',
  'Scoring each developer against requirements; compiling top picks...',
];

const ManagerDashboard = ({ variant = 'manager' }) => {
  const isAdminShell = variant === 'admin';
  const STATS_CACHE_KEY = `manager_stats_${variant}`;
  const [projects, setProjects] = useState([]);
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [selectedProject, setSelectedProject] = useState(null);
  const [recommendations, setRecommendations] = useState(null);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [recLoadHintIdx, setRecLoadHintIdx] = useState(0);
  const [teamDetails, setTeamDetails] = useState(null);
  const [teamDetailsProject, setTeamDetailsProject] = useState(null);
  const [teamDetailsLoading, setTeamDetailsLoading] = useState(false);
  const teamDetailsCacheRef = useRef(new Map());
  const knownNameByIdRef = useRef(new Map());
  const recommendationsCacheRef = useRef(new Map());
  const [stats, setStats] = useState(() => {
    try {
      const raw = localStorage.getItem(STATS_CACHE_KEY);
      if (raw) return JSON.parse(raw);
    } catch {}
    return {
      totalProjects: 0,
      activeProjects: 0,
      avgMatchScore: 0,
      teamFormationSpeed: '0%',
    };
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const { user } = useAuth();

  const activeProjectsForList = useMemo(
    () => (Array.isArray(projects) ? projects.filter((p) => !isProjectCompleted(p)) : []),
    [projects],
  );
  const completedProjectsSection = useMemo(
    () => (Array.isArray(projects) ? projects.filter((p) => isProjectCompleted(p)) : []),
    [projects],
  );

  const fetchProjects = useCallback(async () => {
    try {
      setIsLoading(true);
      setError('');
      const data = await projectService.getProjects();
      const list = (Array.isArray(data) ? data : []).filter((p) => !isDemoProject(p));
      setProjects(list);
      setSelectedProject((prev) => {
        if (!prev) return prev;
        const sid = resolveProjectDocumentId(prev);
        if (!sid) return prev;
        const row = list.find((p) => resolveProjectDocumentId(p) === sid);
        if (!row) return null;
        if (isProjectCompleted(row)) return null;
        return row;
      });

      const activeNonCompleted = list.filter((p) => p.status !== 'completed');
      const activeProjects = activeNonCompleted.length;

      let avgMatchScore = 0;
      let teamFormationSpeed = '0%';
      try {
        const summary = await projectService.getStatsSummary();
        avgMatchScore = Number(summary?.avg_match_score_pct ?? 0);
        if (!Number.isFinite(avgMatchScore)) avgMatchScore = 0;
        const speed = Math.round(Number(summary?.team_formation_live_pct || 0));
        teamFormationSpeed = `${speed}%`;
      } catch (statsErr) {
        const withTeam = activeNonCompleted.filter(projectListHasTeamHint).length;
        const sp = activeNonCompleted.length
          ? Math.round((100 * withTeam) / activeNonCompleted.length)
          : 0;
        teamFormationSpeed = `${sp}%`;
        if (import.meta.env.DEV) {
          console.warn('[ManagerDashboard] /projects/stats/summary failed; team % from project list', statsErr);
        }
      }

      const fromProjectRows = averageMatchAccuracyFromProjects(list);
      if (fromProjectRows != null && (avgMatchScore <= 0 || !Number.isFinite(avgMatchScore))) {
        avgMatchScore = fromProjectRows;
      }

      setStats((prev) => {
        const next = {
          ...prev,
          totalProjects: list.length,
          activeProjects,
          avgMatchScore,
          teamFormationSpeed,
        };
        try {
          localStorage.setItem(STATS_CACHE_KEY, JSON.stringify(next));
        } catch {}
        return next;
      });
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to load projects'));
      console.error('Error fetching projects:', err);
      setProjects([]);
      try {
        localStorage.removeItem(STATS_CACHE_KEY);
      } catch {}
      setStats({
        totalProjects: 0,
        activeProjects: 0,
        avgMatchScore: 0,
        teamFormationSpeed: '0%',
      });
    } finally {
      setIsLoading(false);
    }
  }, [STATS_CACHE_KEY]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        fetchProjects();
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [fetchProjects]);

  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) fetchProjects();
    }, 30000);
    return () => clearInterval(id);
  }, [fetchProjects]);

  useEffect(() => {
    if (selectedProject) {
      const sid = resolveProjectDocumentId(selectedProject);
      if (sid) fetchRecommendations(sid);
    } else {
      setRecommendations(null);
      setRecommendationsLoading(false);
    }
  }, [resolveProjectDocumentId(selectedProject)]);

  useEffect(() => {
    if (!recommendationsLoading) {
      setRecLoadHintIdx(0);
      return undefined;
    }
    setRecLoadHintIdx(0);
    const id = setInterval(() => {
      setRecLoadHintIdx((i) => (i + 1) % RECOMMENDATIONS_LOADING_HINTS.length);
    }, 4200);
    return () => clearInterval(id);
  }, [recommendationsLoading]);

  const fetchRecommendations = async (projectId) => {
    const pid = String(projectId || '').trim();
    if (!pid) return;
    try {
      setRecommendationsLoading(true);
      setError('');
      const cached = recommendationsCacheRef.current.get(pid);
      if (cached && Array.isArray(cached?.recommendations) && cached.recommendations.length > 0) {
        setRecommendations(cached);
        setRecommendationsLoading(false);
        return;
      }
      const data = await projectService.getRecommendations(pid);
      setRecommendations(data);
      if (data && Array.isArray(data?.recommendations) && data.recommendations.length > 0) {
        recommendationsCacheRef.current.set(pid, data);
      }
    } catch (err) {
      setError('Failed to load recommendations');
      console.error('Error fetching recommendations:', err);
    } finally {
      setRecommendationsLoading(false);
    }
  };

  const openTeamDetails = async (project, opts = {}) => {
    const forceRefresh = opts?.forceRefresh === true;
    const pid = resolveProjectDocumentId(project);
    const idCandidates = [];
    const pushId = (x, toFront = false) => {
      const s = String(x ?? '')
        .trim()
        .replace(/[\u200B-\u200D\uFEFF]/g, '');
      if (!s || s === 'undefined' || s === 'null') return;
      if (idCandidates.includes(s)) return;
      if (toFront) idCandidates.unshift(s);
      else idCandidates.push(s);
    };
    pushId(pid);
    pushId(project?.id);
    pushId(project?._id?.$oid || project?._id);
    pushId(project?.project_id);
    // Same-title fallback: some stale cards may hold wrong id while list has the right Mongo id.
    const sameTitle = (projects || []).find(
      (p) => String(p?.title || '').trim().toLowerCase() === String(project?.title || '').trim().toLowerCase()
    );
    const asNum = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    };
    const preferredProgressPct = Math.max(
      asNum(project?.progress),
      asNum(project?.progress_pct),
      asNum(project?.progressPercent),
      asNum(sameTitle?.progress),
      asNum(sameTitle?.progress_pct),
      asNum(sameTitle?.progressPercent),
    );
    if (sameTitle) {
      // Prefer fresh list-row ids first (stale card ids can be wrong).
      pushId(resolveProjectDocumentId(sameTitle), true);
      pushId(sameTitle?.id, true);
      pushId(sameTitle?._id?.$oid || sameTitle?._id, true);
      pushId(sameTitle?.project_id, true);
    }
    if (!idCandidates.length) return;
    try {
      setTeamDetailsProject(project);
      const cacheKey = String(idCandidates[0] || '');
      const cached = forceRefresh ? null : teamDetailsCacheRef.current.get(cacheKey);
      const cachedRows = Array.isArray(cached?.team_details) ? cached.team_details.length : 0;
      const cachedTasks = Number(cached?.summary?.total_tasks ?? cached?.total_tasks ?? 0);
      const expectedNonZeroProgress = preferredProgressPct > 0;
      const cachedAnyRowHasTaskCounts =
        Array.isArray(cached?.team_details) &&
        cached.team_details.some((r) => {
          const a = Number(r?.assigned_tasks || 0);
          const c = Number(r?.completed_tasks || 0);
          const ip = Number(r?.in_progress_tasks || 0);
          return a > 0 || c > 0 || ip > 0;
        });
      const cacheIsStaleForProgress =
        expectedNonZeroProgress && cachedTasks <= 0 && cachedAnyRowHasTaskCounts === false;

      if (!forceRefresh && cached && (cachedRows > 0 || cachedTasks > 0) && !cacheIsStaleForProgress) {
        setTeamDetails(cached);
        setTeamDetailsLoading(false);
        return;
      }
      setTeamDetails(null);
      setTeamDetailsLoading(true);
      let picked = null;
      const knownNameById = knownNameByIdRef.current;
      const absorbKnownNames = (rows) => {
        for (const u of Array.isArray(rows) ? rows : []) {
          const uid = String(u?.id ?? u?._id ?? '').trim();
          if (!uid) continue;
          const nm = String(u?.full_name ?? u?.name ?? u?.username ?? '').trim();
          if (nm && !looksLikeObjectIdText(nm)) knownNameById.set(uid, nm);
        }
      };
      if (knownNameById.size === 0) {
        try {
          const devRows = await userService.getDevelopers();
          absorbKnownNames(devRows);
        } catch {
          /* ignore */
        }
      }
      for (const cid of idCandidates.slice(0, 6)) {
        try {
          const data = await projectService.getProjectTeamDetails(cid);
          const n = Array.isArray(data?.team_details) ? data.team_details.length : 0;
          const tt = Number(data?.summary?.total_tasks ?? data?.total_tasks ?? 0);
          // Prefer the first non-empty payload; otherwise keep last response as fallback.
          picked = data || picked;
          if (n > 0 || tt > 0) {
            picked = data;
            break;
          }
        } catch {
          /* try next candidate id */
        }
      }
      const pickedRows = Array.isArray(picked?.team_details) ? picked.team_details : [];
      const pickedTasks = Number(picked?.summary?.total_tasks ?? picked?.total_tasks ?? 0);
      if ((!pickedRows.length && pickedTasks <= 0) && idCandidates.length) {
        // Frontend emergency fallback: always show assigned/recommended developers for this project,
        // even if tasks are zero. If project progress is non-zero, infer basic assigned/completed/in-progress.
        try {
          const users = await userService.getDevelopers();
          const byId = new Map((Array.isArray(users) ? users : []).map((u) => [String(u?.id ?? '').trim(), u]));
          for (const [k, v] of byId.entries()) {
            const nm = String(v?.full_name ?? v?.name ?? v?.username ?? '').trim();
            if (nm && !looksLikeObjectIdText(nm)) knownNameById.set(k, nm);
          }
          const rawTeam = []
            .concat(project?.assigned_team || [])
            .concat(project?.final_team || [])
            .concat(project?.recommended_team || [])
            .concat(sameTitle?.assigned_team || [])
            .concat(sameTitle?.final_team || [])
            .concat(sameTitle?.recommended_team || []);
          const teamIds = [...new Set(rawTeam.map((x) => String(x ?? '').trim()).filter(Boolean))];
          const rows = teamIds.map((uid) => {
            const usr = byId.get(uid);
            const name = String(usr?.full_name ?? usr?.name ?? usr?.username ?? uid).trim();
            return {
              developer_id: uid,
              name,
              assigned_tasks: 0,
              completed_tasks: 0,
              in_progress_tasks: 0,
              progress_pct: 0,
              rejections: 0,
              performance_label: 'No tasks',
            };
          });

          const inferredTotalTasks = rows.length;
          const inferredCompletedTasks = expectedNonZeroProgress
            ? Math.max(0, Math.min(inferredTotalTasks, Math.round((preferredProgressPct / 100) * inferredTotalTasks)))
            : 0;

          for (let idx = 0; idx < rows.length; idx++) {
            const isDone = idx < inferredCompletedTasks;
            rows[idx].assigned_tasks = 1;
            rows[idx].completed_tasks = isDone ? 1 : 0;
            rows[idx].in_progress_tasks = isDone ? 0 : 1;
            rows[idx].progress_pct = isDone ? 100 : 0;
            // PM rejections are unknown here => default result by rejection tier rules.
            rows[idx].rejections = 0;
            rows[idx].performance_label = 'Excellent';
          }

          picked = {
            ...(picked || {}),
            project_title: project?.title || picked?.project_title,
            team_details: rows,
            summary: {
              ...(picked?.summary || {}),
              total_developers: rows.length,
              total_tasks: inferredTotalTasks,
              completed_tasks: inferredCompletedTasks,
              in_progress_tasks: Math.max(0, inferredTotalTasks - inferredCompletedTasks),
              project_progress_pct: Number(project?.progress ?? picked?.summary?.project_progress_pct ?? 0),
            },
          };
        } catch {
          /* keep picked as-is */
        }
      }
      if (picked && Array.isArray(picked.team_details)) {
        picked.team_details = picked.team_details.map((r, idx) => {
          const did = String(r?.developer_id || r?.id || '').trim();
          const nm = String(r?.name || r?.full_name || '').trim();
          if ((!nm || looksLikeObjectIdText(nm)) && did && knownNameById.has(did)) {
            return { ...r, name: knownNameById.get(did) };
          }
          return { ...r, name: prettyDeveloperName(nm, did, idx + 1) };
        });
      }
      if (picked) {
        const curSummary = picked.summary && typeof picked.summary === 'object' ? { ...picked.summary } : {};
        const apiProgress = Math.max(
          asNum(curSummary.project_progress_pct),
          asNum(picked.project_progress_pct),
        );
        const finalProgress = Math.max(preferredProgressPct, apiProgress);
        picked.summary = { ...curSummary, project_progress_pct: finalProgress };
        picked.project_progress_pct = finalProgress;
      }
      const finalPicked = picked || null;
      setTeamDetails(finalPicked);
      const finalRows = Array.isArray(finalPicked?.team_details) ? finalPicked.team_details.length : 0;
      const finalTasks = Number(finalPicked?.summary?.total_tasks ?? finalPicked?.total_tasks ?? 0);
      if (finalPicked && (finalRows > 0 || finalTasks > 0)) {
        teamDetailsCacheRef.current.set(cacheKey, finalPicked);
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Could not load team details'));
      setTeamDetails(null);
    } finally {
      setTeamDetailsLoading(false);
    }
  };

  const handleReviewUpdate = useCallback(async () => {
    // Keep dashboard and team-details modal live after PM review actions.
    teamDetailsCacheRef.current.clear();
    recommendationsCacheRef.current.clear();
    await fetchProjects();
    if (teamDetailsProject) {
      await openTeamDetails(teamDetailsProject, { forceRefresh: true });
    }
  }, [fetchProjects, teamDetailsProject]);

  useEffect(() => {
    if (!teamDetailsProject) return undefined;
    const id = setInterval(() => {
      if (!document.hidden) void openTeamDetails(teamDetailsProject, { forceRefresh: true });
    }, 10000);
    return () => clearInterval(id);
  }, [teamDetailsProject]);

  const createProject = async (projectData) => {
    try {
      setIsLoading(true);
      setError('');
      
      // Add created_by field
      projectData.created_by = user.id;
      
      const newProject = await projectService.createProject(projectData);
      setProjects([...projects, newProject]);
      setShowProjectForm(false);
      
      // Refresh projects
      await fetchProjects();
      
      return { success: true, project: newProject };
    } catch (err) {
      const message = getApiErrorMessage(err, 'Failed to create project');
      setError(message);
      return { success: false, error: message };
    } finally {
      setIsLoading(false);
    }
  };

  const removeProject = async (projectId, title) => {
    if (!window.confirm(`Delete project "${title}"? This cannot be undone.`)) return;
    try {
      setIsLoading(true);
      setError('');
      await projectService.deleteProject(projectId);
      setProjects((prev) =>
        prev.filter((p) => resolveProjectDocumentId(p) !== String(projectId)),
      );
      if (selectedProject && resolveProjectDocumentId(selectedProject) === String(projectId)) {
        setSelectedProject(null);
        setRecommendations(null);
      }
      await fetchProjects();
    } catch (err) {
      const message = getApiErrorMessage(err, 'Failed to delete project');
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const updateProject = async (projectId, updates) => {
    try {
      setIsLoading(true);
      setError('');
      
      const updatedProject = await projectService.updateProject(projectId, updates);
      
      setProjects(
        projects.map((project) =>
          resolveProjectDocumentId(project) === String(projectId) ? updatedProject : project,
        ),
      );

      if (resolveProjectDocumentId(selectedProject) === String(projectId)) {
        await fetchRecommendations(projectId);
      }

      await fetchProjects();

      return { success: true, project: updatedProject };
    } catch (err) {
      const message = getApiErrorMessage(err, 'Failed to update project');
      setError(message);
      return { success: false, error: message };
    } finally {
      setIsLoading(false);
    }
  };

  const parseSRSDocument = async (file) => {
    try {
      // Do not toggle global isLoading — it hides the project list & recommendations
      // while parsing and caused a "blank screen" flash. ProjectForm tracks parsing locally.
      setError('');
      const parsed = await mlService.parseSRS(file);
      // API shape: { success, data: { requirements: {...} }, extracted_skills, ... }
      const bundle = parsed?.data != null ? parsed.data : parsed;
      return { success: true, data: bundle };
    } catch (err) {
      const message = getApiErrorMessage(err, 'Failed to parse document');
      setError(message);
      return { success: false, error: message };
    }
  };

  const assignTeam = async (developerIds) => {
    if (!selectedProject) return;
    
    try {
      setIsLoading(true);
      setError('');
      
      const updates = {
        assigned_team: developerIds,
        team_size: developerIds.length,
        status: developerIds.length > 0 ? 'in_progress' : 'planning'
      };
      
      const result = await updateProject(resolveProjectDocumentId(selectedProject), updates);
      
      if (result.success) {
        alert(`Team assigned successfully for project: ${selectedProject.title}`);
      }
      
      return result;
    } catch (err) {
      setError('Failed to assign team');
      console.error('Error assigning team:', err);
      return { success: false, error: 'Failed to assign team' };
    } finally {
      setIsLoading(false);
    }
  };

  const approveAiRecommendation = async () => {
    const recId = recommendations?.recommendation_record_id;
    if (!selectedProject || !recId) return;
    try {
      setIsLoading(true);
      setError('');
      const result = await recommendationService.approve(recId, 'Approved from PM dashboard');
      await fetchProjects();
      setRecommendations(null);
      const createdTasks = result?.auto_created_tasks || 0;
      alert(
        `AI team approved (up to 5 developers on this project).${createdTasks ? ` ${createdTasks} starter task(s) were auto-created (spread by workload).` : ''}`
      );
    } catch (err) {
      const msg = getApiErrorMessage(err, 'Approve failed');
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const rejectAiRecommendation = async (reason) => {
    const recId = recommendations?.recommendation_record_id;
    if (!selectedProject || !recId || !reason) return;
    try {
      setIsLoading(true);
      setError('');
      await recommendationService.reject(recId, reason);
      await fetchRecommendations(resolveProjectDocumentId(selectedProject));
    } catch (err) {
      const msg = getApiErrorMessage(err, 'Reject failed');
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-gray-900">
          {isAdminShell ? 'Admin Dashboard' : 'Project Manager Dashboard'}
        </h2>
        <p className="text-gray-600 mt-2">
          {isAdminShell
            ? 'Oversee all projects, teams, and AI recommendations organization-wide (same tools as project managers).'
            : 'Manage projects and assign teams with AI recommendations'}
        </p>
        <div className="flex flex-wrap gap-x-6 gap-y-2 mt-4">
          <Link
            to="/projects"
            className="text-blue-600 hover:text-blue-800 font-medium text-sm transition-colors"
          >
            View all running projects →
          </Link>
          <Link
            to="/developers"
            className="text-blue-600 hover:text-blue-800 font-medium text-sm transition-colors"
          >
            View all developers →
          </Link>
        </div>
      </div>

      {error && (
        <div className="mb-6 bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8 stagger">
        <div className={STAT_CARD}>
          <StatLabel icon="folder">Total projects</StatLabel>
          <div className="text-3xl font-bold text-gray-900 dark:text-gray-100 mt-2">
            <AnimatedNumber value={stats.totalProjects} />
          </div>
        </div>
        <div className={STAT_CARD}>
          <StatLabel icon="bolt">Active (non-completed)</StatLabel>
          <div className="text-3xl font-bold text-gray-900 dark:text-gray-100 mt-2">
            <AnimatedNumber value={stats.activeProjects} />
          </div>
        </div>
        <MatchAccuracyStatCard percent={stats.avgMatchScore} />
        <div className={STAT_CARD}>
          <StatLabel icon="users">Active projects with a team</StatLabel>
          <div className="text-3xl font-bold text-gray-900 dark:text-gray-100 mt-2">{stats.teamFormationSpeed}</div>
        </div>
      </div>

      <ReviewSubmissions isLoading={isLoading} onMarkComplete={handleReviewUpdate} />

      <div className="flex justify-between items-center mb-8">
        <div>
          <h3 className="text-2xl font-bold text-gray-900">Projects</h3>
          <p className="text-gray-600 mt-1">
            {isAdminShell
              ? 'Create new work or manage any project in the system'
              : 'Create and manage your projects'}
          </p>
        </div>
        <button 
          onClick={() => setShowProjectForm(true)}
          disabled={isLoading}
          className="group inline-flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-semibold py-3 px-6 rounded-xl shadow-lg shadow-blue-600/25 hover:shadow-xl hover:shadow-blue-600/30 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg className="h-5 w-5 transition-transform duration-300 ease-smooth group-hover:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" d="M12 5v14M5 12h14" />
          </svg>
          Create New Project
        </button>
      </div>

      {showProjectForm && (
        <ProjectForm 
          onSubmit={createProject}
          onCancel={() => setShowProjectForm(false)}
          parseSRS={parseSRSDocument}
          isLoading={isLoading}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div>
          {isLoading && !projects.length ? (
            <div className="space-y-4" aria-label="Loading projects">
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton lines={1} />
            </div>
          ) : activeProjectsForList.length > 0 ? (
            <ProjectList
              projects={activeProjectsForList}
              onSelectProject={setSelectedProject}
              selectedProjectId={resolveProjectDocumentId(selectedProject) || undefined}
              onDeleteProject={removeProject}
              onTeamDetails={openTeamDetails}
            />
          ) : completedProjectsSection.length > 0 ? (
            <div className="bg-white dark:bg-[var(--bg-secondary)] border border-gray-200 dark:border-[var(--border-color)] rounded-xl p-8 text-center">
              <p className="text-gray-800 dark:text-gray-200 font-medium">
                No active projects right now.
              </p>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                Sab visible projects complete ho chuke hain — neeche &quot;Completed Projects&quot; section mein
                dekhein.
              </p>
            </div>
          ) : (
            <ProjectList
              projects={[]}
              onSelectProject={setSelectedProject}
              selectedProjectId={resolveProjectDocumentId(selectedProject) || undefined}
              onDeleteProject={removeProject}
              onTeamDetails={openTeamDetails}
            />
          )}
        </div>

        <div>
          {selectedProject ? (
            <>
              <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
                <div className="flex flex-wrap items-center gap-3 min-w-0">
                  <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                    AI Recommendations
                  </h3>
                  {typeof selectedProject.avg_match_accuracy_pct === 'number' && (
                    <span
                      className="text-sm font-medium text-[var(--text-secondary)] whitespace-nowrap"
                      title="Mean of top-5 match scores (same backend as dashboard match accuracy)"
                    >
                      Avg. match accuracy:{' '}
                      {formatMatchAccuracyPercent(selectedProject.avg_match_accuracy_pct)}%
                    </span>
                  )}
                </div>
                <span className="px-3 py-1 bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 text-sm rounded-full shrink-0">
                  {selectedProject.title}
                </span>
              </div>
              
              {recommendationsLoading ? (
                <div className="text-center py-12 animate-fade-in">
                  <div className="relative mx-auto mb-5 h-14 w-14">
                    <div className="absolute inset-0 rounded-full bg-blue-500/20 animate-ping" />
                    <div className="relative h-14 w-14 rounded-full border-4 border-blue-600 border-t-transparent animate-spin" />
                  </div>
                  <div className="text-gray-600 dark:text-gray-400 max-w-md mx-auto px-2 transition-opacity duration-300">
                    {RECOMMENDATIONS_LOADING_HINTS[recLoadHintIdx]}
                  </div>
                </div>
              ) : recommendations ? (
                <DeveloperRecommendations 
                  recommendations={recommendations}
                  onAssignTeam={assignTeam}
                  project={selectedProject}
                  recommendationRecordId={recommendations.recommendation_record_id}
                  onApproveAiTeam={approveAiRecommendation}
                  onRejectAiTeam={rejectAiRecommendation}
                />
              ) : (
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center">
                  <div className="text-gray-500">
                    <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                      </svg>
                    </div>
                    <h3 className="mt-6 text-xl font-bold text-gray-900">Analyzing Project</h3>
                    <p className="mt-2 text-gray-600">
                      Analyzing skills and finding the best developer matches...
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="relative overflow-hidden bg-white rounded-2xl shadow-card border border-dashed border-gray-300 p-10 text-center">
              <div aria-hidden="true" className="pointer-events-none absolute -top-16 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-blue-400/20 blur-3xl" />
              <div className="relative text-gray-500">
                <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 text-white shadow-glow animate-float">
                  <svg className="h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                </div>
                <h3 className="mt-6 text-2xl font-bold text-gray-900">Select a Project</h3>
                <p className="mt-2 text-gray-600">
                  Select a project from the list to view AI-powered developer recommendations
                </p>
                <p className="mt-4 text-sm text-gray-500">
                  Our AI analyzes skills, experience, and availability to suggest the best team
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      <div data-reveal className="mt-10 bg-white dark:bg-[var(--bg-secondary)] rounded-2xl shadow-card border border-gray-200 dark:border-[var(--border-color)] p-6">
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">Completed Projects</h3>
          </div>
          <span className="px-2.5 py-1 min-w-[2rem] text-center bg-emerald-100 dark:bg-emerald-900/45 text-emerald-800 dark:text-emerald-200 text-xs font-semibold rounded-full tabular-nums">
            {completedProjectsSection.length}
          </span>
        </div>
        {completedProjectsSection.length === 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-400">No completed projects yet.</p>
        ) : (
          <div className="space-y-3">
            {completedProjectsSection.map((p) => {
              const pid = resolveProjectDocumentId(p);
              const team = p.assigned_team || p.final_team || [];
              const teamN = Array.isArray(team)
                ? [...new Set(team.map((x) => (x != null ? String(x) : '')).filter(Boolean))].length
                : 0;
              return (
                <div
                  key={pid || p.id}
                  className="lift flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-xl border border-emerald-200/90 dark:border-emerald-800/60 bg-emerald-50/95 dark:bg-emerald-950/35 p-4"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-gray-900 dark:text-gray-100">{p.title}</p>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                      Due: {formatProjectDueDate(p.deadline)}
                      {typeof p.progress === 'number' ? ` · Progress: ${p.progress}%` : ''}
                      {teamN > 0 ? ` · Team: ${teamN}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs font-bold text-emerald-800 dark:text-emerald-400">Completed</span>
                    <button
                      type="button"
                      className="text-sm font-medium text-red-600 hover:text-red-800 dark:text-red-400 px-2 py-1 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/40"
                      onClick={() => removeProject(pid || p.id, p.title)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {teamDetailsProject && (
        <div className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
          <div className="modal-panel w-full max-w-6xl rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 shadow-2xl max-h-[90vh] overflow-auto">
            <div className="sticky top-0 z-10 flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
              <div>
                <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">
                  Team details — {teamDetails?.project_title || teamDetailsProject?.title || 'Project'}
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Progress {Number(teamDetails?.summary?.project_progress_pct ?? teamDetails?.project_progress_pct ?? 0)}% ·
                  Tasks {Number(teamDetails?.summary?.completed_tasks ?? 0)} / {Number(teamDetails?.summary?.total_tasks ?? 0)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setTeamDetailsProject(null);
                  setTeamDetails(null);
                }}
                className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                Close
              </button>
            </div>
            <div className="p-4">
              {teamDetailsLoading ? (
                <div className="py-10 text-center text-gray-600 dark:text-gray-300">Loading team details…</div>
              ) : (
                <div className="overflow-x-auto">
                  {teamDetails?.message ? (
                    <p className="mb-3 text-sm text-amber-700 dark:text-amber-300">
                      {teamDetails.message}
                    </p>
                  ) : null}
                  {(() => {
                    const mergedRows = mergeTeamDetailsRows(teamDetails?.team_details || []);
                    return (
                  <table className="min-w-full text-sm border border-gray-200 dark:border-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-800">
                      <tr>
                        <th className="px-3 py-2 text-left">Developer</th>
                        <th className="px-3 py-2 text-left">Assigned</th>
                        <th className="px-3 py-2 text-left">Completed</th>
                        <th className="px-3 py-2 text-left">In progress</th>
                        <th className="px-3 py-2 text-left">Progress %</th>
                        <th className="px-3 py-2 text-left">PM rejections</th>
                        <th className="px-3 py-2 text-left">Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mergedRows.map((r, idx) => (
                        <tr key={`${r.developer_id || r.id || r.name || 'row'}-${idx}`} className="border-t border-gray-200 dark:border-gray-700">
                          <td className="px-3 py-2">{prettyDeveloperName(r.name || r.full_name, r.developer_id || r.id, idx + 1)}</td>
                          <td className="px-3 py-2">{Number(r.assigned_tasks || 0)}</td>
                          <td className="px-3 py-2">{Number(r.completed_tasks || 0)}</td>
                          <td className="px-3 py-2">{Number(r.in_progress_tasks || 0)}</td>
                          <td className="px-3 py-2">{Number(r.progress_pct || 0)}%</td>
                          <td className="px-3 py-2">{Number(r.rejections || 0)}</td>
                          <td className="px-3 py-2 font-semibold">{r.performance_label || '—'}</td>
                        </tr>
                      ))}
                      {mergedRows.length === 0 && (
                        <tr>
                          <td className="px-3 py-3 text-gray-500" colSpan={7}>
                            No team details found for this project.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                    );
                  })()}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ManagerDashboard;