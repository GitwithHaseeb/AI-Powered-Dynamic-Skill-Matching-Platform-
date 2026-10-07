import { describe, expect, it } from 'vitest';
import { getDefaultRouteForRole, normalizeRole, normalizeUser } from './auth.js';

describe('normalizeRole', () => {
  it.each([
    ['PM', 'manager'],
    ['Project Manager', 'manager'],
    ['project_manager', 'manager'],
    [' Dev ', 'developer'],
    ['Administrator', 'admin'],
    ['tester', 'tester'],
    ['', ''],
    [null, ''],
  ])('%j -> %j', (input, expected) => {
    expect(normalizeRole(input)).toBe(expected);
  });
});

describe('normalizeUser', () => {
  it('returns null for non-objects', () => {
    expect(normalizeUser(null)).toBeNull();
    expect(normalizeUser('user')).toBeNull();
  });

  it('normalises role and guarantees a skills array', () => {
    expect(normalizeUser({ name: 'Zain', role: 'Dev', skills: 'React' })).toEqual({
      name: 'Zain',
      role: 'developer',
      skills: [],
    });
  });
});

describe('getDefaultRouteForRole', () => {
  it.each([
    ['developer', '/developer'],
    ['pm', '/manager'],
    ['admin', '/dashboard'],
    ['unknown', '/dashboard'],
  ])('%s -> %s', (role, route) => {
    expect(getDefaultRouteForRole(role)).toBe(route);
  });
});
