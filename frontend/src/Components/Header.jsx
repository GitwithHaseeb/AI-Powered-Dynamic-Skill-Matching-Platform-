// src/components/Header.jsx
import React from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import { useTheme } from '../context/ThemeContext.jsx';
import { Link, useLocation } from 'react-router-dom';

const NAV_BY_ROLE = {
  admin: [
    ['/dashboard', 'Dashboard'],
    ['/developers', 'Developers'],
    ['/analytics', 'Analytics'],
  ],
  manager: [
    ['/dashboard', 'Dashboard'],
    ['/manager', 'Projects'],
    ['/analytics', 'Analytics'],
  ],
  developer: [
    ['/dashboard', 'Dashboard'],
    ['/developer', 'Tasks'],
    ['/analytics', 'Analytics'],
  ],
};

const ROLE_LABEL = { admin: 'Admin', manager: 'Project Manager', developer: 'Developer' };

const getInitials = (name) => {
  if (!name) return 'U';
  return name
    .split(' ')
    .map((word) => word[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
};

const NavLink = ({ to, active, children }) => (
  <Link
    to={to}
    aria-current={active ? 'page' : undefined}
    className={`group relative px-3.5 py-2 text-sm font-medium rounded-lg transition-colors duration-300 ${
      active
        ? 'text-blue-700 dark:text-blue-300'
        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/80 dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-800'
    }`}
  >
    {children}
    <span
      aria-hidden="true"
      className={`absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-gradient-to-r from-blue-600 to-violet-600 origin-center transition-transform duration-300 ease-smooth ${
        active ? 'scale-x-100' : 'scale-x-0 group-hover:scale-x-50'
      }`}
    />
  </Link>
);

const Header = () => {
  const { user, logout } = useAuth();
  const { isDarkMode, toggleTheme } = useTheme();
  const location = useLocation();
  const links = NAV_BY_ROLE[user?.role] || NAV_BY_ROLE.developer;
  const displayName = user?.name || user?.email;

  const nav = links.map(([to, label]) => (
    <NavLink key={to} to={to} active={location.pathname === to}>
      {label}
    </NavLink>
  ));

  // z-[100] keeps nav above modal backdrops (z-50) so Tasks/Dashboard/Analytics/Logout stay clickable
  return (
    <header
      className="sticky top-0 z-[100] border-b backdrop-blur-xl backdrop-saturate-150 transition-colors duration-300 bg-white/80 dark:bg-gray-900/75"
      style={{ borderColor: 'var(--border-color)' }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16 gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link to="/dashboard" className="group flex items-center gap-3 min-w-0">
              <div className="relative w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-blue-600 via-indigo-600 to-violet-600 flex items-center justify-center shadow-glow transition-transform duration-300 ease-smooth group-hover:scale-105 group-hover:-rotate-3">
                <span className="text-white font-bold text-base tracking-tight">SM</span>
              </div>
              <div className="hidden sm:block min-w-0">
                <h1 className="text-lg font-bold leading-tight truncate" style={{ color: 'var(--text-primary)' }}>
                  Skill Mapping
                </h1>
                <p className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>
                  AI-Powered Dynamic Skill Matching
                </p>
              </div>
            </Link>
            <span className="hidden lg:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/15 dark:bg-blue-900/40 dark:text-blue-200 dark:ring-blue-400/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />
              {ROLE_LABEL[user?.role] || 'Developer'}
            </span>
          </div>

          <nav className="hidden md:flex items-center gap-1">{nav}</nav>

          <div className="flex items-center gap-2 sm:gap-3">
            <button
              onClick={toggleTheme}
              className="relative w-10 h-10 rounded-xl flex items-center justify-center overflow-hidden ring-1 ring-inset ring-slate-200 bg-slate-50 hover:bg-slate-100 dark:ring-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700"
              aria-label="Toggle theme"
              title={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              <svg
                className={`absolute w-5 h-5 text-amber-400 transition-all duration-500 ease-smooth ${
                  isDarkMode ? 'rotate-0 scale-100 opacity-100' : 'rotate-90 scale-50 opacity-0'
                }`}
                fill="currentColor"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
              </svg>
              <svg
                className={`absolute w-5 h-5 text-indigo-500 transition-all duration-500 ease-smooth ${
                  isDarkMode ? '-rotate-90 scale-50 opacity-0' : 'rotate-0 scale-100 opacity-100'
                }`}
                fill="currentColor"
                viewBox="0 0 20 20"
                aria-hidden="true"
              >
                <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
              </svg>
            </button>

            <div className="flex items-center gap-3 pl-1">
              <div className="w-10 h-10 shrink-0 rounded-full bg-gradient-to-br from-sky-400 to-indigo-600 p-[2px]">
                <div className="w-full h-full rounded-full bg-white dark:bg-gray-900 flex items-center justify-center">
                  <span className="text-sm font-semibold text-indigo-700 dark:text-indigo-200">{getInitials(displayName)}</span>
                </div>
              </div>
              <div className="hidden lg:block text-right">
                <p className="text-sm font-semibold leading-tight" style={{ color: 'var(--text-primary)' }}>
                  {displayName}
                </p>
                <p className="text-xs capitalize" style={{ color: 'var(--text-secondary)' }}>
                  {user?.role}
                </p>
              </div>
            </div>
            <button
              onClick={logout}
              className="inline-flex items-center gap-1.5 px-3 sm:px-4 py-2 text-sm font-medium rounded-xl ring-1 ring-inset ring-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:text-red-600 hover:ring-red-200 dark:bg-gray-800 dark:text-gray-200 dark:ring-gray-700 dark:hover:bg-gray-700 dark:hover:text-red-300"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </div>

        {/* Compact nav row on small screens */}
        <nav className="md:hidden -mx-1 flex items-center gap-1 overflow-x-auto pb-3">{nav}</nav>
      </div>
    </header>
  );
};

export default Header;
