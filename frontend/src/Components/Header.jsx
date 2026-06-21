// src/components/Header.jsx
import React from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import { useTheme } from '../context/ThemeContext.jsx';
import { Link, useLocation } from 'react-router-dom';

const Header = () => {
  const { user, logout } = useAuth();
  const { isDarkMode, toggleTheme } = useTheme();
  const location = useLocation();

  const NavLink = ({ to, children }) => (
    <Link
      to={to}
      className={`px-4 py-2 rounded-lg font-medium transition-colors duration-300 ${
        location.pathname === to
          ? 'bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-200'
          : 'text-slate-800 hover:text-slate-950 hover:bg-gray-100 dark:text-gray-200 dark:hover:text-white dark:hover:bg-gray-800'
      }`}
    >
      {children}
    </Link>
  );

  const getInitials = (name) => {
    if (!name) return 'U';
    return name
      .split(' ')
      .map(word => word[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  // z-[100] keeps nav above modal backdrops (z-50) so Tasks/Dashboard/Analytics/Logout stay clickable
  return (
    <header className="sticky top-0 z-[100] shadow-sm border-b transition-colors duration-300"
            style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border-color)' }}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          <div className="flex items-center space-x-8">
            <Link to="/dashboard" className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-blue-800 dark:from-blue-700 dark:to-blue-900 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-lg">SM</span>
              </div>
              <div>
                <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Skill Mapping</h1>
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>AI-Powered Dynamic Skill Matching</p>
              </div>
            </Link>
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-200">
              {user?.role === 'admin'
                ? 'Admin'
                : user?.role === 'manager'
                  ? 'Project Manager'
                  : 'Developer'}
            </span>
          </div>

          <nav className="flex items-center space-x-2">
            {user?.role === 'admin' && (
              <>
                <NavLink to="/dashboard">Dashboard</NavLink>
                <NavLink to="/developers">Developers</NavLink>
                <NavLink to="/analytics">Analytics</NavLink>
              </>
            )}
            {user?.role === 'manager' && (
              <>
                <NavLink to="/dashboard">Dashboard</NavLink>
                <NavLink to="/manager">Projects</NavLink>
                <NavLink to="/analytics">Analytics</NavLink>
              </>
            )}
            {user?.role === 'developer' && (
              <>
                <NavLink to="/dashboard">Dashboard</NavLink>
                <NavLink to="/developer">Tasks</NavLink>
                <NavLink to="/analytics">Analytics</NavLink>
              </>
            )}
          </nav>

          <div className="flex items-center space-x-4">
            {/* Enhanced Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg transition-all duration-300 hover:scale-105"
              style={{ 
                backgroundColor: isDarkMode ? '#374151' : '#e5e7eb',
                color: isDarkMode ? '#fbbf24' : '#f59e0b'
              }}
              aria-label="Toggle theme"
              title={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {isDarkMode ? (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                </svg>
              )}
            </button>

            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-blue-100 dark:bg-blue-900/30 rounded-full flex items-center justify-center">
                <span className="font-semibold text-blue-900 dark:text-blue-200">
                  {getInitials(user?.name || user?.email)}
                </span>
              </div>
              <div className="text-right">
                <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{user?.name || user?.email}</p>
                <p className="text-xs capitalize" style={{ color: 'var(--text-secondary)' }}>{user?.role}</p>
              </div>
            </div>
            <button
              onClick={logout}
              className="px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-300 hover:opacity-90"
              style={{ 
                backgroundColor: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)'
              }}
            >
              Logout
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;