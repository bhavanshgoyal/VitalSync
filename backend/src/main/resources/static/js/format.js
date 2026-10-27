/* Presentation helpers.
 *
 * Centralised because the same value must look identical everywhere: a heart
 * rate shown as 88 on the board and 88.0 on the detail page reads as two
 * different measurements.
 */

export const BANDS = {
  LOW:     { glyph: '✓', word: 'Low',         label: 'Low risk' },
  MEDIUM:  { glyph: '!',      word: 'Medium',      label: 'Medium risk' },
  HIGH:    { glyph: '⚠', word: 'High',        label: 'High risk' },
  UNKNOWN: { glyph: '?',      word: 'Unavailable', label: 'Risk unavailable' },
};

export function band(value) {
  return BANDS[value] || BANDS.UNKNOWN;
}

/** Null-safe fixed-precision. Returns an en dash, never "NaN" or "null". */
export function num(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '–';
  }
  return Number(value).toFixed(digits);
}

export function pct(value, digits = 1) {
  if (value === null || value === undefined) return '–';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

/** Compact relative time: "12s", "4m", "2h". */
export function ago(seconds) {
  if (seconds === null || seconds === undefined) return 'never';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function clockTime(iso) {
  if (!iso) return '–';
  return new Date(iso).toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function dateTime(iso) {
  if (!iso) return '–';
  return new Date(iso).toLocaleString();
}

/** Direction of travel. Threshold avoids calling sensor jitter a trend. */
export function trend(delta, threshold = 0.5) {
  if (delta === null || delta === undefined) return { cls: 'trend-flat', text: '' };
  if (delta > threshold) return { cls: 'trend-up', text: `+${delta.toFixed(0)}` };
  if (delta < -threshold) return { cls: 'trend-down', text: delta.toFixed(0) };
  return { cls: 'trend-flat', text: 'steady' };
}

/** Human labels for NEWS2 parameter keys. */
export const NEWS2_LABELS = {
  respiratory_rate: 'Respiratory rate',
  spo2: 'SpO₂',
  supplemental_oxygen: 'Supplemental O₂',
  systolic_bp: 'Systolic BP',
  pulse: 'Pulse',
  consciousness: 'Consciousness',
  temperature: 'Temperature',
};

/** Escapes text destined for innerHTML. */
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Inline SVG sparkline. No library, no layout cost, scales to the card. */
export function sparkline(values, { width = 300, height = 30, color } = {}) {
  const pts = (values || []).filter((v) => typeof v === 'number' && !Number.isNaN(v));
  if (pts.length < 2) return '';

  const min = Math.min(...pts);
  const max = Math.max(...pts);
  // A flat series would divide by zero; draw it down the middle instead.
  const span = max - min || 1;
  const stepX = width / (pts.length - 1);
  const pad = 3;

  const d = pts
    .map((v, i) => {
      const x = (i * stepX).toFixed(1);
      const y = (pad + (height - pad * 2) * (1 - (v - min) / span)).toFixed(1);
      return `${i === 0 ? 'M' : 'L'}${x},${y}`;
    })
    .join(' ');

  const stroke = color || 'var(--vital-hr)';
  return `<svg class="sparkline" viewBox="0 0 ${width} ${height}"
    preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.6"
      stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  </svg>`;
}
