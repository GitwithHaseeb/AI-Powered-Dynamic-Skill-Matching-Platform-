import { describe, expect, it } from 'vitest';
import { taskAssignedToUser } from './tasks.js';

const user = { id: '69e07f87cb6b02a1afd44826', email: 'Rahim586@Gmail.com', name: 'Rahim' };

describe('taskAssignedToUser', () => {
  it('returns false for missing task or user', () => {
    expect(taskAssignedToUser(null, user)).toBe(false);
    expect(taskAssignedToUser({ assigned_to: user.id }, null)).toBe(false);
  });

  it('trusts the server flag over every other field', () => {
    expect(taskAssignedToUser({ is_assigned_to_me: true, assigned_to: 'someone-else' }, user)).toBe(true);
    expect(taskAssignedToUser({ is_assigned_to_me: false, assigned_to: user.id }, user)).toBe(false);
  });

  it('matches by id, accepting either id or _id on the user', () => {
    expect(taskAssignedToUser({ assigned_to: user.id }, user)).toBe(true);
    expect(taskAssignedToUser({ assigned_to: user.id }, { _id: user.id })).toBe(true);
    expect(taskAssignedToUser({ assigned_to: ` ${user.id} ` }, user)).toBe(true);
  });

  it('matches email case-insensitively', () => {
    expect(taskAssignedToUser({ assigned_to: 'rahim586@gmail.com' }, user)).toBe(true);
  });

  it('matches display name exactly (case-sensitive)', () => {
    expect(taskAssignedToUser({ assigned_to: 'Rahim' }, user)).toBe(true);
    expect(taskAssignedToUser({ assigned_to: 'rahim' }, user)).toBe(false);
  });

  it('does not match another developer or an unassigned task', () => {
    expect(taskAssignedToUser({ assigned_to: '69e07f87cb6b02a1afd44827' }, user)).toBe(false);
    expect(taskAssignedToUser({ assigned_to: null }, user)).toBe(false);
    expect(taskAssignedToUser({}, { id: '', email: '', name: '' })).toBe(false);
  });
});
