// src/components/ProjectForm.jsx
import React, { useState } from 'react';

const ProjectForm = ({ onSubmit, onCancel, parseSRS, isLoading }) => {
  const [creationMethod, setCreationMethod] = useState('manual');
  const [manualFormData, setManualFormData] = useState({
    title: '',
    description: '',
    require_skills: [],
    deadline: '',
    department: ''
  });
  const [srsDocument, setSrsDocument] = useState(null);
  const [currentSkill, setCurrentSkill] = useState('');
  const [parsedData, setParsedData] = useState(null);
  const [isParsing, setIsParsing] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const safeText = (value, fallback = 'Request failed') => {
    if (typeof value === 'string') return value;
    if (value == null) return fallback;
    if (typeof value === 'object' && value.msg) return String(value.msg);
    try {
      return JSON.stringify(value);
    } catch {
      return fallback;
    }
  };

  const handleSkillAdd = () => {
    if (currentSkill && !manualFormData.require_skills.includes(currentSkill)) {
      setManualFormData({
        ...manualFormData,
        require_skills: [...manualFormData.require_skills, currentSkill]
      });
      setCurrentSkill('');
    }
  };

  const handleSkillRemove = (skill) => {
    setManualFormData({
      ...manualFormData,
      require_skills: manualFormData.require_skills.filter(s => s !== skill)
    });
  };

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (file) {
      // Check file type
      const allowedTypes = ['application/pdf', 'application/msword', 
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain'];
      const allowedExtensions = ['.pdf', '.doc', '.docx', '.txt'];
      
      const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
      
      if (!allowedTypes.includes(file.type) && !allowedExtensions.includes(fileExtension)) {
        setUploadError('Please upload a PDF, DOC, DOCX, or TXT file only.');
        return;
      }
      
      // Check file size (10MB)
      if (file.size > 10 * 1024 * 1024) {
        setUploadError('File size must be less than 10MB.');
        return;
      }

      setSrsDocument(file);
      setUploadError('');
      setParsedData(null);

      // Parse SRS document
      if (parseSRS) {
        setIsParsing(true);
        try {
          const result = await parseSRS(file);
          if (result.success && result.data) {
            const req = result.data.requirements || {};
            const detected = Array.isArray(req.detected_skills)
              ? req.detected_skills
              : [];
            setParsedData(result.data);

            setManualFormData({
              title: req.title || manualFormData.title,
              description: req.description || manualFormData.description,
              require_skills: [...new Set([...manualFormData.require_skills, ...detected])],
              deadline: manualFormData.deadline,
              department: manualFormData.department,
            });
          } else {
            setUploadError(safeText(result.error, 'Failed to parse document'));
            setSrsDocument(null);
            setParsedData(null);
          }
        } catch (err) {
          setUploadError(
            err?.response?.data?.detail ||
              err?.message ||
              'This is not an SRS document. Please upload a Software Requirements Specification.'
          );
          setSrsDocument(null);
          setParsedData(null);
          console.error('Error parsing document:', err);
        } finally {
          setIsParsing(false);
        }
      }
    }
  };

  const removeDocument = () => {
    setSrsDocument(null);
    setParsedData(null);
    setUploadError('');
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' bytes';
    else if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    else return (bytes / 1048576).toFixed(1) + ' MB';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (creationMethod === 'manual') {
      const projectData = {
        ...manualFormData,
        srs_document: srsDocument
      };
      await onSubmit(projectData);
    } else if (creationMethod === 'upload' && srsDocument) {
      const req = parsedData?.requirements || {};
      const projectData = {
        title: req.title || 'Project from SRS',
        description: req.description || 'Project requirements extracted from SRS',
        require_skills: manualFormData.require_skills,
        deadline: manualFormData.deadline || '2025-12-31',
        department: manualFormData.department || 'Software Development',
        srs_document: srsDocument,
      };
      await onSubmit(projectData);
    } else {
      alert('Please complete the required information');
    }
  };

  return (
    <div className="modal-backdrop fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50 overflow-y-auto">
      <div className="modal-panel bg-white rounded-2xl shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h3 className="text-2xl font-bold text-gray-900 mb-6">Create New Project</h3>
          
          {/* Creation Method Selection */}
          <div className="mb-8">
            <h4 className="text-lg font-medium text-gray-900 mb-4">Choose Creation Method</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <button
                type="button"
                onClick={() => setCreationMethod('manual')}
                className={`p-6 rounded-xl border-2 transition-all duration-300 ${
                  creationMethod === 'manual'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-300 hover:border-blue-300'
                }`}
                disabled={isLoading}
              >
                <div className="flex flex-col items-center text-center">
                  <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mb-3">
                    <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </div>
                  <h5 className="font-semibold text-gray-900 mb-2">Enter Manually</h5>
                  <p className="text-sm text-gray-600">
                    Fill in project details manually with complete control
                  </p>
                </div>
              </button>

              <button
                type="button"
                onClick={() => setCreationMethod('upload')}
                className={`p-6 rounded-xl border-2 transition-all duration-300 ${
                  creationMethod === 'upload'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-300 hover:border-blue-300'
                }`}
                disabled={isLoading}
              >
                <div className="flex flex-col items-center text-center">
                  <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mb-3">
                    <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <h5 className="font-semibold text-gray-900 mb-2">Upload SRS Document</h5>
                  <p className="text-sm text-gray-600">
                    Upload Software Requirements Specification document
                  </p>
                </div>
              </button>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            {creationMethod === 'manual' ? (
              /* Manual Entry Form */
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Project Title</label>
                  <input
                    type="text"
                    value={manualFormData.title}
                    onChange={(e) => setManualFormData({...manualFormData, title: e.target.value})}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                    required
                    placeholder="Enter project title"
                    disabled={isLoading}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
                  <textarea
                    value={manualFormData.description}
                    onChange={(e) => setManualFormData({...manualFormData, description: e.target.value})}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900 h-32 resize-none"
                    required
                    placeholder="Describe the project requirements and objectives"
                    disabled={isLoading}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Department</label>
                  <input
                    type="text"
                    value={manualFormData.department}
                    onChange={(e) => setManualFormData({...manualFormData, department: e.target.value})}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                    required
                    placeholder="Enter department name"
                    disabled={isLoading}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Required Skills</label>
                  <div className="flex space-x-2 mb-3">
                    <input
                      type="text"
                      value={currentSkill}
                      onChange={(e) => setCurrentSkill(e.target.value)}
                      placeholder="Add a skill (e.g., React, Python, ML)"
                      className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                      disabled={isLoading}
                    />
                    <button 
                      type="button" 
                      onClick={handleSkillAdd}
                      className="px-4 py-3 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors whitespace-nowrap border border-gray-300"
                      disabled={isLoading}
                    >
                      Add Skill
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {manualFormData.require_skills.map(skill => (
                      <span key={skill} className="inline-flex items-center px-3 py-2 rounded-lg text-sm font-medium bg-blue-100 text-blue-800">
                        {skill}
                        <button 
                          type="button"
                          onClick={() => handleSkillRemove(skill)}
                          className="ml-2 hover:text-blue-900 text-lg"
                          disabled={isLoading}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Deadline</label>
                  <input
                    type="date"
                    value={manualFormData.deadline}
                    onChange={(e) => setManualFormData({...manualFormData, deadline: e.target.value})}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                    required
                    disabled={isLoading}
                  />
                </div>
              </>
            ) : (
              /* SRS Document Upload Form */
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Upload SRS Document</label>
                  
                  {uploadError && (
                    <div className="mb-4 bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                      {uploadError}
                    </div>
                  )}
                  
                  {!srsDocument ? (
                    <div className="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center hover:border-blue-500 transition-colors">
                      <input
                        type="file"
                        id="srs-document"
                        accept=".pdf,.doc,.docx,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                        onChange={handleFileChange}
                        className="hidden"
                        disabled={isLoading || isParsing}
                      />
                      <label htmlFor="srs-document" className="cursor-pointer">
                        <div className="mb-4">
                          <svg className="mx-auto h-16 w-16 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                          </svg>
                        </div>
                        <p className="text-lg font-medium text-gray-900 mb-2">Upload SRS Document</p>
                        <p className="text-sm text-gray-600 mb-4">
                          <span className="font-medium text-blue-600 hover:text-blue-500">
                            Click to upload
                          </span>{' '}
                          or drag and drop
                        </p>
                        <p className="text-xs text-gray-500">
                          PDF, DOC, DOCX, or TXT (Max. 10MB)
                        </p>
                      </label>
                    </div>
                  ) : (
                    <div className="space-y-6">
                      {/* Document Preview */}
                      <div className="bg-gray-50 border border-gray-200 rounded-xl p-6">
                        <div className="flex items-center justify-between mb-4">
                          <div className="flex items-center space-x-4">
                            <span className="text-3xl">
                              {(srsDocument.type || '').includes('pdf')
                                ? '📄'
                                : (srsDocument.type || '').includes('word')
                                  ? '📝'
                                  : (srsDocument.type || '').includes('text')
                                    ? '📃'
                                    : '📎'}
                            </span>
                            <div>
                              <p className="font-medium text-gray-900">{srsDocument.name}</p>
                              <p className="text-sm text-gray-500">
                                {formatFileSize(srsDocument.size)}
                              </p>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={removeDocument}
                            className="text-red-600 hover:text-red-800 p-2"
                            title="Remove document"
                            disabled={isLoading || isParsing}
                          >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                        
                        {isParsing && (
                          <div className="mb-4">
                            <div className="flex items-center justify-center">
                              <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mr-3"></div>
                              <span className="text-gray-600">Parsing document and extracting requirements...</span>
                            </div>
                          </div>
                        )}
                      </div>
                      
                      {/* Parsed Data Preview */}
                      {parsedData?.requirements && (
                        <div className="bg-blue-50 border border-blue-200 rounded-xl p-6">
                          <h4 className="font-semibold text-blue-900 mb-4">Extracted Project Information</h4>
                          
                          <div className="space-y-4">
                            <div>
                              <p className="text-sm text-gray-600 mb-1">Project Title</p>
                              <p className="font-medium text-gray-900">{parsedData.requirements.title || '—'}</p>
                            </div>
                            
                            <div>
                              <p className="text-sm text-gray-600 mb-1">Description</p>
                              <p className="text-gray-700">{parsedData.requirements.description || '—'}</p>
                            </div>
                            
                            <div className="grid grid-cols-2 gap-4">
                              <div>
                                <p className="text-sm text-gray-600 mb-1">Complexity Score</p>
                                <p className="font-medium text-gray-900">
                                  {typeof parsedData.requirements.complexity_score === 'number'
                                    ? `${parsedData.requirements.complexity_score.toFixed(1)}/100`
                                    : '—'}
                                </p>
                              </div>
                              
                              <div>
                                <p className="text-sm text-gray-600 mb-1">Suggested Team Size</p>
                                <p className="font-medium text-gray-900">
                                  {parsedData.requirements.team_size_suggestion != null
                                    ? `${parsedData.requirements.team_size_suggestion} developers`
                                    : '—'}
                                </p>
                              </div>
                            </div>
                            
                            <div>
                              <p className="text-sm text-gray-600 mb-2">Detected Skills</p>
                              <div className="flex flex-wrap gap-2">
                                {(parsedData.requirements.detected_skills || []).map((skill) => (
                                  <span key={skill} className="inline-flex items-center px-3 py-1 rounded-lg text-sm font-medium bg-blue-100 text-blue-800">
                                    {skill}
                                  </span>
                                ))}
                              </div>
                            </div>
                            
                            <div className="pt-4 border-t border-blue-200">
                              <p className="text-sm text-blue-700">
                                <span className="font-medium">Note:</span> You can edit this information after creation if needed.
                              </p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                
                {/* Additional fields for SRS method */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Additional Skills (Optional)</label>
                  <div className="flex space-x-2 mb-3">
                    <input
                      type="text"
                      value={currentSkill}
                      onChange={(e) => setCurrentSkill(e.target.value)}
                      placeholder="Add additional skills if needed"
                      className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                      disabled={isLoading || isParsing}
                    />
                    <button 
                      type="button" 
                      onClick={handleSkillAdd}
                      className="px-4 py-3 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors whitespace-nowrap border border-gray-300"
                      disabled={isLoading || isParsing}
                    >
                      Add Skill
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {manualFormData.require_skills.map(skill => (
                      <span key={skill} className="inline-flex items-center px-3 py-2 rounded-lg text-sm font-medium bg-blue-100 text-blue-800">
                        {skill}
                        <button 
                          type="button"
                          onClick={() => handleSkillRemove(skill)}
                          className="ml-2 hover:text-blue-900 text-lg"
                          disabled={isLoading || isParsing}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Project Deadline</label>
                  <input
                    type="date"
                    value={manualFormData.deadline}
                    onChange={(e) => setManualFormData({...manualFormData, deadline: e.target.value})}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                    required
                    disabled={isLoading || isParsing}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Department</label>
                  <input
                    type="text"
                    value={manualFormData.department}
                    onChange={(e) => setManualFormData({...manualFormData, department: e.target.value})}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white text-gray-900"
                    placeholder="Enter department name"
                    disabled={isLoading || isParsing}
                  />
                </div>
              </div>
            )}

            <div className="flex justify-end space-x-3 pt-6 border-t border-gray-200">
              <button 
                type="button" 
                onClick={onCancel} 
                className="px-6 py-3 bg-gray-100 text-gray-700 font-medium rounded-lg hover:bg-gray-200 transition-colors border border-gray-300"
                disabled={isLoading || isParsing}
              >
                Cancel
              </button>
              <button 
                type="submit" 
                disabled={
                  isLoading || isParsing || 
                  (creationMethod === 'upload' && !srsDocument) || 
                  (creationMethod === 'manual' && !manualFormData.title)
                }
                className="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? (
                  <span className="flex items-center">
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                    Creating...
                  </span>
                ) : creationMethod === 'manual' ? (
                  'Create Project'
                ) : (
                  'Create from SRS'
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};

export default ProjectForm;