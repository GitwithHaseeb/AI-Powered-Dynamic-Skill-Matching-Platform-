// src/components/Login.jsx
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { getDefaultRouteForRole } from '../utils/auth.js';
import AuthHero from './ui/AuthHero.jsx';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const safeErrorText = (value, fallback = 'Login failed') => {
    if (typeof value === 'string') return value;
    if (value == null) return fallback;
    if (typeof value === 'object' && value.msg) return String(value.msg);
    try {
      return JSON.stringify(value);
    } catch {
      return fallback;
    }
  };

  useEffect(() => {
    // Redirect if already logged in
    if (user) {
      navigate(getDefaultRouteForRole(user.role), { replace: true });
    }
  }, [user, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const result = await login(email, password);
      
      if (result.success) {
        navigate(getDefaultRouteForRole(result.user?.role), { replace: true });
      } else {
        setError(safeErrorText(result.error));
      }
    } catch (err) {
      setError('An unexpected error occurred');
      console.error('Login error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const inputClass =
    'w-full px-4 py-3.5 rounded-xl border border-slate-200 bg-slate-50/70 text-slate-900 placeholder-slate-400 transition-all duration-200 ease-smooth hover:border-slate-300 focus:outline-none focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/15 disabled:opacity-60';

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50/60 p-4">
      <div className="w-full max-w-6xl flex flex-col lg:flex-row bg-white rounded-3xl shadow-2xl shadow-slate-900/10 ring-1 ring-slate-900/5 overflow-hidden animate-scale-in">
        {/* Left side - Login Form */}
        <div className="w-full lg:w-1/2 p-8 sm:p-12 lg:p-16 flex flex-col justify-center">
          <div className="stagger">
            <div className="mb-10">
              <h1 className="text-4xl font-bold text-slate-900 mb-2">Welcome back</h1>
              <p className="text-slate-500">Sign in to continue to your workspace.</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-2">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className={inputClass}
                  placeholder="you@company.com"
                  required
                  disabled={isLoading}
                />
              </div>

              <div>
                <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-2">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`${inputClass} pr-12`}
                    placeholder="Enter your password"
                    required
                    disabled={isLoading}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-slate-400 hover:text-slate-700"
                    aria-label={showPassword ? 'Hide characters' : 'Show characters'}
                  >
                    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                      {showPassword ? (
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M3 3l18 18M10.58 10.58a2 2 0 102.83 2.83M9.88 5.09A9.77 9.77 0 0112 4.86c4.48 0 8.27 2.94 9.54 7a10.05 10.05 0 01-4.13 5.4M6.61 6.61A10.02 10.02 0 002.46 11.86c1.27 4.06 5.06 7 9.54 7 1.6 0 3.12-.37 4.47-1.04" />
                      ) : (
                        <>
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M2.46 12C3.73 7.94 7.52 5 12 5s8.27 2.94 9.54 7c-1.27 4.06-5.06 7-9.54 7S3.73 16.06 2.46 12z" />
                          <circle cx="12" cy="12" r="3" strokeWidth="1.8" />
                        </>
                      )}
                    </svg>
                  </button>
                </div>
              </div>

              {error && (
                <div role="alert" className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm animate-scale-in">
                  <svg className="mt-0.5 h-4 w-4 shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                  </svg>
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="group relative w-full overflow-hidden rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 py-3.5 px-4 font-semibold text-white shadow-lg shadow-blue-600/25 hover:shadow-xl hover:shadow-blue-600/30 disabled:opacity-70 flex items-center justify-center"
              >
                <span
                  aria-hidden="true"
                  className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 ease-smooth group-hover:translate-x-full"
                />
                {isLoading ? (
                  <>
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                    Signing in...
                  </>
                ) : (
                  <>
                    Sign in
                    <svg className="ml-2 h-4 w-4 transition-transform duration-300 ease-smooth group-hover:translate-x-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                  </>
                )}
              </button>
            </form>

            <p className="mt-8 text-center text-slate-500">
              Don&apos;t have an account?{' '}
              <Link to="/signup" className="font-semibold text-blue-600 hover:text-blue-700 transition-colors">
                Sign up
              </Link>
            </p>
          </div>
        </div>

        <AuthHero
          title="Build the right team for every project."
          subtitle="AI-powered skill matching for managers and developers."
        />
      </div>
    </div>
  );
};

export default Login;