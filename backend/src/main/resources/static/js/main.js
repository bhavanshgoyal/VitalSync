/* Bootstrap: routing, polling, theme, auth, keyboard.
 *
 * Hash routing rather than a router library: three views do not justify a
 * dependency, and hash URLs keep the back button and deep links working with
 * no server-side route configuration.
 */

import { ApiError, api, getToken, onAuthLost } from './api.js';
import { destroyAll } from './charts.js';
import * as ward from './views/ward.js';
import * as patient from './views/patient.js';
import * as system from './views/system.js';

const POLL_MS = 5000;
const THEME_KEY = 'vitalsync.theme';

const state = { route: null, timer: null, rendering: false };

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ theme */

function applyTheme(theme) {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* ignore */ }
  // Charts cache theme colours at construction, so they must be rebuilt.
  destroyAll();
}

function initTheme() {
  let saved = 'system';
  try { saved = localStorage.getItem(THEME_KEY) || 'system'; } catch { /* ignore */ }
  applyTheme(saved);

  $('theme-btn').addEventListener('click', () => {
    const order = ['system', 'light', 'dark'];
    let current = 'system';
    try { current = localStorage.getItem(THEME_KEY) || 'system'; } catch { /* ignore */ }
    applyTheme(order[(order.indexOf(current) + 1) % order.length]);
    render();
  });
}

/* ------------------------------------------------------------- connection */

function setConn(stateName, text) {
  const el = $('conn');
  el.dataset.state = stateName;
  el.textContent = text;
}

/** Screen-reader announcement, throttled to meaningful changes only. */
let lastAnnouncement = '';
function announce(message) {
  if (!message || message === lastAnnouncement) return;
  lastAnnouncement = message;
  $('live-region').textContent = message;
}

/* ------------------------------------------------------------------ views */

function parseRoute() {
  const hash = location.hash || '#/ward';
  const m = hash.match(/^#\/patient\/([^/]+)$/);
  if (m) return { name: 'patient', id: decodeURIComponent(m[1]) };
  if (hash.startsWith('#/system')) return { name: 'system' };
  return { name: 'ward' };
}

function showView(name) {
  ['ward', 'patient', 'system'].forEach((v) => {
    $(`view-${v}`).hidden = v !== name;
  });
  document.querySelectorAll('.nav-link').forEach((link) => {
    const active = link.dataset.route === name
      || (name === 'patient' && link.dataset.route === 'ward');
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

function navigate(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

async function render() {
  if (state.rendering) return;          // a slow poll must not stack
  if (!getToken()) return showLogin();

  state.rendering = true;
  const route = parseRoute();
  state.route = route;
  showView(route.name);

  try {
    let message;
    if (route.name === 'ward') message = await ward.render(navigate);
    else if (route.name === 'patient') message = await patient.render(navigate, route.id);
    else message = await system.render();

    setConn('live', 'live');
    announce(message);
  } catch (err) {
    if (err instanceof ApiError && err.kind === 'auth') {
      showLogin('Session expired. Sign in again.');
    } else if (err instanceof ApiError && err.kind === 'notfound') {
      $(`view-${route.name}`).innerHTML =
        '<div class="empty">That patient does not exist.</div>';
      setConn('live', 'live');
    } else {
      setConn('down', 'disconnected');
    }
  } finally {
    state.rendering = false;
  }
}

/* ------------------------------------------------------------------- auth */

function showLogin(message) {
  stopPolling();
  $('app').hidden = true;
  $('login').hidden = false;
  setConn('', 'signed out');
  if (message) {
    const el = $('login-error');
    el.textContent = message;
    el.hidden = false;
  }
}

function showApp() {
  $('login').hidden = true;
  $('app').hidden = false;
  $('login-error').hidden = true;
  startPolling();
  render();
}

function startPolling() {
  stopPolling();
  state.timer = setInterval(() => {
    // Polling a hidden tab wastes the backend and the battery.
    if (!document.hidden) render();
  }, POLL_MS);
}

function stopPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

/* -------------------------------------------------------------- keyboard */

function initKeyboard() {
  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === '1') navigate('#/ward');
    else if (e.key === '2') navigate('#/system');
    else if (e.key === 'r') render();
    else if (e.key === 'Escape' && state.route && state.route.name === 'patient') {
      navigate('#/ward');
    }
  });
}

/* ------------------------------------------------------------------ init */

function init() {
  initTheme();
  initKeyboard();

  onAuthLost(() => showLogin('Session expired. Sign in again.'));

  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type=submit]');
    btn.disabled = true;
    try {
      await api.login($('username').value, $('password').value);
      showApp();
    } catch (err) {
      const el = $('login-error');
      el.textContent = err.message || 'Sign in failed';
      el.hidden = false;
    } finally {
      btn.disabled = false;
    }
  });

  $('signout-btn').addEventListener('click', () => {
    api.logout();
    showLogin();
  });

  $('refresh-btn').addEventListener('click', render);
  window.addEventListener('hashchange', render);

  // Refresh immediately on returning to the tab rather than waiting a cycle.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && getToken()) render();
  });

  document.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', () =>
      navigate(link.dataset.route === 'system' ? '#/system' : '#/ward'));
  });

  if (getToken()) showApp();
  else showLogin();
}

document.addEventListener('DOMContentLoaded', init);
