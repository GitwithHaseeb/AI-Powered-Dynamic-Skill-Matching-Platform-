import React, { useEffect, useMemo, useState } from 'react';
import { projectService, getApiErrorMessage } from '../services/api.js';

function formatStatus(status) {
  const raw = String(status || '').toLowerCase();
  if (raw === 'in_progress') return 'In Progress';
  if (raw === 'planning') return 'Planning';
  if (raw === 'on_hold') return 'On Hold';
  if (raw === 'completed') return 'Completed';
  return 'Unknown';
}

function formatDeadline(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString();
}

const ProjectsDirectory = () => {
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
        const data = await projectService.getRunningProjectsDirectory({ limit: 200 });
        if (cancelled) return;
        const projects = Array.isArray(data) ? data : [];
        setRows(projects);
      } catch (e) {
        if (!cancelled) setError(getApiErrorMessage(e, 'Failed to load projects'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((p) => {
      const title = String(p.title || '').toLowerCase();
      const description = String(p.description || '').toLowerCase();
      const department = String(p.department || '').toLowerCase();
      const skills = (p.require_skills || []).join(' ').toLowerCase();
      return title.includes(q) || description.includes(q) || department.includes(q) || skills.includes(q);
    });
  }, [rows, query]);

  return (
    <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-3xl font-bold text-gray-900">All Running Projects</h2>
          <p className="text-gray-600 mt-1">Live project list from database</p>
        </div>
        <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
          {filtered.length} projects
        </span>
      </div>

      <div className="mb-5">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title, description, department, or skills"
          className="w-full max-w-xl px-4 py-2.5 border border-gray-300 rounded-lg bg-white text-gray-900"
        />
      </div>

      {error && <div className="mb-4 text-red-600 bg-red-50 border border-red-200 p-3 rounded-lg">{error}</div>}

      {loading ? (
        <p className="text-gray-600">Loading projects...</p>
      ) : filtered.length === 0 ? (
        <p className="text-gray-600">No running projects found.</p>
      ) : (
        <div className="space-y-4">
          {filtered.map((p) => (
            <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <div className="flex justify-between items-start gap-4 mb-3">
                <div>
                  <h3 className="font-bold text-gray-900">{p.title}</h3>
                  <p className="text-sm text-gray-600 mt-1">{p.description || 'No description'}</p>
                  {p.created_by_name && (
                    <p className="text-xs text-gray-500 mt-2">Created by: {p.created_by_name}</p>
                  )}
                </div>
                <span className="px-3 py-1 text-xs rounded-full bg-blue-100 text-blue-800 whitespace-nowrap">
                  {formatStatus(p.status)}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-6 text-sm mb-3">
                <div>
                  <span className="text-gray-500">Progress:</span>{' '}
                  <span className="font-semibold text-gray-900">{typeof p.progress === 'number' ? p.progress : 0}%</span>
                </div>
                {typeof p.avg_match_accuracy_pct === 'number' && (
                  <div>
                    <span className="text-gray-500">Avg. match accuracy:</span>{' '}
                    <span className="font-semibold text-sky-700 dark:text-sky-400">
                      {p.avg_match_accuracy_pct}%
                    </span>
                  </div>
                )}
                <div>
                  <span className="text-gray-500">Team Size:</span>{' '}
                  <span className="font-semibold text-gray-900">{p.team_size || (p.assigned_team || []).length || 0}</span>
                </div>
                <div>
                  <span className="text-gray-500">Type:</span>{' '}
                  <span className="font-semibold text-gray-900">{p.department || '—'}</span>
                </div>
                <div>
                  <span className="text-gray-500">Due:</span>{' '}
                  <span className="font-semibold text-gray-900">{formatDeadline(p.deadline)}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {(p.require_skills || []).slice(0, 8).map((skill) => (
                  <span key={`${p.id}-${skill}`} className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-700">
                    {skill}
                  </span>
                ))}
                {(p.require_skills || []).length > 8 && (
                  <span className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-700">
                    +{p.require_skills.length - 8}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ProjectsDirectory;
