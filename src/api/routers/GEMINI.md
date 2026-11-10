# API Routers Module (`src/api/routers/`)

## Overview
The `src/api/routers/` package defines the FastAPI route handlers for the Dashboard REST API, Website Login & Website OAuth flows, Configure UI backend, MCP OAuth 2.0 + PKCE Authorization Server (`oauth.py`), and Model Context Protocol (`mcp.py`) server.

## Router Responsibilities & 4-Domain Auth Mapping

### 1. `oauth.py` — Domain 2: MCP OAuth 2.0 + PKCE Authorization Server (`mcp_oauth`)
- **Discovery Endpoints (RFC 9728 & RFC 8414 & OIDC):**
  - `GET/HEAD /.well-known/oauth-protected-resource` (plus subpath/prefix variants)
  - `GET/HEAD /.well-known/oauth-authorization-server` (plus subpath/prefix variants)
  - `GET/HEAD /.well-known/openid-configuration` (plus subpath/prefix variants)
- **Dynamic Client Registration (RFC 7591):**
  - `POST /oauth/register`: Registers public/confidential MCP clients (`mcp_<hex>`), enforcing strict `redirect_uri` validation (`https://` or `http://localhost|127.0.0.1|[::1]`, no fragments or credentials, max 10 URIs/client, max 200 clients with oldest-first eviction).
- **Authorization & Admin Approval Flow:**
  - `GET /oauth/authorize`: Serves `src/static/oauth_authorize.html` with `X-Frame-Options: DENY` and `Cache-Control: no-store`.
  - `POST /oauth/authorize`: Validates `username`, `client_id`, registered `redirect_uri`, and PKCE `S256` `code_challenge` (`PKCE_CHALLENGE_RE`), creating a pending request (`TTL=300s`, max 50 pending) with a SHA-256 hashed `poll_token`.
  - `GET /oauth/authorize/status/{request_id}`: Constant-time `poll_token` verification (`DUMMY_POLL_HASH`) returning `pending`, `approved` (with `redirect_url`), `denied`, or `expired`.
  - `GET /api/oauth/pending`, `POST /api/oauth/pending/{request_id}/approve`, `POST /api/oauth/pending/{request_id}/deny`, `DELETE /api/oauth/sessions/{token}`: Protected by Website Login (`require_web_login` / `require_basic_auth`) for administrator approval and session revocation.
- **Token Exchange & Revocation:**
  - `POST /oauth/token`: Exchanges single-use `authorization_code` (`TTL=60s`) + PKCE `code_verifier` (`_verify_pkce_s256`) or `refresh_token` for a Domain 2 `mcp_oauth` Bearer token (`oauth=True`, `domain="mcp_oauth"`).
  - `POST /oauth/revoke`: Revokes an access or refresh token.

### 1b. `web_auth.py` — Domain 3 (Website Login `web_login`) & Domain 4 (Website OAuth `web_oauth`)
- `GET /api/auth/status`: Returns current browser authentication state (`authenticated`, `username`, `domain`, `csrf_token`, `website_login_enabled`, `website_oauth_enabled`, `website_oauth_provider`).
- `POST /api/auth/login`: Verifies administrator `username` and `password` (`get_web_login_credentials`) in constant time and sets an HMAC-SHA256 signed `dash_session` cookie (`HttpOnly`, `SameSite=Lax`, `domain="web_login"`, `TTL=86400s`).
- `POST /api/auth/logout`: Deletes the `dash_session` cookie and clears website session state.
- `GET /api/auth/oauth/login` & `GET /api/auth/oauth/callback` (plus `/api/auth/google/login` and `/api/auth/google/callback` aliases): Initiates and completes the Domain 4 Google OIDC Relying Party + PKCE `S256` login flow using signed `dash_web_oauth_state` cookies (`TTL=300s`), verifying `email_verified is True` and checking case-insensitive email membership in `web_oauth_allowed_emails` (`GOOGLE_ALLOWED_EMAILS`) before issuing a `dash_session` cookie (`domain="web_oauth"`).

