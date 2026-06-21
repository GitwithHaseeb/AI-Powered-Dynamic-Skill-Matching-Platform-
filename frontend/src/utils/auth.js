export const normalizeRole = (role) => {
  const value = String(role || '').trim().toLowerCase();
  if (!value) return '';

  if (['manager', 'project_manager', 'project manager', 'pm'].includes(value)) {
    return 'manager';
  }
  if (['developer', 'dev'].includes(value)) {
    return 'developer';
  }
  if (['admin', 'administrator'].includes(value)) {
    return 'admin';
  }
  return value;
};

export const normalizeUser = (user) => {
  if (!user || typeof user !== 'object') return null;
  return {
    ...user,
    role: normalizeRole(user.role),
    skills: Array.isArray(user.skills) ? user.skills : [],
  };
};

export const getDefaultRouteForRole = (role) => {
  const normalized = normalizeRole(role);
  if (normalized === 'developer') return '/developer';
  if (normalized === 'manager') return '/manager';
  if (normalized === 'admin') return '/dashboard';
  return '/dashboard';
};
