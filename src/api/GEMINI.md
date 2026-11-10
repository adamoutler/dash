# API Module (`src/api/`)

## Overview
The `src/api/` module provides the core backend functionality for the Dashboard. It implements the 4-domain authentication architecture (`auth.py`), persistent configuration (`config.py`), repository storage (`storage.py`), hierarchical provider exploration (`explore.py`), git/CI provider integrations (`providers/`), workflow orchestration (`services/`), and FastAPI route handlers (`routers/`).

## 4-Domain Authentication Architecture (`src/api/auth.py`)
`src/api/auth.py` enforces strict domain isolation across four authentication domains so credentials from one domain cannot be misused in another:

### 1. Domain 1: API Token (`api_token`, `require_api_token`)
- **Behavioral Contract:**
  - Authenticates programmatic REST API clients via `Authorization: Bearer <token>` where the token record in `TokenManager` (`data/tokens.json`) has `domain == "api_token"` (or legacy API tokens without an `oauth` flag).
  - Also accepts valid Website Login sessions (`web_login` / `web_oauth`) and HTTP Basic Auth (`DASHBOARD_USER` / `DASHBOARD_PASSWORD`) so the browser UI and administrators can invoke API endpoints seamlessly.
  - Explicitly rejects Domain 2 MCP OAuth tokens (`domain == "mcp_oauth"` or `oauth == True`) on general REST API write/management routes to prevent MCP token privilege escalation.
  - Stores only SHA-256 digests (`_hash_token`) on disk; raw tokens are returned only once at creation time and masked behind opaque IDs (`tok_<hex>`) in listings.
- **Performance Expectations:**
  - O(N) lookup over active tokens using constant-time `secrets.compare_digest` inside a `FileLock` (`timeout=5s`) with automatic lazy expiration pruning (`_prune_nolock`).
- **Failure Modes:**
  - Raises `401 Unauthorized` when no valid API token, web session, or Basic Auth credential is provided, or when an expired/revoked/wrong-domain token is presented.
  - Raises `filelock.Timeout` if `data/tokens.json.lock` is held beyond 5 seconds.

### 2. Domain 2: MCP OAuth (`mcp_oauth`, `require_mcp_oauth` / `get_mcp_user`)
- **Behavioral Contract:**
  - Protects the Model Context Protocol endpoints (`/mcp`, `/sse`, and root `/` MCP discovery/JSON-RPC probes).
  - Strictly validates Bearer tokens issued via the OAuth 2.0 + PKCE (`S256`) flow (`validate_oauth_token`, where `domain == "mcp_oauth"` and `oauth == True`). Rejects Domain 1 API tokens (`api_token`) and HTTP Basic Auth on MCP routes.
  - Constructs RFC 9728 compliant challenge headers (`build_mcp_oauth_headers`) pointing to `/.well-known/oauth-protected-resource` using validated host/scheme resolution (`get_base_url` with `SAFE_HOST_RE`).
  - Supports refresh token rotation (`rotate_refresh_token`) where both access and refresh tokens are hashed with SHA-256 at rest and old tokens are atomically invalidated upon rotation.
- **Performance Expectations:**
  - Sub-millisecond header construction and O(N) constant-time digest validation under `FileLock`.
- **Failure Modes:**
  - Raises `401 Unauthorized` with `WWW-Authenticate: Bearer error="invalid_token", ..., resource_metadata="<base_url>/.well-known/oauth-protected-resource"` and `Link: <...>; rel="oauth-protected-resource"` so MCP clients (Google Gemini App, Claude, Gemini CLI) automatically initiate RFC 9728 / RFC 8414 / RFC 7591 OAuth discovery.
  - Falls back to `http://localhost` in `get_base_url` if `Host` or `X-Forwarded-Host` fails `SAFE_HOST_RE` validation (preventing Host header injection).

