import { expect, test } from '@playwright/test';
import { login, mockApi, users } from './support/mockApi.js';

const accounts = {
  [users.developer.email]: { password: 'dev-pass-1', user: users.developer },
  [users.manager.email]: { password: 'pm-pass-1', user: users.manager },
  [users.admin.email]: { password: 'admin-pass-1', user: users.admin },
};

test.describe('authentication', () => {
  test('protected pages redirect a signed-out visitor to login', async ({ page }) => {
    await mockApi(page, { accounts });
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: /welcome back/i })).toBeVisible();
  });

  test('wrong password shows the API error and keeps the user on login', async ({ page }) => {
    await mockApi(page, { accounts });
    await login(page, users.developer.email, 'not-the-password');
    await expect(page.getByText(/incorrect email or password/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
    expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull();
  });

  for (const [role, landing] of [
    ['developer', /\/developer$/],
    ['manager', /\/manager$/],
    ['admin', /\/dashboard$/],
  ]) {
    test(`${role} lands on their own dashboard after login`, async ({ page }) => {
      await mockApi(page, { accounts });
      const { email } = users[role];
      await login(page, email, accounts[email].password);
      await expect(page).toHaveURL(landing);
    });
  }

  test('session survives a page reload', async ({ page }) => {
    await mockApi(page, { accounts });
    await login(page, users.developer.email, 'dev-pass-1');
    await expect(page).toHaveURL(/\/developer$/);
    await page.reload();
    await expect(page).toHaveURL(/\/developer$/);
  });

  test('a developer cannot open the manager dashboard', async ({ page }) => {
    await mockApi(page, { accounts });
    await login(page, users.developer.email, 'dev-pass-1');
    await expect(page).toHaveURL(/\/developer$/);
    await page.goto('/manager');
    await expect(page).toHaveURL(/\/developer$/);
  });
});
