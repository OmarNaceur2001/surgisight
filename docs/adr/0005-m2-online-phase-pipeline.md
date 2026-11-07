# ADR 0005: M2 Online Causal Phase Pipeline with Bounded Ring Buffer and Safe Artifact Verification

- **Status**: Accepted
- **Date**: 2026-11-07
- **Context**: Real-time surgical video phase recognition requires online step-by-step inference without future lookahead (strict causality) and with strictly bounded memory over long surgical procedures (up to 90+ minutes). Furthermore, research safety guidelines (P2) forbid unvetted synthetic or invalid weight artifacts in production pipelines.
- **Decision**: We implement `OnlinePhasePipeline` with a FIFO ring buffer (`collections.deque` with `maxlen`), pure causal temporal convolution / exponential smoothing, and `load_pipeline`. The `RealPhaseProvider` verifies artifact integrity via SHA-256 hashes, strictly blocks artifacts tagged `synthetic` or `DO_NOT_USE` unless `allow_synthetic_artifact=True` is explicitly set in configuration, and falls back to mock execution when artifacts are absent.
- **Consequences**: Memory consumption is constant $O(1)$ with respect to video duration; future frames cannot leak into current predictions; tests verify truncation causality mathematically.
