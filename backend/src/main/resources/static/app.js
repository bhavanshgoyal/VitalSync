/* VitalSync clinician dashboard.
 *
 * Charts are one-measure-per-figure on purpose. Heart rate (bpm) and SpO2 (%)
 * live on different scales; putting them on twin y-axes would let the axis
 * ranges manufacture an apparent correlation, so each measure gets its own
 * figure with a single shared reading index along x.
 */

const API = {
  token: '/api/v1/auth/token',
  patients: '/api/v1/patients',
  vitals: (id, n) => `/api/v1/patients/${encodeURIComponent(id)}/vitals?limit=${n}`,
  latestRisk: (id) => `/api/v1/patients/${encodeURIComponent(id)}/risk/latest`,
  analyze: (id) => `/api/v1/patients/${encodeURIComponent(id)}/analyze`,
};

const POLL_MS = 5000;
const state = { token: null, patientId: null, limit: 50, charts: {}, timer: null };

/* ------------------------------------------------------------------ helpers */

const $ = (id) => document.getElementById(id);

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function setConn(text, cls) {
  const el = $('conn-status');
  el.textContent = text;
  el.className = `pill ${cls}`;
}

async function api(url, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    state.token = null;
    localStorage.removeItem('vitalsync.token');
    showLogin('Session expired. Sign in again.');
    throw new Error('unauthorized');
  }
  if (res.status === 204) return null;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function fmt(value, digits = 0) {
  return (value === null || value === undefined || Number.isNaN(value))
    ? '–'
    : Number(value).toFixed(digits);
}

/* --------------------------------------------------------------------- auth */

function showLogin(message) {
  $('login-panel').hidden = false;
  $('app').hidden = true;
  if (message) {
    $('login-error').textContent = message;
    $('login-error').hidden = false;
  }
  setConn('signed out', 'pill-muted');
}

function showApp() {
  $('login-panel').hidden = true;
  $('app').hidden = false;
  $('login-error').hidden = true;
}

async function login(event) {
  event.preventDefault();
  try {
    const body = JSON.stringify({
      username: $('username').value,
      password: $('password').value,
    });
    const res = await fetch(API.token, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });
    if (!res.ok) throw new Error('Invalid credentials');
    const data = await res.json();
    state.token = data.token;
    localStorage.setItem('vitalsync.token', data.token);
    showApp();
    await boot();
  } catch (e) {
    $('login-error').textContent = e.message;
    $('login-error').hidden = false;
  }
}

/* ------------------------------------------------------------------- charts */

function baseOptions(yLabel) {
  const text = css('--text-secondary');
  const muted = css('--text-muted');
  const grid = css('--grid');

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    // Crosshair-style shared tooltip: hovering anywhere in the column reports
    // the reading, rather than requiring the pointer to land on the 8px dot.
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        display: false, // enabled per-chart only where >= 2 series exist
        labels: { color: text, boxWidth: 10, boxHeight: 10, usePointStyle: true },
      },
      tooltip: {
        backgroundColor: css('--surface-2'),
        titleColor: css('--text-primary'),
        bodyColor: text,
        borderColor: css('--border'),
        borderWidth: 1,
        padding: 10,
        displayColors: true,
        usePointStyle: true,
      },
    },
    scales: {
      x: {
        ticks: { color: muted, maxRotation: 0, autoSkipPadding: 18, font: { size: 10 } },
        grid: { display: false },
        border: { color: grid },
      },
      y: {
        title: { display: Boolean(yLabel), text: yLabel, color: muted, font: { size: 10 } },
        ticks: { color: muted, font: { size: 10 } },
        grid: { color: grid, drawTicks: false },
        border: { display: false },
      },
    },
  };
}

function lineDataset(label, color, data) {
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 5,
    // A ring in the surface colour keeps overlapping hover points readable.
    pointHoverBorderColor: css('--surface-1'),
    pointHoverBorderWidth: 2,
    tension: 0.25,
    spanGaps: true,
  };
}

