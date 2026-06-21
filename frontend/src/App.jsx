import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { ThemeProvider } from './context/ThemeContext.jsx';
import ProtectedRoute from './Components/ProtectedRoute.jsx';
import AppLayout from './Components/AppLayout.jsx';
import HomeDashboard from './Components/HomeDashboard.jsx';
import Login from './Components/Login.jsx';
import Signup from './Components/Signup.jsx';
import ManagerDashboard from './Components/ManagerDashboard.jsx';
import DeveloperDashboard from './Components/DeveloperDashboard.jsx';
import AnalyticsDashboard from './Components/AnalyticsDashboard.jsx';
import DevelopersDirectory from './Components/DevelopersDirectory.jsx';
import ProjectsDirectory from './Components/ProjectsDirectory.jsx';
import { getDefaultRouteForRole } from './utils/auth.js';

const HomeRedirect = () => {
  const { user, loading } = useAuth();
  if (loading) return null;
  return <Navigate to={user ? getDefaultRouteForRole(user.role) : '/login'} replace />;
};

const PublicOnlyRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) {
    return <Navigate to={getDefaultRouteForRole(user.role)} replace />;
  }
  return children;
};

function App() {
  return (
    <Router>
      <AuthProvider>
        <ThemeProvider>
          <div className="min-h-screen bg-gray-50">
            <Routes>
              <Route path="/login" element={<PublicOnlyRoute><Login /></PublicOnlyRoute>} />
              <Route path="/signup" element={<PublicOnlyRoute><Signup /></PublicOnlyRoute>} />

              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute>
                    <AppLayout>
                      <HomeDashboard />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/manager"
                element={
                  <ProtectedRoute allowedRoles={['manager']}>
                    <AppLayout>
                      <ManagerDashboard />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/developer"
                element={
                  <ProtectedRoute requiredRole="developer">
                    <AppLayout>
                      <DeveloperDashboard />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/analytics"
                element={
                  <ProtectedRoute allowedRoles={['manager', 'admin', 'developer']}>
                    <AppLayout>
                      <AnalyticsDashboard />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/developers"
                element={
                  <ProtectedRoute allowedRoles={['manager', 'developer', 'admin']}>
                    <AppLayout>
                      <DevelopersDirectory />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/projects"
                element={
                  <ProtectedRoute allowedRoles={['manager', 'developer', 'admin']}>
                    <AppLayout>
                      <ProjectsDirectory />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/admin"
                element={
                  <ProtectedRoute requiredRole="admin">
                    <AppLayout>
                      <ManagerDashboard variant="admin" />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route path="/" element={<HomeRedirect />} />
            </Routes>
          </div>
        </ThemeProvider>
      </AuthProvider>
    </Router>
  );
}

export default App;