### 3. Domain 3: Website Login (`web_login`, `require_web_login`, `optional_web_login`)
- **Behavioral Contract:**
  - Manages human administrator authentication for the web dashboard (`/`, `/configure`) and administrative API endpoints (`/api/settings`, `/configure/*`, `/api/oauth/pending/*`, `POST/DELETE /api/repos`, `/api/explore/*`).
  - `optional_web_login`: Used on read-only endpoints (`GET /`, `GET /api/status`, `GET /api/logs`, `GET /api/providers`) to allow anonymous read-only viewing of the dashboard while returning session identity when logged in (or validating optional Basic/Bearer headers if supplied).
  - `require_web_login` (aliased to `require_basic_auth`): Enforces administrator authentication via HMAC-SHA256 signed `dash_session` (`HttpOnly`, `SameSite=Lax`) session cookie (`verify_session_cookie`, created via `POST /api/auth/login` with `DASHBOARD_USER` / `DASHBOARD_PASSWORD`) or HTTP Basic Auth.
  - Enforces CSRF validation (`X-CSRF-Token` header matching the signed session's `csrf` claim via `secrets.compare_digest`) on cookie-authenticated state-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`).
- **Performance Expectations:**
  - Constant-time credential verification (`secrets.compare_digest`) and stateless HMAC-SHA256 cookie signature verification (`verify_signed_payload`).
- **Failure Modes:**
  - Raises `401 Unauthorized` (with `WWW-Authenticate: Session` for XHR/JSON requests or `WWW-Authenticate: Basic` for direct navigation) if credentials are unconfigured (unless `ALLOW_ANONYMOUS_ACCESS=true` is explicitly set) or invalid.
  - Raises `403 Forbidden` (`detail="CSRF token missing or invalid"`) if a cookie-authenticated mutating request lacks a valid `X-CSRF-Token` header.

### 4. Domain 4: Website OAuth (`web_oauth`, Google OIDC Relying Party + Email Allowlist)
- **Behavioral Contract:**
  - Allows human administrators to sign into the Dash Web UI using Google OpenID Connect (`/api/auth/oauth/login` and `/api/auth/oauth/callback` in `src/api/routers/web_auth.py`).
  - Reads `web_oauth_client_id`, `web_oauth_client_secret`, and `web_oauth_allowed_emails` from `ConfigManager` (`data/settings.json`) or environment variables (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_ALLOWED_EMAILS`).
  - Generates a signed `dash_web_oauth_state` cookie containing `state`, PKCE `S256` `code_verifier`, and sanitized `next` path (`_sanitize_next_path`), exchanges the authorization code at Google's OAuth 2.0 token endpoint, verifies `email_verified is True`, checks case-insensitive membership in `allowed_emails`, and issues a `dash_session` cookie with `domain="web_oauth"`.
- **Performance Expectations:**
  - Asynchronous OIDC token exchange and userinfo retrieval using `httpx.AsyncClient(timeout=10.0)`.
- **Failure Modes:**
  - Returns `400 Bad Request` or `401 Unauthorized` if Website OAuth is not configured or the OAuth `state` / `code` is invalid or expired.
  - Returns `403 Forbidden` if the allowlist is empty or the authenticated Google account's email is unverified or not in `web_oauth_allowed_emails`.
  - Returns `502 Bad Gateway` if upstream communication with Google OAuth endpoints fails.

## Dependencies
- **External Packages**: `fastapi`, `httpx`, `pydantic`, `filelock`, `anyio`.
- **Internal Storage**:
  - `data/settings.json`: Provider API keys and Website OAuth (`google_client_id`, `google_client_secret`, `oauth_allowed_emails`) managed by `ConfigManager` (`src/api/config.py`).
  - `data/tokens.json`: SHA-256 hashed API tokens (`api_token`) and MCP OAuth tokens (`mcp_oauth`) managed by `TokenManager` (`src/api/auth.py`).
  - `data/oauth.json`: Dynamic client registrations, pending MCP OAuth approval requests, and single-use PKCE authorization codes managed by `OAuthManager` (`src/api/routers/oauth.py`).
  - `data/repos.json`: Tracked repository definitions managed by `RepoStorage` (`src/api/storage.py`).
  - `logs/`: Uploaded and cached workflow logs.

## Dependents
- **Root (`src/main.py`)**: Mounts all routers and authentication dependencies from `src/api/`.
- **Frontend (`src/static/`)**: Consumes `/api/auth/*`, `/api/*`, `/configure/*`, and `/oauth/*` endpoints.
- **Tests (`tests/`)**: Unit and integration tests validate every module and authentication domain in `src/api/`.