function makeChart(canvasId, datasets, yLabel, showLegend) {
  const ctx = $(canvasId).getContext('2d');
  const options = baseOptions(yLabel);
  options.plugins.legend.display = Boolean(showLegend);
  return new Chart(ctx, { type: 'line', data: { labels: [], datasets }, options });
}

function initCharts() {
  const s1 = css('--series-1');
  const s2 = css('--series-2');

  state.charts.hr = makeChart('chart-hr',
    [lineDataset('Heart rate', s1, [])], 'bpm', false);

  state.charts.spo2 = makeChart('chart-spo2',
    [lineDataset('SpO2', s1, [])], '%', false);

  // Two series, same unit and comparable scale -- a legitimate single chart.
  state.charts.bp = makeChart('chart-bp', [
    lineDataset('Systolic', s1, []),
    lineDataset('Diastolic', s2, []),
  ], 'mmHg', true);

  state.charts.rr = makeChart('chart-rr',
    [lineDataset('Respiratory rate', s1, [])], 'breaths/min', false);
}

function updateCharts(readings) {
  // API returns newest-first; charts read oldest-left.
  const rows = [...readings].reverse();
  const labels = rows.map((r) => new Date(r.observedAt).toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }));

  const apply = (chart, series) => {
    chart.data.labels = labels;
    series.forEach((values, i) => { chart.data.datasets[i].data = values; });
    chart.update('none');
  };

  apply(state.charts.hr, [rows.map((r) => r.heartRate)]);
  apply(state.charts.spo2, [rows.map((r) => r.spo2)]);
  apply(state.charts.bp, [rows.map((r) => r.systolicBp), rows.map((r) => r.diastolicBp)]);
  apply(state.charts.rr, [rows.map((r) => r.respiratoryRate)]);

  const tbody = document.querySelector('#data-table tbody');
  tbody.innerHTML = readings.map((r) => `
    <tr>
      <td>${new Date(r.observedAt).toLocaleString()}</td>
      <td>${fmt(r.heartRate)}</td>
      <td>${fmt(r.spo2, 1)}</td>
      <td>${fmt(r.systolicBp)}</td>
      <td>${fmt(r.diastolicBp)}</td>
      <td>${fmt(r.temperatureC, 1)}</td>
      <td>${fmt(r.respiratoryRate)}</td>
      <td>${fmt(r.shockIndex, 2)}</td>
    </tr>`).join('');
}

/* ---------------------------------------------------------------- rendering */

const RISK_PRESENTATION = {
  LOW:     { cls: 'risk-low',     icon: '✓', word: 'Low' },
  MEDIUM:  { cls: 'risk-medium',  icon: '!',      word: 'Medium' },
  HIGH:    { cls: 'risk-high',    icon: '⚠', word: 'High' },
  UNKNOWN: { cls: 'risk-unknown', icon: '?',      word: 'Unknown' },
};

function renderLatest(reading) {
  if (!reading) return;
  $('t-hr').textContent = fmt(reading.heartRate);
  $('t-spo2').textContent = fmt(reading.spo2, 1);
  $('t-bp').textContent = `${fmt(reading.systolicBp)}/${fmt(reading.diastolicBp)}`;
  $('t-temp').textContent = fmt(reading.temperatureC, 1);
  $('t-rr').textContent = fmt(reading.respiratoryRate);
  $('t-si').textContent = fmt(reading.shockIndex, 2);
}

