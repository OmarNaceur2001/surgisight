# ADR-0002: Use pwdlib[argon2] instead of passlib

**Status**: Accepted  
**Date**: 2026-11-06

## Context
`passlib` is in maintenance-only mode and not compatible with Python 3.13+. `pwdlib` is a modern replacement with native argon2 support via `argon2-cffi` (already installed).

## Decision
Use `pwdlib[argon2]` for password hashing.

## Consequences
- Argon2id is used (memory-hard, recommended by OWASP).
- Hash format is compatible with argon2-cffi's reference format.
- Simple migration if we ever switch backends: same `verify` interface.
