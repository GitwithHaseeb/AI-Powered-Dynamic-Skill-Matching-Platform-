// src/components/SkillProfile.jsx — developers: add new skills only; levels from task completion
import React, { useState, useEffect } from 'react';

const norm = (s) => String(s || '').trim().toLowerCase();

const SkillProfile = ({ showForm, onCloseForm, onOpenForm, onUpdateSkills, userSkills, isLoading }) => {
  const [pendingAdd, setPendingAdd] = useState([]);
  const [newSkill, setNewSkill] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (showForm) {
      setPendingAdd([]);
      setNewSkill('');
      setError('');
    }
  }, [showForm]);

  useEffect(() => {
    if (!showForm) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onCloseForm?.();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showForm, onCloseForm]);

  const openModal = () => {
    if (onOpenForm) onOpenForm();
  };

  const addPendingSkill = () => {
    const raw = newSkill.trim();
    if (!raw) return;
    const key = norm(raw);
    const inProfile = (userSkills || []).some((s) => norm(s.skill_name) === key);
    const inPending = pendingAdd.some((s) => norm(s) === key);
    if (inProfile || inPending) {
      setError(
        inProfile
          ? 'This skill is already on your profile.'
          : 'You already added this skill to the list below.'
      );
      return;
    }
    setError('');
    setPendingAdd((p) => [...p, raw]);
    setNewSkill('');
  };

  const removePending = (name) => {
    setPendingAdd((p) => p.filter((x) => x !== name));
  };

  const handleSave = async () => {
    try {
      setError('');
      if (pendingAdd.length === 0) {
        setError('Add at least one new skill name, or cancel.');
        return;
      }
      const payload = pendingAdd.map((name) => ({ skill_name: name }));
      const result = await onUpdateSkills(payload);
      if (result.success) {
        onCloseForm();
      } else {
        setError(result.error);
      }
    } catch (err) {
      setError('Failed to save skills');
      console.error('Error saving skills:', err);
    }
  };

  const ProficiencyStars = ({ level, editable = false, onChange }) => {
    return (
      <div className="flex space-x-1" role={editable ? undefined : 'img'} aria-label={`Level ${level} of 5`}>
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={editable ? () => onChange(star) : undefined}
            className={`${
              star <= level ? 'text-yellow-400' : 'text-gray-300'
            } ${editable ? 'cursor-pointer hover:text-yellow-300' : 'cursor-default'} text-lg`}
            disabled={!editable || isLoading}
          >
            ★
          </button>
        ))}
      </div>
    );
  };

  if (showForm) {
    return (
      <div
        className="modal-backdrop fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50"
        onMouseDown={() => onCloseForm?.()}
      >
        <div
          className="modal-panel bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-2">Add skills</h3>
            <p className="text-sm text-gray-600 mb-6">
              You can add <strong>new</strong> skill names only. Star levels are read-only here and go up when your
              manager marks tasks complete (using <code className="text-xs bg-gray-100 px-1 rounded">skills_used</code>{' '}
              on those tasks).
            </p>

            {error && (
              <div className="mb-4 bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            <div className="mb-6">
              <p className="text-sm font-medium text-gray-700 mb-2">Current profile</p>
              <div className="space-y-2 max-h-48 overflow-y-auto border border-gray-200 rounded-lg p-3 bg-gray-50">
                {(userSkills || []).length === 0 ? (
                  <p className="text-sm text-gray-500">No skills yet — add some below.</p>
                ) : (
                  (userSkills || []).map((skill) => (
                    <div
                      key={skill.skill_name}
                      className="flex items-center justify-between gap-3 py-2 border-b border-gray-200 last:border-0"
                    >
                      <span className="font-medium text-gray-900">{skill.skill_name}</span>
                      <ProficiencyStars level={Number(skill.proficiency_level) || 1} editable={false} />
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="space-y-3 mb-6">
              <p className="text-sm font-medium text-gray-700">New skills to add</p>
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={newSkill}
                  onChange={(e) => setNewSkill(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addPendingSkill())}
                  placeholder="e.g. Kubernetes"
                  className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={isLoading}
                />
                <button
                  type="button"
                  onClick={addPendingSkill}
                  className="px-4 py-3 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors whitespace-nowrap border border-gray-300"
                  disabled={isLoading}
                >
                  Queue
                </button>
              </div>
              <p className="text-xs text-gray-500">New entries start at level 1 until tasks are completed.</p>
            </div>

            {pendingAdd.length > 0 && (
              <div className="space-y-2 mb-6">
                {pendingAdd.map((name) => (
                  <div
                    key={name}
                    className="flex items-center justify-between p-3 bg-blue-50 border border-blue-100 rounded-lg"
                  >
                    <span className="font-medium text-gray-900">{name}</span>
                    <button
                      type="button"
                      onClick={() => removePending(name)}
                      className="text-red-600 hover:text-red-800 text-sm font-medium"
                      disabled={isLoading}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-end space-x-3 pt-6 border-t border-gray-200">
              <button
                type="button"
                onClick={onCloseForm}
                className="px-6 py-3 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors border border-gray-300"
                disabled={isLoading}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                className="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                disabled={isLoading || pendingAdd.length === 0}
              >
                {isLoading ? (
                  <span className="flex items-center">
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                    Saving...
                  </span>
                ) : (
                  'Save new skills'
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const list = userSkills || [];

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-semibold text-gray-900">Skill Profile</h3>
        <button
          type="button"
          onClick={openModal}
          className="text-blue-600 hover:text-blue-700 text-sm font-medium"
        >
          Add skills
        </button>
      </div>

      {list.length === 0 ? (
        <div className="text-center py-8">
          <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
          <p className="mt-2 text-gray-500">No skills added yet</p>
          <button type="button" onClick={openModal} className="mt-4 text-blue-600 hover:text-blue-700 text-sm font-medium">
            Add your skills
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-gray-500 -mt-2 mb-2">
            Levels update when tasks are completed; use &quot;Add skills&quot; for new names only.
          </p>
          {list.map((skill) => (
            <div key={skill.skill_name} className="flex items-center justify-between p-3 hover:bg-gray-50 rounded-lg">
              <div className="flex items-center space-x-4">
                <span className="font-medium text-gray-900">{skill.skill_name}</span>
                <ProficiencyStars level={Number(skill.proficiency_level) || 1} editable={false} />
              </div>
              <span className="text-sm text-gray-500">
                {skill.proficiency_level >= 4
                  ? 'Expert'
                  : skill.proficiency_level >= 3
                    ? 'Proficient'
                    : skill.proficiency_level >= 2
                      ? 'Intermediate'
                      : 'Beginner'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SkillProfile;
