// src/services/api.js
import axios from 'axios';

/**
 * Uvicorn serves the API at `/` (no `/api` prefix). Vite rewrites `/api/*` → `http://127.0.0.1:8000/*`.
 * In dev, invalid VITE_API_URL values must not become axios baseURL (they cause HTML 404 "Not Found").
 */
function resolveApiBaseUrl() {
  const raw = import.meta.env.VITE_API_URL;
  const empty = raw == null || String(raw).trim() === '';

  if (import.meta.env.DEV) {
    if (empty) return '/api';
    let u = String(raw).trim().replace(/\/+$/, '');
    if (u === '/api') return '/api';
    if (/^https?:\/\//i.test(u)) {
      if (u.endsWith('/api')) u = u.slice(0, -4);
      return u;
    }
    // Typos / accidental values — force proxy so team-details and other routes reach FastAPI.
    return '/api';
  }

  if (empty) {
    return 'http://127.0.0.1:8000';
  }
  let u = String(raw).trim().replace(/\/+$/, '');
  if (u === '/api') {
    return '/api';
  }
  if (/^https?:\/\//i.test(u) && u.endsWith('/api')) {
    u = u.slice(0, -4);
  }
  return u || 'http://127.0.0.1:8000';
}

/** Relative `/api` in dev = same-origin + Vite proxy (works on 5173, 5175, LAN). */
function getResolvedApiBase() {
  return resolveApiBaseUrl();
}

/**
 * Always use an absolute origin + /api in the browser when proxying so nested routes
 * (e.g. /manager) never mis-resolve and the Vite proxy reliably reaches 127.0.0.1:8000.
 */
