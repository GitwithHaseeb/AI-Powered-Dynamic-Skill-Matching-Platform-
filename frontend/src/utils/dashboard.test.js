import { describe, expect, it } from 'vitest';
import {
  displayRoleFor,
  formatDeadline,
  formatProjectStatus,
  inferDeveloperType,
  projectTeamMemberCount,
  projectsListPath,
  roleBadgeClass,
} from './dashboard.js';

describe('projectsListPath', () => {
  it.each([
    ['developer', '/projects'],
    ['PM', '/projects'],
    ['administrator', '/projects'],
    ['guest', '/dashboard'],
    [undefined, '/dashboard'],
  ])('%s -> %s', (role, path) => {
    expect(projectsListPath(role)).toBe(path);
  });
});

describe('projectTeamMemberCount', () => {
  it('counts unique, non-empty member ids', () => {
    expect(projectTeamMemberCount({ assigned_team: ['a', 'b', 'a', '', null] })).toBe(2);
  });

  it('falls back to final_team, then team_size', () => {
    expect(projectTeamMemberCount({ final_team: ['x'] })).toBe(1);
    expect(projectTeamMemberCount({ team_size: 4.7 })).toBe(4);
    expect(projectTeamMemberCount({ team_size: -2 })).toBe(0);
    expect(projectTeamMemberCount({})).toBe(0);
  });
});

describe('formatProjectStatus', () => {
  it('maps known statuses and humanises unknown ones', () => {
    expect(formatProjectStatus('in_progress')).toBe('In Progress');
    expect(formatProjectStatus('on_hold')).toBe('On Hold');
    expect(formatProjectStatus('needs_review')).toBe('needs review');
    expect(formatProjectStatus('')).toBe('—');
  });
});

describe('formatDeadline', () => {
  it('returns a dash for empty input', () => {
    expect(formatDeadline(null)).toBe('—');
  });

  it('falls back to the raw date prefix for unparseable input', () => {
    expect(formatDeadline('2026-13-45 not a date')).toBe('2026-13-45');
  });

  it('formats a valid date with the locale formatter', () => {
    const iso = '2026-06-01T00:00:00';
    expect(formatDeadline(iso)).toBe(new Date(iso).toLocaleDateString());
  });
});

describe('inferDeveloperType', () => {
  it.each([
    [['React', 'FastAPI'], 'Full Stack Developer'],
    [['Django', 'PostgreSQL'], 'Backend Developer'],
    [['Vue'], 'Frontend Developer'],
    [['Figma', 'UX research'], 'UI Designer'],
    [['Selenium', 'Manual Testing'], 'Tester'],
    [[{ skill_name: 'Node.js' }], 'Backend Developer'],
    [[], 'Frontend Developer'],
  ])('%j -> %s', (skills, expected) => {
    expect(inferDeveloperType(skills)).toBe(expected);
  });
});

describe('displayRoleFor', () => {
  it('uses the manual override when a name is listed', () => {
    expect(displayRoleFor({ name: '  Aima ', skills: ['React'] })).toBe('Backend Developer');
  });

  it('otherwise infers from skills', () => {
    expect(displayRoleFor({ name: 'Zain', skills: ['React', 'FastAPI'] })).toBe('Full Stack Developer');
  });
});

describe('roleBadgeClass', () => {
  it('gives each role its own colour and a default', () => {
    expect(roleBadgeClass('Full Stack Developer')).toContain('purple');
    expect(roleBadgeClass('Backend Developer')).toContain('emerald');
    expect(roleBadgeClass('Tester')).toContain('amber');
    expect(roleBadgeClass(undefined)).toContain('indigo');
  });
});
