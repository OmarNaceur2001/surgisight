export function clampPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(100, Math.max(0, numeric));
}

export function formatDuration(totalSeconds) {
  const numeric = Number(totalSeconds);
  if (!Number.isFinite(numeric) || numeric < 0) return "—";
  const seconds = Math.floor(numeric);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function confidenceState(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric < 0.5 ? "uncertain" : "confident";
}
