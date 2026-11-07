import assert from "node:assert/strict";
import test from "node:test";

import { clampPercent, confidenceState, formatDuration } from "../src/helpers.mjs";

test("clampPercent handles non-finite values and bounds", () => {
  assert.equal(clampPercent(Number.NaN), 0);
  assert.equal(clampPercent(-5), 0);
  assert.equal(clampPercent(140), 100);
  assert.equal(clampPercent(37.5), 37.5);
});

test("formatDuration emits stable elapsed time", () => {
  assert.equal(formatDuration(0), "00:00");
  assert.equal(formatDuration(75), "01:15");
  assert.equal(formatDuration(3661), "01:01:01");
  assert.equal(formatDuration(Number.NaN), "—");
});

test("confidenceState marks only below-threshold values uncertain", () => {
  assert.equal(confidenceState(0.49), "uncertain");
  assert.equal(confidenceState(0.5), "confident");
  assert.equal(confidenceState(0.99), "confident");
});
