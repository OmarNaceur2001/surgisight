# SurgiSight

> **Research prototype — not for clinical use.**

AI surgical video copilot for laparoscopic cholecystectomy.  
Produces phase timelines, tool presence, action triplets, analytics and an operative report from recorded surgery video.

## Setup (Windows, no Docker)

```powershell
# 1. Create and activate venv
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements-dev.txt

# 3. Copy and edit environment file
copy .env.example .env
# Edit .env: set DATABASE_URL, JWT_SECRET, CORS_ORIGINS

# 4. Install pre-commit hooks
pre-commit install

# 5. Run all checks
.\scripts\check.ps1

# 6. Start development servers
.\scripts\dev.ps1
```

## Running tests

```powershell
pytest -q                                  # unit tests (SQLite, synthetic fixtures)
pytest -q -m postgres                      # requires live PostgreSQL
pytest -q -m ffmpeg                        # requires ffmpeg on PATH
```

## Architecture

See `docs/architecture.md` (created at WP12).

## Disclaimer

This software is a university research prototype. It is **not** a medical device and **must not** be used for clinical decision-making.


## WP8–WP12 delivery

- API routes: authenticated analysis status/submission, prediction slices, filtered library, report JSON/PDF, append-only correction proposals, reviewer-only review state, saved/live replay, cohort aggregates and latency metrics.
- Dashboard: login, video library/upload, synchronized review page, phase/tool/event display, report corrections and export.
- Stage 2: report-grounded deterministic summaries with fact checks, paced live M2 replay (requires an installed and enabled local artifact), latency aggregates, and an optional unassessed CVS interface.
- Quality/security: CI lint, formatting, type-check, coverage, tracked-file security guard, dependency audit, frontend tests, and synthetic smoke harness.

See docs/architecture.md, docs/user_guide.md, docs/handover.md, and docs/adr/ for details. See docs/model_card_template.md, docs/dataset_card_template.md and docs/licences/register_template.md before any model/dataset research use.

The complete 90-minute memory acceptance test must be run on the controlled Windows workstation:

~~~powershell
python scripts/performance_harness.py --seconds 5400 --enforce
~~~

The CI harness is a short synthetic smoke test only; it does not substitute for that workstation acceptance test.
