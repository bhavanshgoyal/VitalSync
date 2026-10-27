/* System view: is the architecture doing what it claims?
 *
 * Not decoration. This is the resilience claim rendered: which tiers are live,
 * what each answered, how often the faithfulness guard passed, and how many
 * assessments were recorded while triage was down.
 */

import { api } from '../api.js';
import { esc, num } from '../format.js';

const root = () => document.getElementById('view-system');

const TIERS = [
  { name: 'ollama', label: 'Tier 1 · local model', note: 'keeps telemetry on the host' },
  { name: 'gemini', label: 'Tier 2 · cloud model', note: 'uncorrelated failure mode' },
  { name: 'rule-based', label: 'Tier 3 · deterministic', note: 'no dependency; cannot fail' },
];

function stat(k, v, d) {
  return `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div>
          <div class="d">${d || '&nbsp;'}</div></div>`;
}

export async function render() {
  const el = root();
  const health = await api.systemHealth();

  const active = new Set(health.activeProviders || []);
  const counts = health.providerCounts || {};
  const faith = health.faithfulness || {};

  const total = health.totalAssessments || 0;
  const degraded = health.degradedAssessments || 0;
  const degradedPct = total ? ((degraded / total) * 100).toFixed(1) : '0.0';

  // Overall faithfulness across every tier that answered.
  let checked = 0;
  let passed = 0;
  Object.values(faith).forEach((f) => {
    checked += f.total || 0;
    passed += f.faithful || 0;
  });
  const faithPct = checked ? ((passed / checked) * 100).toFixed(1) : '–';

  const tiers = TIERS.map((t) => {
    const isActive = active.has(t.name);
    const n = counts[t.name] || 0;
    const f = faith[t.name];
    const rate = f && f.total
      ? `${((f.faithful / f.total) * 100).toFixed(0)}% faithful` : '';
    return `
      <div class="tier" data-active="${isActive}">
        <span class="svc-dot" data-up="${isActive}"></span>
        <strong>${esc(t.label)}</strong>
        <span class="muted small">${esc(t.note)}</span>
        <span class="spacer"></span>
        ${rate ? `<span class="small muted">${rate}</span>` : ''}
        <span class="pill">${isActive ? 'live' : 'not configured'}</span>
        <span class="mono small">${n} answered</span>
      </div>`;
  }).join('');

  el.innerHTML = `
    <div class="view-head">
      <h1>System</h1>
      <span class="count">architecture health and cascade behaviour</span>
    </div>

    <div class="grid" style="gap:var(--s4)">

      <section class="stat-grid">
        ${stat('Assessments', total.toLocaleString(), 'total recorded')}
        ${stat('Degraded', degraded.toLocaleString(),
               `${degradedPct}% written with triage unreachable`)}
        ${stat('Faithfulness', checked ? `${faithPct}%` : '–',
               checked ? `${passed}/${checked} summaries verified` : 'no summaries yet')}
        ${stat('Active tiers', String(active.size), 'in the cascade')}
      </section>

      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
        <section class="card">
          <div class="card-head"><h2>Services</h2></div>
          <div class="svc-row">
            <span class="svc-dot" data-up="true"></span>
            <strong>Backend</strong>
            <span class="muted small">serving this page</span>
            <span class="spacer"></span><span class="pill">up</span>
          </div>
          <div class="svc-row">
            <span class="svc-dot" data-up="${health.mlReachable}"></span>
            <strong>Triage service</strong>
            <span class="muted small mono">${esc(health.mlBaseUrl || '')}</span>
            <span class="spacer"></span>
            <span class="pill">${health.mlReachable ? 'up' : 'unreachable'}</span>
          </div>
          <div class="svc-row">
            <span class="svc-dot" data-up="true"></span>
            <strong>PostgreSQL</strong>
            <span class="muted small">assessments persisted</span>
            <span class="spacer"></span><span class="pill">up</span>
          </div>
          ${health.mlReachable ? '' : `
            <p class="small" style="margin-top:var(--s3);margin-bottom:0">
              <strong>Degraded mode.</strong> Telemetry is still being accepted
              and summarised by the deterministic tier; risk bands read
              <em>unavailable</em> rather than being guessed.
            </p>`}
        </section>

        <section class="card">
          <div class="card-head">
            <h2>Summarization cascade</h2>
            <span class="spacer"></span>
            <span class="small muted">best-first, terminal tier cannot fail</span>
          </div>
          <div class="tier-list">${tiers}</div>
          ${active.size === 1 ? `
            <p class="muted small" style="margin-top:var(--s3);margin-bottom:0">
              Only the deterministic tier is configured, so every summary above
              was produced without a language model. Enable a tier in
              <span class="mono">.env</span> to exercise the others.
            </p>` : ''}
        </section>
      </div>

      <section class="card">
        <div class="card-head"><h2>What this view is for</h2></div>
        <p class="small muted" style="margin-bottom:0">
          The architecture claims that ingestion and summarization survive the
          loss of the triage service. The degraded counter is the evidence:
          those assessments were recorded while triage was unreachable, with
          the band marked unavailable and the summary produced deterministically.
          Stop the <span class="mono">ml-service</span> container and watch
          these numbers move.
        </p>
      </section>
    </div>`;

  return `System view. ${active.size} active tiers, ${degraded} degraded assessments.`;
}
