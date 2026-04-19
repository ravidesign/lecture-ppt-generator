# Teach-On Admin Security Plan

## Scope
- Dashboard/session authentication
- Request rate limiting
- Dashboard IP allowlist

## App-Level Controls
- Session login via `TEACHON_ADMIN_USERNAME` + `TEACHON_ADMIN_PASSWORD` or `TEACHON_ADMIN_PASSWORD_HASH`
- Header token fallback via `TEACHON_ADMIN_TOKEN`
- Dashboard/API IP filtering via `TEACHON_DASHBOARD_IP_ALLOWLIST`
- In-memory rate limiting for login, dashboard mutations, heavy jobs, API, and page traffic

## Default Behavior
- If no admin password/hash and no token are set, dashboard stays open with warnings
- If password auth is set, dashboard data APIs require a valid session or admin token
- If token auth is set, automation can keep using `X-TeachOn-Token`

## Reverse Proxy / Deployment Recommendation
- Restrict `/dashboard` and `/api/dashboard/*` at the edge when the hosting platform supports IP or auth rules
- Keep app-level allowlist enabled even when proxy rules exist as a defense-in-depth layer
- Set `SESSION_COOKIE_SECURE=true` in HTTPS production

## Environment Variables
- `TEACHON_ADMIN_USERNAME`
- `TEACHON_ADMIN_PASSWORD`
- `TEACHON_ADMIN_PASSWORD_HASH`
- `TEACHON_ADMIN_TOKEN`
- `TEACHON_DASHBOARD_IP_ALLOWLIST`
- `SESSION_COOKIE_SECURE`
- `MAX_UPLOAD_MB`

## Verification Checklist
- Wrong login is rejected
- Correct login unlocks dashboard APIs
- Stored token unlocks dashboard APIs
- Dashboard requests from blocked IPs return 403
- Excess login attempts return 429
- Dashboard connectors remain protected behind auth
