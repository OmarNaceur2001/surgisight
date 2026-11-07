# Handover and open items

> Research prototype — not for clinical use.

## Implemented
- REST APIs for analysis submission/status, prediction slices, filtered library, report JSON/PDF, append-only corrections and reviewer-only review transition.
- Authenticated saved replay and gated live M2 replay.
- React dashboard with login, library, upload and review workflow.
- Deterministic report-grounded summary with fact checking.
- Aggregate cohort API, local latency metrics, and optional CVS not_assessed interface.
- Documentation templates and local security/performance tools.

## Required on the controlled Windows workstation
1. Verify PostgreSQL 16 is installed and reachable; run Alembic upgrade/downgrade and verify the append-only correction trigger against the actual database.
2. Set a strong JWT secret, HTTPS, COOKIE_SECURE=true, institution-specific CORS origins, and approved storage permissions.
3. Run scripts/check.ps1; run npm test; run pip-audit -r requirements.txt and npm audit.
4. Run python scripts/performance_harness.py --seconds 5400 --enforce and archive the console output without media content.
5. Verify browser upload, range seeking, logout/session refresh, correction history, reviewer authorization, PDF traceability and both replay modes using synthetic fixtures.
6. Complete dataset access, licence register and dataset card using written owner approval before any authorized dataset preparation.
7. Install only a verified, locally stored model export. Do not commit weights, embeddings, frames or datasets.
8. Supervisor must review the model and dataset cards before any external research result is circulated.

## Explicitly not completed by this delivery
- No Cholec80 download, dataset preparation, training or model evaluation.
- No M3 detector/tracker or M4 action-triplet model artifact.
- CVS remains an unassessed stub.
- No cloud, clinical or production deployment.
