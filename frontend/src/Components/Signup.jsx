// src/components/Signup.jsx
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { getDefaultRouteForRole } from '../utils/auth.js';
import AuthHero from './ui/AuthHero.jsx';

const Signup = () => {
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    password: '',
    role: 'developer',
    department: '',
    agreeTerms: false
  });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { signup } = useAuth();
  const navigate = useNavigate();

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    if (!formData.agreeTerms) {
      setError('You must agree to the Terms & Conditions');
      setIsLoading(false);
      return;
    }

    try {
      const userData = {
        name: `${formData.firstName} ${formData.lastName}`.trim(),
        email: formData.email,
        password: formData.password,
        role: formData.role,
        department: formData.department || 'General'
      };

      const result = await signup(userData);
      
      if (result.success) {
        navigate(getDefaultRouteForRole(result.user?.role), { replace: true });
      } else {
        setError(result.error);
      }
    } catch (err) {
      setError('Registration failed. Please try again.');
      console.error('Signup error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const inputClass =
    'w-full px-4 py-3.5 rounded-xl border border-slate-200 bg-slate-50/70 text-slate-900 placeholder-slate-400 transition-all duration-200 ease-smooth hover:border-slate-300 focus:outline-none focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/15 disabled:opacity-60';

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50/60 p-4">
      <div className="w-full max-w-6xl flex flex-col lg:flex-row bg-white rounded-3xl shadow-2xl shadow-slate-900/10 ring-1 ring-slate-900/5 overflow-hidden animate-scale-in">
        {/* Left side - Signup Form */}
        <div className="w-full lg:w-1/2 p-8 sm:p-12 lg:p-16 flex flex-col justify-center animate-fade-in-up">
          <div className="mb-8">
            <h1 className="text-4xl font-bold text-slate-900 mb-2">Create an account</h1>
            <p className="text-slate-500">
              Already have an account?{' '}
              <Link to="/login" className="font-semibold text-blue-600 hover:text-blue-700 transition-colors">
                Log in
              </Link>
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label htmlFor="firstName" className="block text-sm font-medium text-slate-700 mb-2">
                  First name
                </label>
                <input
                  id="firstName"
                  name="firstName"
                  type="text"
                  value={formData.firstName}
                  onChange={handleChange}
                  className={inputClass}
                  placeholder="First name"
                  required
                  disabled={isLoading}
                />
              </div>

              <div>
                <label htmlFor="lastName" className="block text-sm font-medium text-slate-700 mb-2">
                  Last name
                </label>
                <input
                  id="lastName"
                  name="lastName"
                  type="text"
                  value={formData.lastName}
                  onChange={handleChange}
                  className={inputClass}
                  placeholder="Last name"
                  required
                  disabled={isLoading}
                />
              </div>
            </div>

            <div>
              <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-2">
                Email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                value={formData.email}
                onChange={handleChange}
                className={inputClass}
                placeholder="Enter your email"
                required
                disabled={isLoading}
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-2">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                value={formData.password}
                onChange={handleChange}
                className={inputClass}
                placeholder="Create a strong password"
                required
                disabled={isLoading}
              />
            </div>

            <div>
              <label htmlFor="role" className="block text-sm font-medium text-slate-700 mb-2">
                Role
              </label>
              <select
                id="role"
                name="role"
                value={formData.role}
                onChange={handleChange}
                className={inputClass}
                disabled={isLoading}
              >
                <option value="developer">Developer</option>
                <option value="manager">Manager</option>
                <option value="admin">Admin (CEO — system account only)</option>
              </select>
              <p className="text-xs text-gray-500 mt-1">
                CEO admin is created in the database; new admin sign-ups are not allowed.
              </p>
            </div>

            <div>
              <label htmlFor="department" className="block text-sm font-medium text-slate-700 mb-2">
                Department (Optional)
              </label>
              <input
                id="department"
                name="department"
                type="text"
                value={formData.department}
                onChange={handleChange}
                className={inputClass}
                placeholder="e.g., Computer Science, Engineering"
                disabled={isLoading}
              />
            </div>

            <div className="flex items-start">
              <input
                id="agreeTerms"
                name="agreeTerms"
                type="checkbox"
                checked={formData.agreeTerms}
                onChange={handleChange}
                className="h-5 w-5 mt-0.5 rounded border-slate-300 accent-blue-600 cursor-pointer"
                required
                disabled={isLoading}
              />
              <label htmlFor="agreeTerms" className="ml-3 text-sm text-slate-600">
                <span>I agree to the{' '}</span>
                <a href="#" className="text-blue-600 hover:text-blue-700 font-medium underline-offset-2 hover:underline">
                  Terms & Conditions
                </a>
              </label>
            </div>

            {error && (
              <div role="alert" className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm animate-scale-in">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="group relative w-full overflow-hidden rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 py-3.5 px-4 font-semibold text-white shadow-lg shadow-blue-600/25 hover:shadow-xl hover:shadow-blue-600/30 disabled:opacity-70 flex items-center justify-center"
            >
              {isLoading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                  Creating account...
                </>
              ) : (
                'Create account'
              )}
            </button>
          </form>
        </div>

        <AuthHero
          title="Join the Skill Mapping platform."
          subtitle="Set up your profile once — get matched to the projects that fit your skills."
        />
      </div>
    </div>
  );
};

export default Signup;