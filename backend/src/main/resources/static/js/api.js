/* Thin fetch layer: auth header, error normalisation, token lifecycle.
 *
 * Every network failure becomes an ApiError with a `kind`, so views can
 * distinguish "signed out" from "backend unreachable" from "no data yet".
 * Collapsing those into a generic failure is how a dashboard ends up showing
 * an empty ward when the real problem is an expired token.
 */

const TOKEN_KEY = 'vitalsync.token';

export class ApiError extends Error {
  constructor(kind, message, status) {
    super(message);
    this.kind = kind;       // 'auth' | 'network' | 'server' | 'notfound'
    this.status = status;
  }
}

let token = null;
try {
  token = localStorage.getItem(TOKEN_KEY);
} catch {
  // Private browsing or blocked storage: run without persistence.
  token = null;
}

export function getToken() {
  return token;
}

export function setToken(value) {
  token = value;
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* non-fatal; session simply will not survive a reload */
  }
}

const listeners = new Set();
export function onAuthLost(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

async function request(path, { method = 'GET', body } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError('network', 'Backend unreachable', 0);
  }

  if (res.status === 401 || res.status === 403) {
    setToken(null);
    listeners.forEach((fn) => fn());
    throw new ApiError('auth', 'Session expired', res.status);
  }
  if (res.status === 404) {
    throw new ApiError('notfound', 'Not found', 404);
  }
  // 204 is a legitimate "nothing yet", not an error: a patient with no
  // assessment has not failed, they simply have not been analysed.
  if (res.status === 204) return null;

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const parsed = await res.json();
      if (parsed && parsed.message) detail = parsed.message;
    } catch { /* body was not json */ }
    throw new ApiError('server', detail, res.status);
  }

  return res.json();
}

export const api = {
  async login(username, password) {
    const res = await fetch('/api/v1/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new ApiError('auth', 'Invalid credentials', res.status);
    const data = await res.json();
    setToken(data.token);
    return data;
  },

  logout() {
    setToken(null);
  },

  ward: (sparkline = 20) => request(`/api/v1/ward?sparkline=${sparkline}`),
  vitals: (id, limit = 50) =>
    request(`/api/v1/patients/${encodeURIComponent(id)}/vitals?limit=${limit}`),
  latestRisk: (id) =>
    request(`/api/v1/patients/${encodeURIComponent(id)}/risk/latest`),
  analyze: (id) =>
    request(`/api/v1/patients/${encodeURIComponent(id)}/analyze`, { method: 'POST' }),
  systemHealth: () => request('/api/v1/system/health'),
  modelCard: () => request('/api/v1/system/providers'),
};
