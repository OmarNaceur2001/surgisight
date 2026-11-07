import test from "node:test";
import assert from "node:assert/strict";
import {
  clampPageSize,
  confidenceLabel,
  formatDuration,
  phaseWidth,
} from "../src/presentation.mjs";

test("formats seconds and hours without negative values", () => {
  assert.equal(formatDuration(65), "1m 05s");
  assert.equal(formatDuration(3670), "1h 01m");
  assert.equal(formatDuration(-4), "0m 00s");
});

test("phase widths are bounded by the video duration", () => {
  assert.equal(phaseWidth(10, 30, 100), 20);
  assert.equal(phaseWidth(0, 200, 100), 100);
  assert.equal(phaseWidth(0, 30, 0), 0);
});

test("pagination has a safe default and a maximum", () => {
  assert.equal(clampPageSize(0), 1);
  assert.equal(clampPageSize(1000), 100);
  assert.equal(clampPageSize(Number.NaN), 25);
});

test("confidence is clamped and formatted", () => {
  assert.equal(confidenceLabel(0.875), "88%");
  assert.equal(confidenceLabel(2), "100%");
});
