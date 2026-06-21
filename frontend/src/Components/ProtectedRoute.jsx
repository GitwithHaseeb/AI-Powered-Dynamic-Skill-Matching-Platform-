import React from 'react';
import { Navigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { useAuth } from '../context/AuthContext.jsx';
import { getDefaultRouteForRole, normalizeRole } from '../utils/auth.js';

/**
 * @param {object} props
 * @param {React.ReactNode} props.children
 * @param {string} [props.requiredRole] single role
 * @param {string[]} [props.allowedRoles] any of these roles
 */
const ProtectedRoute = ({ children, requiredRole, allowedRoles }) => {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="40vh">
        <CircularProgress />
      </Box>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const roles = allowedRoles ? allowedRoles.map(normalizeRole) : (requiredRole ? [normalizeRole(requiredRole)] : null);
  const userRole = normalizeRole(user.role);
  if (roles && !roles.includes(userRole)) {
    return <Navigate to={getDefaultRouteForRole(userRole)} replace />;
  }

  return children;
};

export default ProtectedRoute;
