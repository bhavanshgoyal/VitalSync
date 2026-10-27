/* Patient detail: what is happening, and why the system says so. */

import { api } from '../api.js';
import { ensureChart, updateChart } from '../charts.js';
import {
  NEWS2_LABELS, band, clockTime, dateTime, esc, num, pct, trend,
} from '../format.js';

const root = () => document.getElementById('view-patient');

let currentId = null;
let tableOpen = false;

function tile(vital, label, value, unit, deltaText) {
  return `
    <div class="vtile" data-vital="${vital}">
      <div class="k">${label}</div>
      <div class="v">${value}<span class="u">${unit}</span></div>
      <div class="d">${deltaText || '&nbsp;'}</div>
    </div>`;
}

/**
 * Per-parameter NEWS2 contributions.
 *
 * This is the part that makes the score checkable: a clinician can compare
 * each row against the chart in front of them. Parameters are shown even at
 * zero points, so the absence of a contribution is visible rather than
 * inferred from a missing row.
 */
function breakdown(perParameter, total) {
  if (!perParameter) {
    return `<p class="muted small">No breakdown available &mdash; the triage
      service did not score this reading.</p>`;
  }

  const order = ['respiratory_rate', 'spo2', 'supplemental_oxygen',
                 'systolic_bp', 'pulse', 'consciousness', 'temperature'];
  const keys = order.filter((k) => k in perParameter);
  const sum = keys.reduce((acc, k) => acc + (perParameter[k] || 0), 0);

  const rows = keys.map((k) => {
    const points = perParameter[k] || 0;
    return `
      <div class="bd-row" data-points="${points}">
        <span class="bd-label">${esc(NEWS2_LABELS[k] || k)}</span>
        <span class="bd-track">
          <span class="bd-fill" data-points="${points}"
                style="width:${(points / 3) * 100}%"></span>
        </span>
        <span class="bd-points">${points}</span>
      </div>`;
  }).join('');

  // If the parts disagree with the headline the UI must say so rather than
  // quietly showing a breakdown that contradicts the number beside it.
  const mismatch = (total != null && sum !== total)
    ? `<p class="error small">Breakdown sums to ${sum} but the recorded total
       is ${total}. Treat both as unreliable.</p>`
    : '';

  return `<div class="breakdown">${rows}</div>${mismatch}`;
}

function summaryBlock(risk) {
  if (!risk || !risk.summary) {
    return '<p class="muted">No summary yet.</p>';
  }
  const bullets = risk.summary
    .split('\n')
    .map((l) => l.replace(/^[-*•]\s*/, '').trim())
    .filter(Boolean);

  const faith = risk.summaryFaithful === false
    ? '<span class="faith-bad">failed faithfulness check</span>'
    : '<span class="faith-ok">faithfulness verified</span>';

  return `
    <ul class="summary-list">
      ${bullets.map((b) => `<li>${esc(b)}</li>`).join('')}
    </ul>
    <div class="provenance">
      <span class="prov-k">produced by</span>
      <span class="pill" data-provider="${esc(risk.summaryProvider || '')}">${esc(risk.summaryProvider || '–')}</span>
      <span class="muted">${num(risk.summaryLatencyMs, 1)} ms</span>
      <span>&middot;</span>
      ${faith}
    </div>`;
}

