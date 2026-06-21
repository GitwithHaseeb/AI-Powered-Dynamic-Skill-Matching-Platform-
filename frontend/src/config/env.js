// src/config/env.js
/** Match api.js: dev uses same-origin /api → Vite proxy → FastAPI :8000 */
const defaultApiUrl = import.meta.env.DEV ? '/api' : 'http://127.0.0.1:8000';

export const config = {
  API_URL: import.meta.env.VITE_API_URL || defaultApiUrl,
  APP_NAME: import.meta.env.VITE_APP_NAME || 'Skill Mapping Platform',
  NODE_ENV: import.meta.env.MODE || 'development',

  validate: function () {
    if (import.meta.env.DEV) return true;
    const missing = ['VITE_API_URL'].filter((key) => !import.meta.env[key]);
    if (missing.length > 0) {
      console.warn('Missing environment variables:', missing);
      return false;
    }
    return true;
  },
};

// Validate on import
config.validate();

export default config;