function getAxiosBaseURL() {
  const base = resolveApiBaseUrl();
  if (base === '/api' && typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}/api`;
  }
  return base;
}

/** 0 = no axios timeout (wait until backend responds — best for demo/viva). */
function resolveAxiosTimeoutMs(envValue, fallback = 0) {
  if (envValue == null || String(envValue).trim() === '') return fallback;
  const n = Number(envValue);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

const API_REQUEST_TIMEOUT_MS = resolveAxiosTimeoutMs(import.meta.env.VITE_API_TIMEOUT_MS, 0);
const ANALYTICS_REQUEST_TIMEOUT_MS = resolveAxiosTimeoutMs(
  import.meta.env.VITE_ANALYTICS_TIMEOUT_MS,
  API_REQUEST_TIMEOUT_MS,
);

const api = axios.create({
  baseURL: getAxiosBaseURL(),
  timeout: API_REQUEST_TIMEOUT_MS,
  // Do not set a default Content-Type: it breaks multipart/form-data (e.g. task submit-for-review).
  // Axios sets application/json automatically for plain object bodies.
});

function axiosAttemptedRequestLabel(err) {
  const cfg = err?.config;
  if (!cfg) return '';
  const base = cfg.baseURL != null ? String(cfg.baseURL).replace(/\/+$/, '') : '';
  const u = cfg.url != null ? String(cfg.url) : '';
  if (!base && !u) return '';
  if (!u) return base;
  if (/^https?:\/\//i.test(u)) return u;
  const path = u.startsWith('/') ? u : `/${u}`;
  return base ? `${base}${path}` : path;
}

export const getApiErrorMessage = (err, fallback = 'Request failed') => {
  const data = err?.response?.data;
  const detail = data?.detail;
  const message = data?.message;

  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (typeof first === 'string' && first.trim()) return first;
    if (first?.msg) return String(first.msg);
    try {
      return JSON.stringify(first);
    } catch {
      return fallback;
    }
  }
  if (detail && typeof detail === 'object') {
    if (detail.msg) return String(detail.msg);
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  if (typeof message === 'string' && message.trim()) return message;
  const status = err?.response?.status;
  if (typeof data === 'string' && (data.includes('<!DOCTYPE') || data.includes('<html'))) {
    return (
      `API returned HTML instead of JSON (${status || '?'}). Use Vite with VITE_API_URL=/api ` +
      `or point the client at the FastAPI base URL. Tried: ${axiosAttemptedRequestLabel(err) || 'unknown'}.`
    );
  }
  if (status === 404 && (detail == null || detail === '')) {
    return 'Not found — check project id, login as manager/admin, and that the backend is running.';
  }
  if (err?.code === 'ECONNABORTED' || /timeout of \d+ms exceeded/i.test(String(err?.message || ''))) {
    const tried = axiosAttemptedRequestLabel(err);
    return (
      (tried ? `Request timed out (${tried}). ` : 'Request timed out. ') +
      'Backend slow or not running: start uvicorn on port 8000, check MongoDB, and use Vite proxy (/api → 8000).'
    );
  }
  if (typeof err?.message === 'string' && err.message.trim()) {
    const m = err.message.trim();
    if (m === 'Network Error' || m === 'Failed to fetch') {
      const tried = axiosAttemptedRequestLabel(err);
      const where = tried
        ? `Request failed: ${tried} (no response from server). `
        : 'No response from server. ';
      return (
        where +
        'Start the backend (uvicorn on http://127.0.0.1:8000) and fix MongoDB if startup crashes. ' +
        'With Vite dev, keep VITE_API_URL=/api so the browser calls your dev origin /api (proxied to 8000). ' +
        'If you use `npm run build` + a static server, either run `npm run preview` or set VITE_API_URL to your API base URL.'
      );
    }
    return m;
  }
  return String(fallback);
};

/** MongoDB ObjectId as 24 hex chars (API project.id). */
const MONGO_OBJECT_ID_RE = /^[a-f0-9]{24}$/i;

/** Safe id from project list row — avoids String(undefined) === "undefined". */
export function resolveProjectDocumentId(project) {
  if (!project || typeof project !== 'object') return '';
  let raw = project.id ?? project._id ?? project.project_id;
  if (raw && typeof raw === 'object') {
    if (raw.$oid) raw = raw.$oid;
    else if (raw._id) raw = raw._id;
  }
  if (raw == null) return '';
  const s = String(raw).trim().replace(/[\u200B-\u200D\uFEFF]/g, '');
  if (!s || s === 'undefined' || s === 'null') return '';
  return s;
}

export function isMongoObjectIdString(s) {
  return typeof s === 'string' && MONGO_OBJECT_ID_RE.test(s);
}

/** @param {string | undefined} contentDisposition */
export const parseAttachmentFilename = (contentDisposition) => {
  if (!contentDisposition || typeof contentDisposition !== 'string') return null;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(contentDisposition);
  if (star) {
    const raw = star[1].trim().replace(/^"+|"+$/g, '');
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(contentDisposition);
  if (quoted) return quoted[1];
  const loose = /filename=([^;]+)/i.exec(contentDisposition);
  if (loose) return loose[1].trim().replace(/^"+|"+$/g, '');
  return null;
};

// Add token to requests if available
api.interceptors.request.use(
  (config) => {
    // Absolute /api URL avoids bad merges for nested routes (e.g. /manager on :5175).
    if (resolveApiBaseUrl() === '/api' && typeof window !== 'undefined') {
      config.baseURL = `${window.location.origin}/api`;
    }
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // Let the browser set multipart boundary for FormData (critical for file + field uploads).
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type'];
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Add response interceptor for error handling
api.interceptors.response.use(
  (response) => {
    const ct = response.headers?.['content-type'] || response.headers?.['Content-Type'] || '';
    if (
      import.meta.env.DEV &&
      typeof response.data === 'string' &&
      (response.data.includes('<!DOCTYPE') || response.data.includes('<html')) &&
      String(ct).includes('html')
    ) {
      // eslint-disable-next-line no-console
      console.warn(
        '[api] Received HTML instead of JSON — check Vite proxy and that FastAPI is on port 8000.',
        response.config?.url,
      );
    }
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.dispatchEvent(new Event('auth:unauthorized'));
    }
    return Promise.reject(error);
  }
);

// Auth services
export const authService = {
  login: async (email, password) => {
    const normalizedEmail = String(email || '').trim();
    const normalizedPassword = String(password || '');
    const response = await api.post('/auth/login', {
      email: normalizedEmail,
      password: normalizedPassword,
    });
    return response.data;
  },

  register: async (userData) => {
    const response = await api.post('/auth/register', userData);
    return response.data;
  },

 getCurrentUser: async () => {
  try {
    const response = await api.get('/auth/me');
    return { user: response.data }; // Wrap in user object
  } catch (err) {
    throw err;
  }
},
  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  }
};

// Project services
export const projectService = {
  createProject: async (projectData) => {
    const formData = new FormData();
    
    Object.keys(projectData).forEach(key => {
      const value = projectData[key];
      if (value === undefined || value === null) return;

      if (key === 'require_skills') {
        const skills = Array.isArray(value) ? value.filter(Boolean) : [];
        formData.append(key, skills.join(','));
        return;
      }

      if (key === 'srs_document') {
        if (value instanceof File) {
          formData.append(key, value);
        }
        return;
      }

      if (typeof value === 'string' && value.trim() === '') return;
      formData.append(key, value);
    });

    const response = await api.post('/projects/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  getProjects: async (params = {}) => {
    const maxAttempts = 3;
    let lastErr;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        const response = await api.get('/projects/', { params });
        return response.data;
      } catch (err) {
        lastErr = err;
        const timedOut =
          err?.code === 'ECONNABORTED' ||
          /timeout of \d+ms exceeded/i.test(String(err?.message || ''));
        if (!timedOut || attempt === maxAttempts) throw err;
        await new Promise((r) => setTimeout(r, 800 * attempt));
      }
    }
    throw lastErr;
  },

  getRunningProjectsDirectory: async (params = {}) => {
    const response = await api.get('/projects/directory/running', { params });
    return response.data;
  },

  getProject: async (projectId) => {
    const response = await api.get(`/projects/${projectId}`);
    return response.data;
  },

  updateProject: async (projectId, updates) => {
    const response = await api.put(`/projects/${projectId}`, updates);
    return response.data;
  },

  deleteProject: async (projectId) => {
    await api.delete(`/projects/${projectId}`);
  },

  getRecommendations: async (projectId) => {
    const response = await api.get(`/projects/${projectId}/recommendations`);
    return response.data;
  },

  getStatsSummary: async () => {
    const response = await api.get('/projects/stats/summary');
    return response.data;
  },

  getProjectTeamDetails: async (projectId) => {
    const id = String(projectId ?? '')
      .trim()
      .replace(/[\u200B-\u200D\uFEFF]/g, '');
    if (!id || id === 'undefined' || id === 'null') {
      throw Object.assign(new Error('Invalid project id'), {
        response: { status: 400, data: { detail: 'Invalid project id' } },
      });
    }
    const pathUrl = `/projects/${encodeURIComponent(id)}/team-details`;
    const tryFetch = async (url, params) => {
      const response = await api.get(url, params ? { params } : undefined);
      return response.data;
    };
    /** Unwrap axios-style or legacy { data: { ... } } / { result: ... } payloads. */
    const unwrapPayload = (raw) => {
      if (raw == null || typeof raw !== 'object') return raw;
      let cur = raw;
      let depth = 0;
      while (depth < 5 && cur && typeof cur === 'object') {
        if (Array.isArray(cur)) break;
        if (
          cur.team_details != null ||
          cur.developers != null ||
          cur.summary != null ||
          cur.project_id != null
        ) {
          return cur;
        }
        if (cur.data != null && typeof cur.data === 'object') {
          cur = cur.data;
          depth += 1;
          continue;
        }
        if (cur.result != null && typeof cur.result === 'object') {
          cur = cur.result;
          depth += 1;
          continue;
        }
        break;
      }
      return cur;
    };
    const normalize = (data) => {
      const unwrapped = unwrapPayload(data);
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.log('[team-details] unwrap: had nested data/result=', unwrapped !== data, 'topKeys=', data && typeof data === 'object' ? Object.keys(data) : []);
      }
      if (!unwrapped || typeof unwrapped !== 'object') {
        return {
          team_details: [],
          developers: [],
          summary: {},
          message: 'Invalid API response',
        };
      }
      const rows = Array.isArray(unwrapped.team_details)
        ? unwrapped.team_details
        : Array.isArray(unwrapped.developers)
          ? unwrapped.developers
          : Array.isArray(unwrapped.team)
            ? unwrapped.team
            : [];
      return {
        ...unwrapped,
        team_details: rows,
        developers: rows,
      };
    };
    const logDev = (label, raw) => {
      if (!import.meta.env.DEV) return;
      // eslint-disable-next-line no-console
      console.log(`[team-details] raw response (${label})`, raw);
      try {
        // eslint-disable-next-line no-console
        console.log('[team-details] raw JSON sample', JSON.stringify(raw).slice(0, 2000));
      } catch {
        /* ignore */
      }
    };

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.debug(
        '[team-details] GET ?project_id= then fallback',
        pathUrl,
        'baseURL',
        api.defaults.baseURL || '(relative)',
      );
    }

    try {
      const rawQ = await tryFetch('/projects/team-details', { project_id: id });
      logDev('query', rawQ);
      const out = normalize(rawQ);
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.log(
          '[team-details] normalized team_details length=',
          out.team_details?.length,
          'summary=',
          out.summary,
        );
      }
      return out;
    } catch (errQ) {
      const stQ = errQ?.response?.status;
      if (stQ === 401) {
        throw errQ;
      }
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[team-details] query failed', stQ, '→ path', errQ?.response?.data);
      }
      try {
        const rawP = await tryFetch(pathUrl);
        logDev('path', rawP);
        const out = normalize(rawP);
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.log('[team-details] normalized (path) team_details length=', out.team_details?.length);
        }
        return out;
      } catch (errP) {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.error(
            '[team-details] both routes failed',
            errP?.response?.status,
            errP?.response?.data,
          );
        }
        throw errP;
      }
    }
  },
};

// ML services
export const mlService = {
  parseSRS: async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await api.post('/ml/parse-srs', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  matchDevelopers: async (skills, minScore = 70) => {
    const response = await api.post('/ml/match-developers', {
      required_skills: skills,
      min_match_score: minScore
    });
    return response.data;
  },

  analyzeSkillGap: async (projectId) => {
    const response = await api.get(`/ml/skill-analysis?project_id=${projectId}`);
    return response.data;
  },

  extractSkillsFromText: async (text) => {
    const response = await api.post('/ml/extract-skills-from-text', { text });
    return response.data;
  },
};

// User services
export const userService = {
  getDevelopers: async () => {
    const response = await api.get('/users/developers');
    return response.data;
  },

  getDeveloperDirectory: async () => {
    const response = await api.get('/users/directory/developers');
    return response.data;
  },

  updateUser: async (userId, updates) => {
    const response = await api.put(`/users/${userId}`, updates);
    return response.data;
  },

  updateSkills: async (userId, skills) => {
    const response = await api.post(`/users/${userId}/skills`, { skills });
    return response.data;
  },

  /** SDS §1.4 — merge skills extracted from resume/CV (PDF/DOCX/TXT). */
  uploadResume: async (userId, file, mergeSkills = true) => {
    const formData = new FormData();
    formData.append('resume', file);
    const q = mergeSkills ? '' : '?merge_skills=false';
    const response = await api.post(`/users/${userId}/resume${q}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },
};

