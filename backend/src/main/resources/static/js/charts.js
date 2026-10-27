/* Chart.js configuration shared by every chart in the app.
 *
 * One measure per chart. There is no twin-axis helper here and that is
 * deliberate: plotting heart rate (bpm) against SpO2 (%) on two independently
 * scaled y-axes lets the axis ranges manufacture a correlation that is not in
 * the data. Two measures of different units get two charts.
 */

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function baseOptions(yLabel) {
  const text = cssVar('--text-secondary');
  const muted = cssVar('--text-muted');
  const grid = cssVar('--grid');

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    // Crosshair-style: hovering the column reports the reading, so the pointer
    // does not have to land on a 3px dot.
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        display: false,
        labels: { color: text, boxWidth: 10, boxHeight: 10, usePointStyle: true },
      },
      tooltip: {
        backgroundColor: cssVar('--surface-2'),
        titleColor: cssVar('--text-primary'),
        bodyColor: text,
        borderColor: cssVar('--border'),
        borderWidth: 1,
        padding: 9,
        usePointStyle: true,
      },
    },
    scales: {
      x: {
        ticks: { color: muted, maxRotation: 0, autoSkipPadding: 20, font: { size: 10 } },
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

function dataset(label, color, dashed = false) {
  return {
    label,
    data: [],
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    borderDash: dashed ? [5, 3] : [],
    pointRadius: 0,
    pointHoverRadius: 4,
    // A surface-coloured ring keeps overlapping hover points readable.
    pointHoverBorderColor: cssVar('--surface-1'),
    pointHoverBorderWidth: 2,
    tension: 0.25,
    spanGaps: true,
  };
}

const registry = new Map();

/** Creates (or returns) the chart bound to a canvas id. */
export function ensureChart(canvasId, series, yLabel) {
  const canvas = document.getElementById(canvasId);
  const existing = registry.get(canvasId);
  if (existing && existing.canvas === canvas) return existing;
  // Views re-render via innerHTML, so a cached chart may be bound to a detached canvas.
  if (existing) {
    existing.destroy();
    registry.delete(canvasId);
  }
  if (!canvas || typeof Chart === 'undefined') return null;

  const options = baseOptions(yLabel);
  options.plugins.legend.display = series.length > 1;

  const chart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels: [],
      datasets: series.map((s, i) => dataset(s.label, cssVar(s.colorVar), i > 0)),
    },
    options,
  });
  registry.set(canvasId, chart);
  return chart;
}

export function updateChart(canvasId, labels, seriesData) {
  const chart = registry.get(canvasId);
  if (!chart) return;
  chart.data.labels = labels;
  seriesData.forEach((values, i) => {
    if (chart.data.datasets[i]) chart.data.datasets[i].data = values;
  });
  chart.update('none');
}

/** Charts cache theme colours, so a theme switch requires a rebuild. */
export function destroyAll() {
  registry.forEach((chart) => chart.destroy());
  registry.clear();
}