### 2. `mcp.py` — Domain 2: Model Context Protocol Server (`require_mcp_oauth` / `get_mcp_user`)
- **Endpoints:** `GET/HEAD/POST/DELETE /mcp`, `GET/HEAD/POST/DELETE /sse`, and root `/` MCP discovery/JSON-RPC dispatch.
- **Behavioral Contract:**
  - Protected by `get_mcp_user` (`require_mcp_oauth`), which challenges unauthenticated requests with RFC 9728 `WWW-Authenticate` and `Link` headers.
  - Exposes MCP tools `get_status`, `get_logs`, `get_branches`, and `wait` over JSON-RPC 2.0 (`2024-11-05`, `2025-03-26`, `2025-06-18`) and SSE streamable-HTTP transport.
- **Performance Expectations:**
  - `wait` streams whitespace keepalives every 10s (up to `MAX_WAIT_ITERATIONS = 360`) until a build reaches a terminal state.
- **Failure Modes:**
  - Returns JSON-RPC `-32600` (Invalid Request), `-32601` (Method not found), `-32602` (Invalid params / provider conflict), or `-32000` (Internal error) without leaking stack traces.

### 3. `config_ui.py` — Domain 3: Configure UI & Domain 1 Token Management (`require_web_login` / `require_basic_auth`)
- **Endpoints:** `GET /configure/data`, `POST /configure/tokens`, `DELETE /configure/tokens/{token}`.
- **Behavioral Contract:**
  - Strictly requires Website Login / administrator authentication (`require_web_login` / `require_basic_auth`). API Bearer tokens and MCP OAuth tokens cannot create or revoke tokens.
  - Creates Domain 1 API tokens (`domain="api_token"`) and lists masked token metadata (`tok_<hex>`) alongside pending MCP OAuth requests and connected OAuth sessions.

### 4. `settings.py` — Domain 3: Provider & Website OAuth Settings (`require_web_login` / `optional_web_login`)
- **Endpoints:** `GET /api/settings`, `POST /api/settings`, `GET /api/providers`.
- **Behavioral Contract:**
  - `GET /api/settings` and `POST /api/settings` require administrator authentication (`require_web_login` / `require_basic_auth`) to view configuration flags or update GitHub/Forgejo/Jenkins credentials and Website OAuth settings (`google_client_id`, `google_client_secret`, `oauth_allowed_emails`).
  - Validates provider URLs via `_validate_provider_url` (rejecting non-HTTP/HTTPS schemes, embedded credentials, query strings, or fragments).
  - `GET /api/providers` supports read access so the dashboard UI can determine which providers are active.

### 5. `repos.py` — Domain 1 & Domain 3: Repository Tracking (`require_api_token` / `require_web_login`)
- **Endpoints:** `POST /api/repos`, `DELETE /api/repos`.
- **Behavioral Contract:**
  - Requires authenticated write access (`get_current_user` / `require_web_login` / `require_api_token`) to add or remove tracked repositories in `RepoStorage`. Unauthenticated anonymous users cannot mutate tracked repositories.

### 6. `workflows.py` — Domain 1 & Domain 3: CI/CD Status, Logs, Artifacts, and Wait (`optional_web_login` / `require_api_token`)
- **Endpoints:** `GET /api/status`, `GET /api/logs`, `POST /api/logs`, `GET /api/wait`, `GET /api/artifacts`, `GET /api/branches`, `GET /api/workflows`.
- **Behavioral Contract:**
  - Read endpoints (`GET /api/status`, `GET /api/logs`) allow dashboard viewing and Domain 1 API Token access (`require_api_token` / `get_current_user`).
  - `POST /api/logs` requires authenticated access (`require_api_token` / `get_current_user`), streams request chunks with a 2MB tail-truncation cyclic buffer (`MAX_LOG_SIZE`), and sanitizes filenames against path traversal (`LOGS_DIR` prefix check).

## Dependencies
- **`src/api/auth.py`**: 4-domain authentication guards, `TokenManager`, and RFC 9728 header builders.
- **`src/api/storage.py` & `src/api/config.py`**: FileLock-backed JSON persistence for repositories and settings.
- **`src/api/services/workflow_service.py`**: Asynchronous CI/CD status, branch, artifact, and log retrieval service.

## Dependents
- **Root (`src/main.py`)**: Mounts all routers onto the FastAPI `app`.
- **Tests (`tests/`)**: Verified by `tests/test_auth.py`, `tests/test_oauth.py`, `tests/test_mcp.py`, `tests/test_configure.py`, and `tests/test_main.py`.
