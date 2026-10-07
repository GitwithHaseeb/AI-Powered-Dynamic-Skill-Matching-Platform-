import { expect, test } from '@playwright/test';
import { login, mockApi, users } from './support/mockApi.js';

test('team members list shows each developer once and never a manager', async ({ page }) => {
  const developers = [
    { id: 'd1', full_name: 'Zain', email: 'zain.dev@gmail.com', role: 'developer', skills: ['React', 'FastAPI'] },
    // Same person stored twice (duplicate account) — must be collapsed by email.
    { id: 'd1-copy', full_name: 'Zain', email: 'ZAIN.dev@gmail.com', role: 'developer', skills: ['React'] },
    { id: 'pm', full_name: 'Ghania Tanveer', email: 'ghania@example.com', role: 'manager', skills: [] },
    { id: 'd2', full_name: 'Hina', email: 'hina618@gmail.com', role: 'developer', skills: ['Figma'] },
  ];
  await mockApi(page, {
    accounts: { [users.admin.email]: { password: 'admin-pass-1', user: users.admin } },
    developers,
  });

  await login(page, users.admin.email, 'admin-pass-1');
  await expect(page).toHaveURL(/\/dashboard$/);

  await expect(page.getByRole('heading', { name: 'Team Members' })).toBeVisible();
  await expect(page.getByText('2 developers', { exact: true })).toBeVisible();
  const member = (name) => page.getByRole('heading', { level: 3, name, exact: true });
  await expect(member('Hina')).toBeVisible();
  await expect(member('Zain')).toHaveCount(1);
  await expect(member('Ghania Tanveer')).toHaveCount(0);
});

test('developer dashboard counts only tasks assigned to them', async ({ page }) => {
  const tasks = [
    { id: 't1', title: 'Build login page', status: 'in_progress', assigned_to: users.developer.id, project_id: 'p1' },
    { id: 't2', title: 'Write API tests', status: 'assigned', assigned_to: users.developer.email, project_id: 'p1' },
    { id: 't3', title: 'Design schema', status: 'in_progress', assigned_to: 'someone-else', project_id: 'p1' },
  ];
  await mockApi(page, {
    accounts: { [users.developer.email]: { password: 'dev-pass-1', user: users.developer } },
    tasks,
    projects: [{ id: 'p1', title: 'Online Toy Shop', status: 'in_progress', assigned_team: [users.developer.id] }],
  });

  await login(page, users.developer.email, 'dev-pass-1');
  await expect(page).toHaveURL(/\/developer$/);
  await expect(page.getByText(/2 assigned to you/i)).toBeVisible();
  await expect(page.getByText('Design schema')).toHaveCount(0);
});
