# SurgiSight user guide

> Research prototype — not for clinical use.

## Access and roles

An administrator provisions accounts with python -m surgisight.api.create_user. The four roles are:

| Role | Capabilities |
|---|---|
| admin | User administration, research, review |
| reviewer | Read records, propose corrections, mark reports reviewed |
| researcher | Upload research videos, request analyses, propose corrections |
| viewer | Read-only access |

Create a dedicated account for each person. Never share passwords or refresh cookies.

## Start on Windows

1. Install Python 3.11, Node.js 20 LTS, PostgreSQL 16 and Git.
2. Copy .env.example to .env. Set a random secret of at least 32 bytes, the institution-approved local DATABASE_URL, explicit CORS_ORIGINS, STORAGE_DIR, and COOKIE_SECURE=true when using HTTPS.
3. Create and activate .venv; install requirements-dev.txt.
4. Run Alembic migrations with the project migration instructions, install frontend dependencies with npm ci, then run scripts/check.ps1.
5. Start API, worker, and Vite with scripts/dev.ps1.

Do not place credentials in Git or send data to external services.

## Review workflow

1. Sign in. The browser holds the access token in memory; refresh credentials are held in an HttpOnly cookie.
2. Use the Library filters to find videos by phase, tool, triplet, or event.
3. Upload only media for which the research team has documented authorization. The upload notice is not a substitute for the dataset licence.
4. Select a video and request an analysis. The run status is displayed in the Library.
5. Open Review to inspect the synchronized video player, phase intervals, uncertainty shading, tool-presence summaries, events, report, and model versions.
6. Click a phase segment or event marker to seek to its timestamp.
7. Submit corrections as proposals. Proposals are append-only and do not silently rewrite source predictions.
8. A reviewer may mark a report REVIEWED. A reviewed report is read-only.
9. Export the PDF. It is generated from the validated report JSON.
10. Stage 2 offers saved prediction replay and an optional live-M2 replay. Live replay is available only when USE_REAL_M2=true and a verified local artifact is installed.

## Interpretation

Confidence and uncertainty describe model output and evidence availability. They do not rate a surgeon. Cohort statistics describe reference data aggregates, not individual performance.

## Troubleshooting

- /health checks API liveness; /health/db checks database connectivity.
- A missing analysis result may mean the worker has not completed the queued run.
- Live M2 replay intentionally refuses to run when the real-model flag is off or a verified local artifact is absent.
- Media and model artifacts must remain under the controlled local storage root.