export async function render(navigate, patientId) {
  const el = root();
  const switching = patientId !== currentId;
  currentId = patientId;

  const [vitalsRes, risk] = await Promise.all([
    api.vitals(patientId, 50),
    api.latestRisk(patientId).catch((e) => {
      if (e.kind === 'notfound') throw e;
      return null;
    }),
  ]);

  const readings = (vitalsRes && vitalsRes.readings) || [];
  const latest = readings[0];
  const oldest = readings[readings.length - 1];

  const b = band(risk ? risk.riskBand : 'UNKNOWN');

  const d = (key) => (latest && oldest && readings.length > 1)
    ? latest[key] - oldest[key] : null;

  const bpValue = latest
    ? `${num(latest.systolicBp)}/${num(latest.diastolicBp)}` : '–';

  const confidenceText = !risk
    ? ''
    : risk.mlAvailable === false
      ? 'triage service unavailable &mdash; NEWS2 only'
      : `model confidence ${pct(risk.confidence)}`;

  el.innerHTML = `
    <button class="back-link" data-back>&larr; Ward board</button>

    <div class="view-head">
      <h1>${esc(patientId)}</h1>
      <span class="count">${esc(latest ? `last reading ${clockTime(latest.observedAt)}` : 'no readings')}</span>
      <span class="spacer"></span>
      <button class="btn btn-sm" data-analyze>Analyze now</button>
    </div>

    <div class="grid" style="grid-template-columns:1fr;gap:var(--s4)">

      <section class="vitals-row" aria-label="Latest vital signs">
        ${tile('hr', 'Heart rate', num(latest && latest.heartRate), 'bpm',
               trendText(d('heartRate'), 'bpm'))}
        ${tile('spo2', 'SpO&#8322;', num(latest && latest.spo2, 1), '%',
               trendText(d('spo2'), '%'))}
        ${tile('bp', 'Blood pressure', bpValue, 'mmHg',
               trendText(d('systolicBp'), 'sys'))}
        ${tile('temp', 'Temperature', num(latest && latest.temperatureC, 1), '&deg;C', '')}
        ${tile('rr', 'Resp. rate', num(latest && latest.respiratoryRate), '/min',
               trendText(d('respiratoryRate'), '/min'))}
        ${tile('si', 'Shock index', num(latest && latest.shockIndex, 2), 'HR/SBP', '')}
      </section>

      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
        <section class="card">
          <div class="card-head"><h2>Risk assessment</h2></div>
          <div style="display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;margin-bottom:var(--s3)">
            <span class="badge" data-band="${esc(risk ? risk.riskBand : 'UNKNOWN')}">
              <span class="glyph" aria-hidden="true">${b.glyph}</span>${esc(b.word)}
            </span>
            <span class="news2-chip">
              <span class="n">${risk && risk.news2Total != null ? risk.news2Total : '–'}</span>
              <span class="l">NEWS2</span>
            </span>
            <span class="small muted">${confidenceText}</span>
          </div>
          <h3 class="muted small" style="margin-bottom:var(--s2)">Score breakdown</h3>
          ${breakdown(risk && risk.news2PerParameter, risk && risk.news2Total)}
        </section>

        <section class="card">
          <div class="card-head"><h2>Clinical summary</h2></div>
          ${summaryBlock(risk)}
          <p class="muted small" style="margin-top:var(--s3);margin-bottom:0">
            For clinician review. The tier that produced this is recorded with
            every assessment, so the fallback cascade is observable.
          </p>
        </section>
      </div>

      <section class="card">
        <div class="card-head">
          <h2>Trends</h2>
          <span class="small muted">last ${readings.length} readings</span>
          <span class="spacer"></span>
          <button class="btn btn-sm" data-table aria-expanded="${tableOpen}">
            ${tableOpen ? 'Hide' : 'Show'} data table
          </button>
        </div>
        <div class="chart-grid">
          ${figure('chart-hr', 'Heart rate', 'bpm')}
          ${figure('chart-spo2', 'Oxygen saturation', '%')}
          ${figure('chart-bp', 'Blood pressure', 'mmHg')}
          ${figure('chart-rr', 'Respiratory rate', 'breaths/min')}
        </div>
        <div class="table-wrap" ${tableOpen ? '' : 'hidden'} data-table-wrap
             style="margin-top:var(--s4)">
          ${table(readings)}
        </div>
      </section>
    </div>`;

  el.querySelector('[data-back]').addEventListener('click', () => navigate('#/ward'));
  el.querySelector('[data-table]').addEventListener('click', (e) => {
    tableOpen = !tableOpen;
    const wrap = el.querySelector('[data-table-wrap]');
    wrap.hidden = !tableOpen;
    e.target.textContent = `${tableOpen ? 'Hide' : 'Show'} data table`;
    e.target.setAttribute('aria-expanded', String(tableOpen));
  });

  const analyzeBtn = el.querySelector('[data-analyze]');
  analyzeBtn.addEventListener('click', async () => {
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing…';
    try {
      await api.analyze(patientId);
      await render(navigate, patientId);
    } catch {
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = 'Analyze now';
    }
  });

  drawCharts(readings, switching);

  return risk
    ? `${patientId}: ${b.label}, NEWS2 ${risk.news2Total ?? 'unavailable'}.`
    : `${patientId}: no assessment yet.`;
}

function trendText(delta, unit) {
  if (delta === null || delta === undefined) return '';
  const t = trend(delta);
  return t.text === 'steady'
    ? '<span class="trend-flat">steady</span>'
    : `<span class="${t.cls}">${t.text} ${esc(unit)}</span>`;
}

function figure(id, label, unit) {
  return `
    <figure class="chart-figure">
      <figcaption>${label} <span class="unit">${unit}</span></figcaption>
      <div class="chart-box"><canvas id="${id}"></canvas></div>
    </figure>`;
}

function table(readings) {
  if (!readings.length) return '<p class="muted small">No readings.</p>';
  return `
    <table>
      <caption class="sr-only">Recent vital-sign readings</caption>
      <thead><tr>
        <th scope="col">Observed</th><th scope="col">HR</th><th scope="col">SpO&#8322;</th>
        <th scope="col">SBP</th><th scope="col">DBP</th><th scope="col">Temp</th>
        <th scope="col">RR</th><th scope="col">SI</th>
      </tr></thead>
      <tbody>
        ${readings.map((r) => `
          <tr>
            <td>${esc(dateTime(r.observedAt))}</td>
            <td>${num(r.heartRate)}</td><td>${num(r.spo2, 1)}</td>
            <td>${num(r.systolicBp)}</td><td>${num(r.diastolicBp)}</td>
            <td>${num(r.temperatureC, 1)}</td><td>${num(r.respiratoryRate)}</td>
            <td>${num(r.shockIndex, 2)}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

function drawCharts(readings) {
  // API returns newest first; charts read oldest-left.
  const rows = [...readings].reverse();
  const labels = rows.map((r) => clockTime(r.observedAt));

  ensureChart('chart-hr', [{ label: 'Heart rate', colorVar: '--vital-hr' }], 'bpm');
  ensureChart('chart-spo2', [{ label: 'SpO2', colorVar: '--vital-spo2' }], '%');
  ensureChart('chart-bp', [
    { label: 'Systolic', colorVar: '--vital-bp' },
    { label: 'Diastolic', colorVar: '--series-1' },
  ], 'mmHg');
  ensureChart('chart-rr', [{ label: 'Respiratory rate', colorVar: '--vital-rr' }], 'breaths/min');

  updateChart('chart-hr', labels, [rows.map((r) => r.heartRate)]);
  updateChart('chart-spo2', labels, [rows.map((r) => r.spo2)]);
  updateChart('chart-bp', labels, [
    rows.map((r) => r.systolicBp), rows.map((r) => r.diastolicBp),
  ]);
  updateChart('chart-rr', labels, [rows.map((r) => r.respiratoryRate)]);
}
