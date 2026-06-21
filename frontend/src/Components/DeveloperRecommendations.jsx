// src/components/DeveloperRecommendations.jsx
import React, { useState, useMemo } from 'react';

function normalizePersonLabel(s) {
  return String(s || '')
    .normalize('NFKC')
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ');
}

function dedupeRecommendationRows(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return rows || [];
  const seenIds = new Set();
  const seenEmails = new Set();
  const seenNames = new Set();
  const out = [];
  for (const r of rows) {
    const id = String(r.developer_id || '').trim();
    const em = normalizePersonLabel(r.email || '');
    const nm = normalizePersonLabel(r.name || '');
    if (id && seenIds.has(id)) continue;
    if (em && seenEmails.has(em)) continue;
    if (nm && seenNames.has(nm)) continue;
    if (id) seenIds.add(id);
    if (em) seenEmails.add(em);
    if (nm) seenNames.add(nm);
    out.push(r);
  }
  return out;
}

const DeveloperRecommendations = ({
  recommendations,
  onAssignTeam,
  project,
  recommendationRecordId,
  onApproveAiTeam,
  onRejectAiTeam,
}) => {
  const [selectedDevelopers, setSelectedDevelopers] = useState([]);
  const [isAssigning, setIsAssigning] = useState(false);

  const toggleDeveloperSelection = (developerId) => {
    if (selectedDevelopers.includes(developerId)) {
      setSelectedDevelopers(selectedDevelopers.filter(id => id !== developerId));
    } else {
      setSelectedDevelopers([...selectedDevelopers, developerId]);
    }
  };

  const handleAssignTeam = async () => {
    if (selectedDevelopers.length === 0) return;
    
    setIsAssigning(true);
    try {
      await onAssignTeam(selectedDevelopers);
      // Clear selection after assignment
      setSelectedDevelopers([]);
    } catch (err) {
      console.error('Error assigning team:', err);
    } finally {
      setIsAssigning(false);
    }
  };

  const recommendationRows = useMemo(
    () => dedupeRecommendationRows(recommendations?.recommendations),
    [recommendations]
  );

  if (!recommendations || !recommendations.recommendations) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center">
        <div className="text-gray-500">
          <div className="w-12 h-12 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p>Loading recommendations...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-blue-50 to-blue-100 border border-blue-200 rounded-xl p-6">
        <h4 className="text-lg font-semibold text-blue-900 mb-2">AI-Powered Recommendations</h4>
        <p className="text-blue-700">
          Based on required skills: <span className="font-semibold">
            {project?.require_skills?.join(', ') || 'No skills specified'}
          </span>
        </p>
        <p className="text-sm text-blue-600 mt-2">
          Scored {recommendations.total_developers_evaluated} eligible developers. The list is a balanced
          top {recommendations.recommendations?.length || 5} by role track (not the five highest raw scores).
          Approve puts that team on the project; starter tasks go to members with fewer active tasks first.
        </p>
        {recommendationRecordId && (onApproveAiTeam || onRejectAiTeam) && (
          <div className="mt-4 flex flex-wrap gap-2">
            {onApproveAiTeam && (
              <button
                type="button"
                onClick={() => onApproveAiTeam()}
                className="bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold py-2 px-4 rounded-lg"
              >
                Approve AI team
              </button>
            )}
            {onRejectAiTeam && (
              <button
                type="button"
                onClick={() => {
                  const r = window.prompt('Reason for rejecting this AI suggestion?');
                  if (r) onRejectAiTeam(r);
                }}
                className="bg-white border border-red-300 text-red-700 hover:bg-red-50 text-sm font-semibold py-2 px-4 rounded-lg"
              >
                Reject suggestion…
              </button>
            )}
            <span className="text-xs text-blue-800 self-center">
              Batch ID: {recommendationRecordId}
            </span>
          </div>
        )}
      </div>

      <div className="space-y-4">
        {recommendationRows.map((developer, idx) => (
          <div 
            key={developer.developer_id ? String(developer.developer_id) : `row-${idx}`} 
            className={`bg-white border rounded-xl p-6 transition-all ${
              selectedDevelopers.includes(developer.developer_id)
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-200 hover:border-blue-300'
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center space-x-3 mb-3">
                  <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center">
                    <span className="font-semibold text-blue-800">
                      {(developer.name || '?').split(' ').map(n => n[0]).join('')}
                    </span>
                  </div>
                  <div>
                    <h4 className="text-lg font-semibold text-gray-900">{developer.name}</h4>
                    <div className="flex space-x-2 mt-1">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        developer.availability ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                      }`}>
                        {developer.availability ? 'Available' : 'Unavailable'}
                      </span>
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                        Score: {developer.match_score}%
                      </span>
                      {developer.confidence_score != null && (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
                          Confidence: {(Number(developer.confidence_score) * 100).toFixed(1)}%
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                
                <div className="grid grid-cols-2 gap-4 text-sm mb-3">
                  <div>
                    <span className="text-gray-600">Workload:</span>
                    <span className="font-medium ml-2">{Number(developer.current_workload || 0)} tasks</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Skill Match:</span>
                    <span className="font-medium ml-2 text-green-600">
                      {Number.isFinite(Number(developer.skill_score))
                        ? Number(developer.skill_score).toFixed(1)
                        : Number.isFinite(Number(developer.match_score))
                          ? Number(developer.match_score).toFixed(1)
                          : '0.0'}
                      %
                    </span>
                  </div>
                </div>

                {developer.explanation && (
                  <p className="text-sm text-slate-700 mb-3 leading-snug border-l-4 border-blue-200 pl-3 bg-slate-50/80 py-2 rounded-r">
                    {developer.explanation}
                  </p>
                )}

                <div className="mb-3">
                  <span className="text-sm text-gray-600 mb-2 block">Matching Skills:</span>
                  <div className="flex flex-wrap gap-2">
                    {(developer.matching_skills || []).map(skill => (
                      <span 
                        key={skill}
                        className="inline-flex items-center px-3 py-1 rounded-lg text-sm font-medium bg-blue-100 text-blue-800 border border-blue-200"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>

                {developer.all_skills && developer.all_skills.length > developer.matching_skills.length && (
                  <div className="mt-2">
                    <span className="text-sm text-gray-600 mb-1 block">Other Skills:</span>
                    <div className="flex flex-wrap gap-1">
                      {developer.all_skills
                        .filter(skill => !developer.matching_skills.includes(skill))
                        .slice(0, 5)
                        .map(skill => (
                          <span 
                            key={skill}
                            className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700"
                          >
                            {skill}
                          </span>
                        ))}
                      {developer.all_skills.length - developer.matching_skills.length > 5 && (
                        <span className="text-xs text-gray-500">
                          +{developer.all_skills.length - developer.matching_skills.length - 5} more
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="ml-4 flex items-center">
                <input
                  type="checkbox"
                  checked={selectedDevelopers.includes(developer.developer_id)}
                  onChange={() => toggleDeveloperSelection(developer.developer_id)}
                  className="h-5 w-5 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  disabled={!developer.availability}
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex space-x-4 pt-4 border-t border-gray-200">
        <button 
          onClick={handleAssignTeam}
          disabled={selectedDevelopers.length === 0 || isAssigning}
          className={`flex-1 bg-blue-600 text-white font-semibold py-3 px-6 rounded-xl transition-colors ${
            selectedDevelopers.length === 0 || isAssigning
              ? 'opacity-50 cursor-not-allowed'
              : 'hover:bg-blue-700'
          }`}
        >
          {isAssigning ? (
            <span className="flex items-center justify-center">
              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
              Assigning...
            </span>
          ) : (
            `Assign Selected Team (${selectedDevelopers.length})`
          )}
        </button>
        
        <button
          type="button"
          onClick={() =>
            setSelectedDevelopers(
              recommendationRows.map((r) => r.developer_id).filter(Boolean)
            )
          }
          className="bg-gray-100 hover:bg-gray-200 text-gray-700 font-semibold py-3 px-6 rounded-xl transition-colors"
        >
          Select all ({recommendationRows.length})
        </button>
      </div>
    </div>
  );
};

export default DeveloperRecommendations;