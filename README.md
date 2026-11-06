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
