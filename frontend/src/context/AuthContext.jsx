// src/context/AuthContext.jsx
import React, { createContext, useState, useContext, useEffect } from 'react';
import { authService, getApiErrorMessage } from '../services/api';
import { normalizeUser } from '../utils/auth.js';

const AuthContext = createContext({});

export const useAuth = () => useContext(AuthContext);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    checkAuth();
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setError('Your session expired. Please sign in again.');
    };
    window.addEventListener('auth:unauthorized', onUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized);
  }, []);

  const checkAuth = async () => {
    const token = localStorage.getItem('token');
    const savedUser = localStorage.getItem('user');

    if (token) {
      try {
        // Verify token by fetching current user
        const userData = await authService.getCurrentUser();
        const parsedSavedUser = savedUser ? JSON.parse(savedUser) : null;
        const nextUser = normalizeUser(userData.user || parsedSavedUser);
        setUser(nextUser);
        if (nextUser) {
          localStorage.setItem('user', JSON.stringify(nextUser));
        }
      } catch (err) {
        console.error('Auth check failed:', err);
        logout();
      }
    }
    setLoading(false);
  };

  const login = async (email, password) => {
    try {
      setError('');
      const data = await authService.login(email, password);
      const nextUser = normalizeUser(data.user);
      
      // Save token and user
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(nextUser));
      
      setUser(nextUser);
      return { success: true, user: nextUser };
    } catch (err) {
      const message = getApiErrorMessage(err, 'Login failed');
      setError(message);
      return { success: false, error: message };
    }
  };

  const signup = async (userData) => {
    try {
      setError('');
      const data = await authService.register(userData);
      const nextUser = normalizeUser(data.user);
      
      // Auto-login after signup
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(nextUser));
      
      setUser(nextUser);
      return { success: true, user: nextUser };
    } catch (err) {
      const message = getApiErrorMessage(err, 'Registration failed');
      setError(message);
      return { success: false, error: message };
    }
  };

  const logout = () => {
    authService.logout();
    setUser(null);
    setError('');
  };

  const updateUser = (userData) => {
    const nextUser = normalizeUser(userData);
    setUser(nextUser);
    localStorage.setItem('user', JSON.stringify(nextUser));
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        error,
        login,
        signup,
        logout,
        updateUser
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};