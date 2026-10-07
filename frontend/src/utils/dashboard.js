import { normalizeRole } from './auth.js';

/** Directory of running projects (admin uses same read-only list as PM/dev). */
export function projectsListPath(role) {
  const r = normalizeRole(role);
  if (r === 'developer' || r === 'manager' || r === 'admin') return '/projects';
  return '/dashboard';
}

export function projectTeamMemberCount(p) {
  const team = p.assigned_team || p.final_team || [];
  const ids = Array.isArray(team)
    ? [...new Set(team.map((x) => (x != null ? String(x) : '')).filter(Boolean))]
    : [];
  const fromTeam = ids.length;
  const ts = typeof p.team_size === 'number' ? Math.max(0, Math.floor(p.team_size)) : 0;
  if (fromTeam > 0) return fromTeam;
  return ts;
}

export function formatProjectStatus(status) {
  if (!status) return '—';
  const map = {
    in_progress: 'In Progress',
    planning: 'Planning',
    completed: 'Completed',
    on_hold: 'On Hold',
  };
  return map[status] || String(status).replace(/_/g, ' ');
}

export function formatDeadline(d) {
  if (!d) return '—';
  try {
    const x = new Date(d);
    if (Number.isNaN(x.getTime())) return String(d).slice(0, 10);
    return x.toLocaleDateString();
  } catch {
    return '—';
  }
}

export function inferDeveloperType(skills = []) {
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

export function roleBadgeClass(role) {
  const r = String(role || '').toLowerCase();
  if (r.includes('full stack')) return 'bg-purple-600 text-white border-purple-500';
  if (r.includes('frontend')) return 'bg-blue-600 text-white border-blue-500';
  if (r.includes('backend')) return 'bg-emerald-600 text-white border-emerald-500';
  if (r.includes('ui')) return 'bg-pink-600 text-white border-pink-500';
  if (r.includes('tester')) return 'bg-amber-600 text-white border-amber-500';
  return 'bg-indigo-600 text-white border-indigo-500';
}

export function displayRoleFor(member) {
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
