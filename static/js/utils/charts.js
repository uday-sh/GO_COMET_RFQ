import { escapeHtml } from "./format.js";

export function renderSparkChart(container, points, valueOf = (point) => point.value) {
  const values = points.map(valueOf).map((value) => Number(value || 0));
  const maximum = Math.max(...values, 0);
  container.innerHTML = points.length
    ? points.map((point, index) => {
      const value = values[index];
      const height = maximum ? Math.max(5, Math.round((value / maximum) * 100)) : 4;
      return `<span title="${escapeHtml(point.label)}: ${escapeHtml(value)}" style="height:${height}%"></span>`;
    }).join("")
    : '<p class="muted chart-empty">No activity recorded yet.</p>';
}

export function renderBarChart(container, points) {
  const maximum = Math.max(...points.map((point) => Number(point.value || 0)), 0);
  container.innerHTML = points.length
    ? points.map((point) => {
      const value = Number(point.value || 0);
      const width = maximum ? Math.round((value / maximum) * 100) : 0;
      return `<div class="bar-row"><div><span>${escapeHtml(point.label)}</span><strong>${escapeHtml(value)}</strong></div><div class="bar-track"><i style="width:${width}%"></i></div></div>`;
    }).join("")
    : '<p class="muted chart-empty">No data to show yet.</p>';
}