/** @param {'week'|'month'|'quarter'|'all'} [period] */
export const analyticsService = {
  getDashboard: async (period = 'month') => {
    const response = await api.get('/analytics/dashboard', {
      params: { period, _t: Date.now() },
    });
    return response.data;
  },
  getPerformanceReport: async (period = 'month') => {
    const response = await api.get('/analytics/performance-report', {
      params: { period, _t: Date.now() },
      timeout: ANALYTICS_REQUEST_TIMEOUT_MS,
    });
    return response.data;
  },
  getSkillGapDetail: async () => {
    const response = await api.get('/analytics/skill-gap-detail', {
      params: { _t: Date.now() },
      timeout: ANALYTICS_REQUEST_TIMEOUT_MS,
    });
    return response.data;
  },
  /** @returns {Promise<{ blob: Blob; filename: string }>} */
  getPerformanceReportPdf: async (period = 'month') => {
    const response = await api.get('/analytics/performance-report/pdf', {
      params: { period, _t: Date.now() },
      responseType: 'blob',
      timeout: ANALYTICS_REQUEST_TIMEOUT_MS,
    });
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const fallback = `performance_report_v4_${period}_${stamp}.pdf`;
    const filename =
      parseAttachmentFilename(response.headers?.['content-disposition']) || fallback;
    return { blob: response.data, filename };
  },
  /** @returns {Promise<{ blob: Blob; filename: string }>} */
  getSkillGapPdf: async () => {
    const response = await api.get('/analytics/skill-gap-detail/pdf', {
      params: { _t: Date.now() },
      responseType: 'blob',
      timeout: ANALYTICS_REQUEST_TIMEOUT_MS,
    });
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const fallback = `skill_gap_analysis_v4_${stamp}.pdf`;
    const filename =
      parseAttachmentFilename(response.headers?.['content-disposition']) || fallback;
    return { blob: response.data, filename };
  },
  /** @param {'json'|'csv'} format @param {'week'|'month'|'quarter'|'all'} [period] */
  exportAnalytics: async (format = 'json', period = 'month') => {
    const response = await api.get('/analytics/export', {
      params: { format, period },
      responseType: 'text',
      timeout: ANALYTICS_REQUEST_TIMEOUT_MS,
    });
    const stamp = new Date().toISOString().slice(0, 10);
    const blob = new Blob([response.data], {
      type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const ext = format === 'csv' ? 'csv' : 'json';
    a.download = `analytics_export_${period}_${stamp}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};

export const chatbotService = {
  query: async (message) => {
    const response = await api.post('/chatbot/query', { message });
    return response.data;
  },
};

export const teamService = {
  list: async (projectId) => {
    const response = await api.get('/teams/', { params: projectId ? { project_id: projectId } : {} });
    return response.data;
  },
  create: async (data) => {
    const response = await api.post('/teams/', data);
    return response.data;
  },
};

export const recommendationService = {
  list: async (statusFilter) => {
    const response = await api.get('/recommendations/', {
      params: statusFilter ? { status_filter: statusFilter } : {},
    });
    return response.data;
  },
  create: async (payload) => {
    const response = await api.post('/recommendations/', payload);
    return response.data;
  },
  approve: async (recId, note = '') => {
    const response = await api.post(`/recommendations/${recId}/approve`, { note });
    return response.data;
  },
  reject: async (recId, reason) => {
    const response = await api.post(`/recommendations/${recId}/reject`, { reason });
    return response.data;
  },
};

// Task services
export const taskService = {
  getTasks: async (params = {}) => {
    const response = await api.get('/tasks/', { params });
    return response.data;
  },

  createTask: async (taskData) => {
    const response = await api.post('/tasks/', taskData);
    return response.data;
  },

  updateTaskStatus: async (taskId, status) => {
    const response = await api.put(`/tasks/${taskId}/status`, { status });
    return response.data;
  },

  requestTaskChanges: async (taskId, comment) => {
    const response = await api.post(`/tasks/${taskId}/request-changes`, { comment });
    return response.data;
  },

  /** Submit work for PM review: text paste, comment, optional files */
  submitTaskForReview: async (taskId, { textContent = '', comment = '', files = [] }) => {
    const formData = new FormData();
    formData.append('text_content', textContent);
    formData.append('comment', comment);
    for (const f of files) {
      if (f) formData.append('files', f);
    }
    const response = await api.post(`/tasks/${taskId}/submit-for-review`, formData);
    return response.data;
  },

  getReviewSubmissions: async () => {
    const response = await api.get('/tasks/review-submissions');
    return response.data;
  },

  downloadSubmissionFile: async (taskId, fileIndex) => {
    const response = await api.get(`/tasks/${taskId}/submission/file/${fileIndex}`, {
      responseType: 'blob',
    });
    return response.data;
  },
};

export default api;


