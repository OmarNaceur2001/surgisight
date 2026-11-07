# SurgiSight architecture

> Research prototype — not for clinical use.

## Scope

SurgiSight is a Windows-first modular monolith for reviewing recorded laparoscopic cholecystectomy research videos. It is not a medical device and is not intended for diagnosis, treatment, intra-operative guidance, or clinical decision-making.

~~~mermaid
flowchart LR
  Browser[React review dashboard] -->|REST / WebSocket| API[FastAPI application]
  API --> Auth[JWT roles and audit]
  API --> DB[(PostgreSQL 16 / SQLite tests)]
  API --> Files[Controlled local storage]
  API --> Queue[Database-backed job queue]
  Queue --> Worker[Pipeline orchestrator]
  Worker --> M2[OnlinePhasePipeline]
  Worker --> Analytics[Timeline analytics]
  Analytics --> JSON[Validated report.json]
  JSON --> PDF[ReportLab PDF]
  Browser -->|review corrections| API
~~~

## Runtime boundaries

- The Python package is surgisight/; web/ is a React + TypeScript + Vite application.
- PostgreSQL 16 is the intended Windows deployment database. Unit tests use in-memory SQLite and synthetic fixtures.
- Uploaded media, 1 Hz predictions, 5 Hz detections, embeddings, and model artifacts stay under the configured controlled storage root. They are not repository content.
- The worker queue is database-backed. Redis, RQ, Docker, WSL, Kubernetes, and runtime external APIs are out of scope.
- Report JSON is the sole source of factual report content. The PDF renderer accepts the validated Report model, not free-form strings.
- M2 recorded analysis and live replay use the same OnlinePhasePipeline.step() interface. The pipeline ring buffer is bounded.

## Main data flow

1. An authenticated researcher uploads a permitted research video. The upload path validates the video and stores normalized media locally.
2. A database-backed run is created idempotently.
3. Pipeline providers produce contract-shaped phase, tool, detection, tracking, and triplet outputs. Mock providers are used when the relevant real artifacts are not enabled.
4. Per-second records and five-Hz detections are stored as local Parquet streams. Relational tables index phase, tool, event, triplet, and access metadata.
5. Analytics produce a validated report JSON. PDF export is regenerated only from that JSON.
6. A researcher can submit an append-only correction proposal. A reviewer can transition a report from DRAFT_PENDING_REVIEW to REVIEWED.
7. Saved replay streams persisted contract records; live replay extracts local video frames at 1 Hz and calls the existing M2 online pipeline. Live replay refuses to run unless the real M2 flag is enabled and a valid local artifact is available.

## Security and privacy boundaries

- Short-lived access tokens are kept in frontend module memory.
- Refresh tokens are HttpOnly, SameSite cookies scoped to /auth; HTTPS deployments must set COOKIE_SECURE=true.
- Every protected access is intended to produce an audit record. Media is served through authenticated short-lived URLs/range responses, not public object URLs.
- CORS origins are an explicit allow-list. Wildcard origins are forbidden.
- No patient video, frame, embedding, model weight, dataset archive, or derived dataset file is committed.
- CI uses synthetic test fixtures only. Experiment tracking is metrics-only.

## Research limitations

- Current M2 providers and M3/M4 interfaces do not imply a clinically validated model.
- The Stage 2 summary is deterministic and report-grounded; it is not an external LLM summary.
- Latency measurements are local process measurements, not a production service-level guarantee.
- Cohort statistics are aggregates, not surgeon ratings.
- CVS is an optional not_assessed interface stub.
- PostgreSQL migrations/triggers and the 90-minute Windows performance target require verification on the controlled workstation.
