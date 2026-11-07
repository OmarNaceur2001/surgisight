# ADR-002: Frontend session handling

- Status: Accepted
- Context: Browser storage accessible to JavaScript increases exposure of long-lived refresh credentials.
- Decision: Keep short-lived access tokens in module memory and deliver refresh tokens only in HttpOnly, SameSite cookies scoped to /auth.
- Consequences: Page reload restores sessions through the refresh endpoint. Production HTTPS deployments must set COOKIE_SECURE=true; deployments must also apply origin and CSRF protections.
