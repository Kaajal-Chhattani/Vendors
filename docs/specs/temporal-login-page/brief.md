# Temporal UI login page

## Problem Statement
Temporal UI (port 8080, nginx) is protected by the browser's native Basic Auth dialog (`auth_basic`), which cannot be styled and looks poor.

## Users
Anyone who needs the Temporal UI URL. Internal/local network only for now.

## Inputs
Username + password of any active Django user. Django is the single source of truth: new users and password changes work on Temporal immediately, nothing is copied to `.htpasswd`.

## Outputs
- Styled login page matching the chat page: logo + title, show/hide password toggle.
- Signed session cookie valid 8 hours.
- Logout link/endpoint that clears the cookie.
- Authenticated requests proxied to `temporal:8233` as today.

## Integrations
| System | Role |
|---|---|
| nginx (`vendors_temporal_ui_proxy`) | `auth_request` to auth service; redirects unauthenticated browsers to `/login`; WebSocket upgrade kept |
| New auth container (small Python) | Serves `/login`, `/logout`, `/auth` check; verifies password against `.htpasswd`; issues/validates signed cookie |
| Django (chat app) | New POST endpoint that checks username/password with `authenticate()` and returns ok only for active users; protected by a shared secret header |
| Temporal UI | Unchanged |

## Operational
New service in `docker-compose.temporal.yml`; code in `nginx/auth/`. Cookie signing secret via env var. Logs to container stdout.

## Acceptance Criteria
1. Opening :8080 without a session shows the styled login page, not the native popup.
2. Correct existing credentials log in; wrong ones show an inline error.
3. After login Temporal UI works, including live updates (WebSocket).
4. Session expires after 8 hours; logout ends it immediately.
5. Password toggle works.

## Out of Scope
HTTPS, rate limiting, Django SSO, Basic Auth fallback (dropped), changes to Temporal itself, hardening for public exposure.

## Constraints
Do not touch `apps`/Django code; `.htpasswd` and its volume mount are retired; internal-only exposure.

## Open Questions
- Logo file: which image to use (path)?
- Django base URL the container uses (e.g. `http://host.docker.internal:8000`) and shared secret env `TEMPORAL_AUTH_DJANGO_SECRET`?
- Cookie secret: ok to read from an env var `TEMPORAL_AUTH_SECRET`?
