# ADR-004: Delivery quality and security gates

- Status: Accepted
- Context: The repository must prevent dataset/derived data exposure and report measurable code quality.
- Decision: Add CI gates for code style, unit tests, coverage, dependency audit, tracked-file security scan, and a synthetic online replay harness.
- Consequences: Machine-specific PostgreSQL and full 90-minute RSS checks remain explicit manual acceptance items on the controlled Windows machine, not fabricated CI claims.