function renderRisk(risk) {
  const badge = $('risk-badge');

  if (!risk) {
    const p = RISK_PRESENTATION.UNKNOWN;
    badge.className = `risk-badge ${p.cls}`;
    badge.querySelector('.risk-icon').textContent = p.icon;
    $('risk-band').textContent = 'No assessment yet';
    $('risk-confidence').textContent = '';
    $('news2-total').textContent = '–';
    $('news2-band').textContent = '';
    $('summary-list').innerHTML = '<li class="muted">No summary yet.</li>';
    $('summary-provider').textContent = '–';
    $('summary-provider').className = 'pill pill-muted';
    $('summary-latency').textContent = '';
    return;
  }

  const p = RISK_PRESENTATION[risk.riskBand] || RISK_PRESENTATION.UNKNOWN;
  badge.className = `risk-badge ${p.cls}`;
  badge.querySelector('.risk-icon').textContent = p.icon;
  $('risk-band').textContent = `${p.word} risk`;

  $('risk-confidence').textContent = risk.mlAvailable === false
    ? 'triage service unavailable — NEWS2 only'
    : (risk.confidence != null ? `model confidence ${(risk.confidence * 100).toFixed(1)}%` : '');

  $('news2-total').textContent = risk.news2Total != null ? risk.news2Total : '–';
  $('news2-band').textContent = risk.news2Band ? `band ${risk.news2Band}` : '';

  const bullets = (risk.summary || '')
    .split('\n')
    .map((line) => line.replace(/^[-*•]\s*/, '').trim())
    .filter(Boolean);
  $('summary-list').innerHTML = bullets.length
    ? bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join('')
    : '<li class="muted">No summary yet.</li>';

  const provider = risk.summaryProvider || '–';
  const el = $('summary-provider');
  el.textContent = provider;
  el.className = `pill pill-${provider}`;
  $('summary-latency').textContent = risk.summaryLatencyMs != null
    ? `${risk.summaryLatencyMs.toFixed(0)} ms`
    : '';
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* ------------------------------------------------------------------ polling */

async function refresh() {
  if (!state.patientId) return;
  try {
    const [vitals, risk] = await Promise.all([
      api(API.vitals(state.patientId, state.limit)),
      api(API.latestRisk(state.patientId)),
    ]);
    if (vitals && vitals.readings.length) {
      renderLatest(vitals.readings[0]);
      updateCharts(vitals.readings);
    }
    renderRisk(risk);
    setConn('live', 'pill-ok');
  } catch (e) {
    if (e.message !== 'unauthorized') setConn('disconnected', 'pill-bad');
  }
}

async function loadPatients() {
  const data = await api(API.patients);
  const select = $('patient-select');
  select.innerHTML = data.patients
    .map((p) => `<option value="${p.patientId}">${p.patientId} — ${p.displayName}</option>`)
    .join('');
  if (data.patients.length && !state.patientId) {
    state.patientId = data.patients[0].patientId;
  }
  select.value = state.patientId;
}

async function boot() {
  await loadPatients();
  await refresh();
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(refresh, POLL_MS);
}

/* -------------------------------------------------------------------- wiring */

document.addEventListener('DOMContentLoaded', () => {
  initCharts();

  $('login-form').addEventListener('submit', login);
  $('refresh-btn').addEventListener('click', refresh);

  $('patient-select').addEventListener('change', (e) => {
    state.patientId = e.target.value;
    refresh();
  });

  $('window-select').addEventListener('change', (e) => {
    state.limit = Number(e.target.value);
    refresh();
  });

  $('analyze-btn').addEventListener('click', async () => {
    if (!state.patientId) return;
    const btn = $('analyze-btn');
    btn.disabled = true;
    btn.textContent = 'Analyzing…';
    try {
      await api(API.analyze(state.patientId), { method: 'POST' });
      await refresh();
    } catch (e) {
      /* refresh() already reports connection state */
    } finally {
      btn.disabled = false;
      btn.textContent = 'Analyze now';
    }
  });

  $('table-toggle').addEventListener('click', () => {
    const wrap = $('table-wrap');
    const btn = $('table-toggle');
    wrap.hidden = !wrap.hidden;
    btn.setAttribute('aria-expanded', String(!wrap.hidden));
    btn.textContent = wrap.hidden ? 'Show data table' : 'Hide data table';
  });

  const saved = localStorage.getItem('vitalsync.token');
  if (saved) {
    state.token = saved;
    showApp();
    boot().catch(() => showLogin('Could not restore session.'));
  } else {
    showLogin();
  }
});
