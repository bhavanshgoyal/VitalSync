/* Ward Board: who needs attention first.
 *
 * The server sorts by acuity. The client does not re-sort, so the ordering
 * rule lives in exactly one place.
 */

import { api } from '../api.js';
import { ago, band, esc, num, sparkline } from '../format.js';

const root = () => document.getElementById('view-ward');

function card(p) {
  const b = band(p.riskBand);
  const v = p.vitals || {};
  const bp = (v.systolicBp != null && v.diastolicBp != null)
    ? `${num(v.systolicBp)}/${num(v.diastolicBp)}`
    : '–';

  // Staleness is surfaced, not hidden. Showing an old number as if it were
  // current is the most dangerous thing a monitoring board can do.
  const staleNote = p.stale
    ? `<span class="pill" title="No reading for ${esc(ago(p.secondsSinceReading))}">no recent data</span>`
    : '';

  const provider = p.summaryProvider
    ? `<span class="pill" data-provider="${esc(p.summaryProvider)}">${esc(p.summaryProvider)}</span>`
    : '';

  const degraded = p.mlAvailable === false
    ? '<span class="pill" title="Triage service was unreachable">triage down</span>'
    : '';

  return `
    <button class="patient-card${p.stale ? ' stale' : ''}"
            data-band="${esc(p.riskBand || 'UNKNOWN')}"
            data-patient="${esc(p.patientId)}"
            aria-label="${esc(p.patientId)}, ${esc(b.label)}, NEWS2 ${p.news2Total ?? 'unavailable'}">
      <div class="pc-head">
        <span class="pc-id">${esc(p.patientId)}</span>
        <span class="pc-name">${esc(p.displayName || '')}</span>
        <span class="spacer"></span>
        <span class="badge" data-band="${esc(p.riskBand || 'UNKNOWN')}">
          <span class="glyph" aria-hidden="true">${b.glyph}</span>${esc(b.word)}
        </span>
      </div>

      ${sparkline(p.heartRateSeries)}

      <div class="pc-vitals">
        <span class="pc-vital"><span class="v">${num(v.heartRate)}</span><span class="k">HR</span></span>
        <span class="pc-vital"><span class="v">${num(v.spo2, 0)}</span><span class="k">SpO&#8322;</span></span>
        <span class="pc-vital"><span class="v">${bp}</span><span class="k">BP</span></span>
        <span class="pc-vital"><span class="v">${num(v.temperatureC, 1)}</span><span class="k">Temp</span></span>
      </div>

      <div class="pc-foot">
        <span class="news2-chip">
          <span class="n">${p.news2Total ?? '–'}</span><span class="l">NEWS2</span>
        </span>
        ${degraded}${staleNote}
        <span class="spacer"></span>
        ${provider}
        <span>${esc(ago(p.secondsSinceReading))} ago</span>
      </div>
    </button>`;
}

export async function render(navigate) {
  const el = root();
  const data = await api.ward(20);
  const patients = data.patients || [];

  const highCount = patients.filter((p) => p.riskBand === 'HIGH').length;

  el.innerHTML = `
    <div class="view-head">
      <h1>Ward board</h1>
      <span class="count">${patients.length} patients${highCount ? ` · ${highCount} high risk` : ''}</span>
      <span class="spacer"></span>
      <span class="small muted">sorted by acuity</span>
    </div>
    ${patients.length
      ? `<div class="ward-grid">${patients.map(card).join('')}</div>`
      : '<div class="empty">No patients yet. Run the simulator to generate telemetry.</div>'}
  `;

  el.querySelectorAll('.patient-card').forEach((node) => {
    node.addEventListener('click', () =>
      navigate(`#/patient/${node.dataset.patient}`));
  });

  // Announce only the headline, not every card, or a screen reader would read
  // the whole board on each poll.
  return highCount
    ? `Ward board updated. ${highCount} patient${highCount > 1 ? 's' : ''} at high risk.`
    : 'Ward board updated. No patients at high risk.';
}
