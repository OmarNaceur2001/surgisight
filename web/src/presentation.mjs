/** Pure helpers shared by the dashboard and Node's built-in tests. */
export function formatDuration(seconds) {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  return hours > 0
    ? `${hours}h ${String(minutes).padStart(2, "0")}m`
    : `${minutes}m ${String(secs).padStart(2, "0")}s`;
}

export function phaseWidth(start, end, duration) {
  if (!(duration > 0)) return 0;
  return Math.min(100, Math.max(0, ((end - start) / duration) * 100));
}

export function clampPageSize(value, max = 100) {
  const n = Math.trunc(Number(value));
  return Number.isFinite(n) ? Math.max(1, Math.min(max, n)) : 25;
}

export function confidenceLabel(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "not available";
  return `${Math.round(Math.max(0, Math.min(1, n)) * 100)}%`;
}
