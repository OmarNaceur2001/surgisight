# ADR-003: Causal online replay and report-grounded summaries

- Status: Accepted
- Context: Saved review and Stage 2 replay must not create a second inference implementation, and generated prose must not invent facts.
- Decision: Saved replay reads stored contract records. Live replay calls the existing OnlinePhasePipeline.step() at a controlled pace. Summaries are deterministic renderings of validated report.json, checked against report fields and the neutral wording lexicon.
- Consequences: Live replay refuses to run without enabled, verified local M2 artifacts. Latency metrics are process-local aggregates; no video or user identifiers are retained in the metrics registry.
