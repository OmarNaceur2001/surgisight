# ADR-0003: Database-backed job queue instead of Redis/RQ

**Status**: Accepted  
**Date**: 2026-11-06

## Context
RQ workers do not run on native Windows (no `os.fork`). Redis adds an external service dependency. The project requirement is "no Docker, no Redis" with Windows as the target environment.

## Decision
Implement a database-backed job queue using `analysis_runs` rows claimed with `SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL, and a polling loop with optimistic locking on SQLite (for unit tests).

## Consequences
- No external message broker required.
- Queue is inspectable via standard SQL.
- Throughput is sufficient for the use case (< 10 concurrent analyses).
- Redis can be added later behind the `JobQueue` interface without changing callers.
