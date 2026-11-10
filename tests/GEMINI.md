# Tests Module (`tests/`)

## Overview
The `tests/` directory contains the `pytest` and `pytest-asyncio` test suite verifying all backend logic, provider integrations, storage invariants, and the 4-domain authentication architecture of the Dashboard application.

## 4-Domain Authentication Test Coverage

### 1. `tests/test_auth.py` — Domain 1 (`api_token`) & Domain 3 (`web_login`) Unit Tests
- **Behavioral Contracts Verified:**
  - `TokenManager` lifecycle: creation, validation, expiration pruning, revocation (by raw token, opaque `tok_<hex>` ID, or refresh token), and 50-thread concurrent `FileLock` safety.
  - Cryptographic storage invariant: verifies raw access tokens and refresh tokens are never written in plaintext to `tokens.json` (only 64-char SHA-256 hex digests and `tok_` opaque IDs).
  - Domain separation: verifies `api_token` (`require_api_token`) vs `mcp_oauth` (`require_mcp_oauth`) vs `web_login` (`require_web_login` / `optional_web_login`) boundaries.
  - Fail-closed security invariant: verifies that unset or whitespace-only `DASHBOARD_USER` / `DASHBOARD_PASSWORD` fail closed with `401 Unauthorized` unless `ALLOW_ANONYMOUS_ACCESS=true` is explicitly enabled.
  - Host header validation: verifies `get_base_url` rejects path/query/scheme injection in `Host` and `X-Forwarded-Host` headers by falling back to `http://localhost`.

### 2. `tests/test_oauth.py` — Domain 2 (`mcp_oauth`) & Domain 4 (`web_oauth`) Integration Tests
- **Behavioral Contracts Verified:**
  - **RFC 9728 Challenge Headers:** Unauthenticated `HEAD`, `GET`, `POST`, and `DELETE` probes to `/mcp`, `/sse`, and `/` return `401 Unauthorized` with `WWW-Authenticate` (`resource_metadata`) and `Link` (`rel="oauth-protected-resource"`) headers.
  - **Metadata Discovery:** Validates `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, and `/.well-known/openid-configuration` (root, subpath, and prefix forms).
  - **Dynamic Client Registration (RFC 7591):** Validates `POST /oauth/register`, `redirect_uri` scheme/host allowlisting, body size cap (`413` over 16KB), URI count cap (`400` over 10 URIs), and oldest-client eviction above `MAX_REGISTERED_CLIENTS` (200).
  - **PKCE S256 & Admin Approval Lifecycle:** Validates end-to-end `POST /oauth/authorize`, `poll_token` constant-time verification (`403` on wrong token, `expired` when omitted), admin approval/denial via `/api/oauth/pending/{id}/approve|deny`, single-use `authorization_code` consumption bound to `client_id` + `redirect_uri` + `code_verifier`, `refresh_token` rotation, and `/oauth/revoke`.
  - **Website Login & Website OAuth (Domains 3 & 4):** Validates `/api/auth/status`, `/api/auth/login`, `/api/auth/logout`, CSRF protection, and Google OIDC `/api/auth/oauth/login` & `/api/auth/oauth/callback` email allowlist enforcement.

### 3. `tests/test_configure.py`, `tests/test_main.py`, & `tests/test_mcp*.py`
- **`tests/test_configure.py`**: Verifies `/configure` access control, opaque token listing (`tok_`), and provider settings persistence.
- **`tests/test_main.py`**: Verifies `/static/*.html` direct-access blocking (`404`), theme support, repository CRUD, and 2MB log upload truncation and path traversal isolation.
- **`tests/test_mcp.py` & `tests/test_mcp_extended.py`**: Verifies MCP JSON-RPC tool calls (`get_status`, `get_logs`, `get_branches`, `wait`), provider conflict resolution, and streaming responses.

## Performance Expectations & Execution
- All tests use isolated `tmp_path` fixtures and mocked network transports so the full suite executes in a few seconds with zero external network dependencies.
- Run via `pytest` from the repository root (`PYTHONPATH=src`). Minimum required coverage is 80%.

## Dependencies
- **`src/main.py` & `src/api/`**: Tested via FastAPI `TestClient` and direct unit imports.
- **External Packages**: `pytest`, `pytest-asyncio`, `httpx`.

## Dependents
- **CI/CD Pipelines (`.github/workflows/dev.yml`, `.github/workflows/prod.yml`, `Jenkinsfile`)**: Execute this suite as a mandatory quality gate on every push and pull request.
