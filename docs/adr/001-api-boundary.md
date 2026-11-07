# ADR-001: REST and WebSocket API boundary

- Status: Accepted
- Context: The review UI requires paginated library search, analysis status, prediction slices, corrections, reports and synchronized replay.
- Decision: Keep these capabilities in the FastAPI modular monolith. Use REST for resource operations and WebSocket only for paced record replay.
- Consequences: API schemas remain the single contract boundary; tests use SQLite and synthetic fixtures. No new service or runtime external dependency is introduced.
