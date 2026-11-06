# ADR-0001: Use PyJWT instead of python-jose

**Status**: Accepted  
**Date**: 2026-11-06

## Context
`python-jose` depends on `ecdsa` which has known timing-side-channel issues and is no longer actively maintained. `PyJWT` is the reference implementation, actively maintained, supports HS256/RS256, and has a clean API.

## Decision
Replace `python-jose` with `PyJWT==2.10.1`.

## Consequences
- `api/main.py` auth helpers must use `jwt.encode` / `jwt.decode` from `PyJWT`.
- Algorithm confusion attacks are mitigated by explicitly passing `algorithms=["HS256"]` to `decode`.
- No `ecdsa` or `rsa` package dependency.
