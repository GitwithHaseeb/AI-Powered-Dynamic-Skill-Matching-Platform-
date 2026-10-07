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

test('dashboard shows "—" instead of an invented match accuracy when no AI scores exist', async ({ page }) => {
  await mockApi(page, {
    accounts: { [users.admin.email]: { password: 'admin-pass-1', user: users.admin } },
  });
  // Analytics has task data, but /projects/stats/summary has no avg_match_score_pct.
  await page.route('**/api/analytics/dashboard**', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ tasks: { completion_rate_pct: 40, open_or_active: 7, total: 12 }, skill_utilization_pct: 90 }),
    })
  );

  await login(page, users.admin.email, 'admin-pass-1');
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText('No AI match scores yet')).toBeVisible();
  await expect(page.getByText('Open Tasks')).toBeVisible();
  await expect(page.getByText('% faster')).toHaveCount(0);
});

test('analytics shows "—" (not 0%) when the selected window has no task activity', async ({ page }) => {
  await mockApi(page, {
    accounts: { [users.manager.email]: { password: 'pm-pass-1', user: users.manager } },
  });
  await page.route('**/api/analytics/dashboard**', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        period: 'month',
        tasks: { total: 0, completed: 0, open_or_active: 0, completion_rate_pct: 0, scoped_to_period: true },
        skill_utilization_pct: 91.9,
        team_performance: [{ project_id: 'p1', project_title: 'Toy Shop', tasks_total: 0, task_completion_pct: 0 }],
      }),
    })
  );

  await login(page, users.manager.email, 'pm-pass-1');
  await page.goto('/analytics');
  await expect(page.getByText('Completion Rate', { exact: true })).toBeVisible();
  await expect(page.getByText(/No task activity in the last 30 days/)).toHaveCount(2);
  // The utilization card is not time-scoped, so it still shows its value.
  await expect(page.getByText('91.9%').first()).toBeVisible();
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
