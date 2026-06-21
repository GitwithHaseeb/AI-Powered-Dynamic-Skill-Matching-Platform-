// src/components/ProjectList.jsx
import React from 'react';
import { resolveProjectDocumentId } from '../services/api';

/** Match dashboard logic: prefer roster ids, else stored team_size. */
function teamMemberCount(p) {
  const team = p.assigned_team || p.final_team || [];
  const ids = Array.isArray(team)
    ? [...new Set(team.map((x) => (x != null ? String(x) : '')).filter(Boolean))]
    : [];
  // Show only real member ids; numeric team_size alone can be a planning estimate (not assigned people).
  return ids.length;
}

const ProjectList = ({ projects, onSelectProject, selectedProjectId, onDeleteProject, onTeamDetails }) => {
  const formatDueDate = (deadline) => {
    if (!deadline) return 'N/A';
    // Keep exact date selected in form (avoid timezone shifts).
    if (typeof deadline === 'string' && deadline.includes('T')) {
      return deadline.split('T')[0];
    }
    const d = new Date(deadline);
    if (Number.isNaN(d.getTime())) return String(deadline);
    return d.toLocaleDateString();
  };

  const getStatusColor = (status) => {
    switch(status) {
      case 'completed': return 'bg-green-100 text-green-800';
      case 'in_progress': return 'bg-blue-100 text-blue-800';
      case 'planning': return 'bg-yellow-100 text-yellow-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusText = (status) => {
    switch(status) {
      case 'completed': return 'Completed';
      case 'in_progress': return 'In Progress';
      case 'planning': return 'Planning';
      default: return 'Draft';
    }
  };

  return (
    <div className="space-y-4">
      {projects.map((project, idx) => {
        const pid = resolveProjectDocumentId(project);
        const teamSize = teamMemberCount(project);
        const progressPct =
          typeof project.progress === 'number' ? project.progress : 0;
        return (
        <div 
          key={pid || `project-${idx}`}
          className={`bg-white border rounded-xl p-6 cursor-pointer hover:shadow-lg transition-all duration-200 hover:border-blue-300 ${
            selectedProjectId === pid ? 'border-blue-400 ring-2 ring-blue-100' : 'border-gray-200'
          }`}
          onClick={() => onSelectProject(project)}
        >
          <div className="flex justify-between items-start">
            <div className="flex-1">
              <div className="flex items-start justify-between mb-3 gap-3">
                <div className="min-w-0">
                  <h4 className="text-lg font-semibold text-gray-900">{project.title}</h4>
                  <p className="text-gray-600 mt-1">{project.description}</p>
                </div>
                <div className="text-right shrink-0 flex flex-col items-end gap-2">
                  {onDeleteProject && (
                    <button
                      type="button"
                      className="text-sm font-medium text-red-600 hover:text-red-800 px-2 py-1 rounded-lg hover:bg-red-50"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteProject(pid || project.id, project.title);
                      }}
                    >
                      Delete
                    </button>
                  )}
                  <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(project.status)}`}>
                    {getStatusText(project.status)}
                  </span>
                  <p className="text-sm text-gray-500 mt-1">Due: {formatDueDate(project.deadline)}</p>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap gap-2">
                  {(project.require_skills || []).map(skill => (
                    <span 
                      key={skill}
                      className="inline-flex items-center px-3 py-1 rounded-lg text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
                
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    <span className="font-medium text-gray-800 dark:text-gray-200">Progress:</span>{' '}
                    {progressPct}%
                  </div>
                  {typeof project.avg_match_accuracy_pct === 'number' && (
                    <div className="text-sm text-gray-600 dark:text-gray-400">
                      <span className="font-medium text-sky-700 dark:text-sky-400">
                        Avg. match accuracy:
                      </span>{' '}
                      {project.avg_match_accuracy_pct}%
                    </div>
                  )}
                  <button
                    type="button"
                    className="text-sm text-blue-700 dark:text-blue-300 hover:underline"
                    aria-label={`Team size ${teamSize}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (typeof onTeamDetails === 'function') onTeamDetails(project);
                    }}
                  >
                    <span className="font-medium">Team:</span> {teamSize} member{teamSize === 1 ? '' : 's'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      );
      })}
      
      {projects.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
          <div className="text-gray-500">
            <svg className="mx-auto h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <h3 className="mt-6 text-2xl font-bold text-gray-900">No projects yet</h3>
            <p className="mt-2 text-gray-600">
              Get started by creating your first project to use AI-powered skill matching
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectList;