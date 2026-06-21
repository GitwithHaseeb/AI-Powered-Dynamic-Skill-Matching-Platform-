import React, { useEffect, useMemo, useState } from 'react';
import { userService, getApiErrorMessage } from '../services/api.js';

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
  const nameKey = String(member?.full_name || member?.name || member?.username || '').trim().toLowerCase();
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

const DevelopersDirectory = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError('');
        const data = await userService.getDeveloperDirectory();
        if (cancelled) return;
        setRows(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!cancelled) setError(getApiErrorMessage(e, 'Failed to load developers'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const directoryRows = useMemo(() => {
    const devOnly = rows.filter((d) => String(d.role || 'developer').toLowerCase() === 'developer');
    const byKey = new Map();
    for (const d of devOnly) {
      const email = String(d.email || '').trim().toLowerCase();
      const key = email || String(d.id || '').trim();
      if (!key) continue;
      if (!byKey.has(key)) byKey.set(key, d);
    }
    return [...byKey.values()];
  }, [rows]);

  const filtered = useMemo(() => {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return directoryRows;
    return directoryRows.filter((d) => {
      const name = String(d.full_name || d.name || d.username || '').toLowerCase();
      const email = String(d.email || '').toLowerCase();
      const skills = (d.skills || [])
        .map((s) => (typeof s === 'string' ? s : s?.skill_name))
        .join(' ')
        .toLowerCase();
      return name.includes(q) || email.includes(q) || skills.includes(q);
    });
  }, [directoryRows, query]);

  const roleMixed = useMemo(
    () => filtered.map((d) => ({ ...d, role: displayRoleFor(d) })),
    [filtered]
  );

  return (
    <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold text-gray-900">All Developers</h2>
          <p className="text-gray-600 mt-1">Live directory from database</p>
        </div>
        <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
          {filtered.length} developers
        </span>
      </div>

      <div className="mb-5">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, email, or skills"
          className="w-full max-w-md px-4 py-2.5 border border-gray-300 rounded-lg bg-white text-gray-900"
        />
      </div>

      {error && <div className="mb-4 text-red-600 bg-red-50 border border-red-200 p-3 rounded-lg">{error}</div>}

      {loading ? (
        <p className="text-gray-600">Loading developers...</p>
      ) : roleMixed.length === 0 ? (
        <p className="text-gray-600">No developers found.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {roleMixed.map((d) => {
            const name = d.full_name || d.name || d.username || d.email || 'Developer';
            const skills = (d.skills || []).map((s) => (typeof s === 'string' ? s : s?.skill_name)).filter(Boolean);
            const role = d.role || displayRoleFor(d);
            return (
              <div key={d.id || d.email} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                <div className="flex justify-between items-start mb-3">
                  <h3 className="font-bold text-gray-900">{name}</h3>
                  <span className="px-2.5 py-1 text-xs rounded-full bg-green-50 text-green-700">Active</span>
                </div>
                <span
                  className={`inline-flex mb-1 px-2.5 py-1 rounded-md border text-xs font-semibold tracking-wide ${roleBadgeClass(
                    role
                  )}`}
                >
                  {role}
                </span>
                <p className="text-sm text-gray-600">Availability: {d.availability === false ? 'Part Time' : 'Full Time'}</p>
                <p className="text-sm text-gray-600">Contact: {d.contact || d.email || '—'}</p>
                <div className="mt-3">
                  <p className="text-sm text-gray-700 mb-1.5">Skills:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {skills.slice(0, 8).map((s) => (
                      <span key={`${d.id}-${s}`} className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-700">
                        {s}
                      </span>
                    ))}
                    {skills.length > 8 && (
                      <span className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-700">
                        +{skills.length - 8}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default DevelopersDirectory;
