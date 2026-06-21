// src/components/Login.jsx
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { getDefaultRouteForRole } from '../utils/auth.js';
import logoIcon from '../assets/skill-mapping-logo.svg';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
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

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100 p-4">
      <div className="w-full max-w-6xl flex flex-col lg:flex-row bg-white rounded-3xl shadow-xl overflow-hidden">
        {/* Left side - Login Form */}
        <div className="w-full lg:w-1/2 p-8 lg:p-12 flex flex-col justify-center">
          <div className="mb-10">
            <h1 className="text-4xl font-bold text-gray-900 mb-2">Welcome Back!</h1>
            <p className="text-gray-600">Enter your email and password</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
                Email address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-4 border border-gray-300 rounded-xl text-gray-900 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-gray-800 focus:border-transparent transition-all bg-gray-50"
                placeholder="Enter Email Address"
                required
                disabled={isLoading}
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-4 border border-gray-300 rounded-xl text-gray-900 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-gray-800 focus:border-transparent transition-all bg-gray-50"
                placeholder="Password"
                required
                disabled={isLoading}
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg">
                {error}
              </div>
            )}

            <button 
              type="submit" 
              disabled={isLoading}
              className={`w-full ${
                isLoading ? 'bg-gray-400' : 'bg-gray-900 hover:bg-gray-800'
              } text-white font-semibold py-4 px-4 rounded-xl transition-all duration-300 shadow-md hover:shadow-lg flex items-center justify-center`}
            >
              {isLoading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                  Signing in...
                </>
              ) : (
                'Sign in'
              )}
            </button>
          </form>

          <div className="mt-8 text-center">
            <p className="text-gray-600">
              Don't have an account?{' '}
              <Link to="/signup" className="font-medium text-gray-900 hover:text-gray-700 transition-colors">
                Sign up
              </Link>
            </p>
          </div>
        </div>

        {/* Right side - Hero Section */}
        <div className="w-full lg:w-1/2 bg-gradient-to-br from-gray-900 to-gray-800 p-8 lg:p-12 flex flex-col justify-center items-center text-white relative overflow-hidden">
          <div className="max-w-md text-center space-y-4">
            <img src={logoIcon} alt="Skill Mapping logo" className="mx-auto h-24 w-24 rounded-2xl mb-2" />
            <p className="text-base uppercase tracking-[0.2em] text-gray-300">Skill Mapping</p>
            <h2 className="text-3xl font-bold">AI-Powered Skill Matching</h2>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;