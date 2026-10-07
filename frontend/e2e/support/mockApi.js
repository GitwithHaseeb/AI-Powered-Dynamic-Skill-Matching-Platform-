/**
 * Route every `/api/*` request to an in-memory fake of the FastAPI backend.
 * Tests pass only the data they care about; everything else gets an empty response.
 */

export const users = {
  developer: { id: 'dev-1', name: 'Zain', email: 'zain.dev@gmail.com', role: 'developer', skills: ['React'] },
  manager: { id: 'pm-1', name: 'Ghania Tanveer', email: 'ghania@example.com', role: 'manager', skills: [] },
  admin: { id: 'admin-1', name: 'Demo Admin', email: 'admin@demo.local', role: 'admin', skills: [] },
};

const json = (route, body, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

/**
 * @param {import('@playwright/test').Page} page
 * @param {object} opts
 * @param {Record<string, {password: string, user: object}>} [opts.accounts] email -> credentials
 * @param {object[]} [opts.tasks]       GET /tasks/
 * @param {object[]} [opts.projects]    GET /projects/
 * @param {object[]} [opts.developers]  GET /users/directory/developers
 */
export async function mockApi(page, { accounts = {}, tasks = [], projects = [], developers = [] } = {}) {
  const calls = [];
  let currentUser = null;

  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^\/api/, '').replace(/\/$/, '') || '/';
    const method = req.method();
    calls.push(`${method} ${path}`);

    if (method === 'POST' && path === '/auth/login') {
      const { email, password } = req.postDataJSON();
      const account = accounts[String(email).toLowerCase()];
      if (!account || account.password !== password) {
        return json(route, { detail: 'Incorrect email or password' }, 401);
      }
      currentUser = account.user;
      return json(route, { access_token: `token-${account.user.id}`, token_type: 'bearer', user: account.user });
    }

    if (method === 'GET' && path === '/auth/me') {
      const auth = req.headers()['authorization'] || '';
      const id = auth.replace('Bearer token-', '');
      const user = currentUser || Object.values(accounts).map((a) => a.user).find((u) => u.id === id);
      return user ? json(route, user) : json(route, { detail: 'Not authenticated' }, 401);
    }

    if (method === 'GET' && path === '/tasks') return json(route, tasks);
    if (method === 'GET' && (path === '/projects' || path === '/projects/directory/running')) return json(route, projects);
    if (method === 'GET' && (path === '/users/directory/developers' || path === '/users/developers')) {
      return json(route, developers);
    }
    if (method === 'GET' && (path === '/projects/stats/summary' || path.startsWith('/analytics'))) {
      return json(route, {});
    }

    return json(route, method === 'GET' ? [] : {});
  });

  return { calls };
}

/** Fill and submit the login form. */
export async function login(page, email, password) {
  await page.goto('/login');
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
}
