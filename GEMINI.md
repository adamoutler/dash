# Dashboard Root Module

## Overview
This is the root folder of the Dashboard project. It contains the main application entrypoint (`src/main.py`), deployment configurations (`docker-compose.yml`, `Dockerfile`), and top-level settings (`requirements.txt`, `pytest.ini`).

## 4-Domain Authentication Architecture
Dash enforces strict domain separation across four distinct authentication boundaries so credentials from one domain cannot cross-pollinate or escalate privileges in another:

1. **Domain 1: API Token (`api_token` / `require_api_token`)**
   - **Purpose:** Programmatic REST API access (`/api/status`, `/api/logs`, `/api/wait`, `/api/artifacts`, `/api/branches`, `/api/workflows`, `/api/repos`, `/api/explore/*`) for CI/CD scripts, hooks, and CLI automation.
   - **Behavioral Contract:** Validates `Authorization: Bearer <token>` against SHA-256 hashed entries in `data/tokens.json` with `domain == "api_token"` (or legacy non-OAuth tokens), while also permitting authenticated website administrators (`web_login` / `web_oauth`) or Basic Auth to read/manage resources. Rejects MCP OAuth tokens (`domain == "mcp_oauth"`).
   - **Performance Expectations:** O(N) constant-time digest comparison (`secrets.compare_digest`) over active tokens under a 5-second `FileLock`.
   - **Failure Modes:** Fails closed with `401 Unauthorized` when credentials are missing, expired, or belong to the `mcp_oauth` domain.

2. **Domain 2: MCP OAuth (`mcp_oauth` / `require_mcp_oauth`)**
   - **Purpose:** Dedicated OAuth 2.0 + PKCE (`S256`) Authorization Server for Model Context Protocol (MCP) clients (such as Google Gemini App, Gemini CLI, and Claude) accessing `/mcp`, `/sse`, and root `/` MCP discovery/JSON-RPC probes.
   - **Behavioral Contract:** Implements RFC 9728 Protected Resource Metadata (`/.well-known/oauth-protected-resource`), RFC 8414 Authorization Server Metadata (`/.well-known/oauth-authorization-server`), OpenID Configuration (`/.well-known/openid-configuration`), RFC 7591 Dynamic Client Registration (`/oauth/register`), PKCE `S256` authorization code flow (`/oauth/authorize`, `/oauth/token`), refresh token rotation, and administrator approval in `/configure`. Tokens are isolated to `domain == "mcp_oauth"` (`validate_oauth_token`) or active static API tokens (`api_token`, allowing programmatic MCP clients such as Antigravity); Basic Auth is rejected on MCP endpoints.
   - **Performance Expectations:** Single-use authorization codes expire in 60s; pending approval requests expire in 300s (capped at 50 concurrent requests); registered clients are capped at 200 with oldest-first eviction.
   - **Failure Modes:** Unauthenticated or non-OAuth probes to `/mcp`, `/sse`, or `/` return `401 Unauthorized` with RFC 9728 `WWW-Authenticate: Bearer ..., resource_metadata="..."` and `Link: <...>; rel="oauth-protected-resource"` headers. Replayed authorization codes, invalid PKCE verifiers, or unregistered `redirect_uri` values return `400 Bad Request`.

3. **Domain 3: Website Login (`web_login` / `require_web_login` / `optional_web_login`)**
   - **Purpose:** Human administrator access to the Web UI (`/`, `/configure`), configuration mutations (`/api/settings`, `/configure/*`, `/api/oauth/pending/*`), and interactive repository management.
   - **Behavioral Contract:** Read-only dashboard views (`GET /`, `GET /api/status`, `GET /api/logs`, `GET /api/providers`) are publicly viewable via `optional_web_login` without forcing a browser Basic Auth popup, while write/configuration actions require an authenticated website session (`require_web_login`) established via `POST /api/auth/login` (`src/api/routers/web_auth.py`, using `DASHBOARD_USER` and `DASHBOARD_PASSWORD` into an HMAC-SHA256 signed `dash_session` `HttpOnly`, `SameSite=Lax` cookie with `X-CSRF-Token` validation) or HTTP Basic Auth.
   - **Performance Expectations:** Stateless HMAC-SHA256 cookie verification and constant-time credential verification via `secrets.compare_digest`.
   - **Failure Modes:** Returns `401 Unauthorized` on unauthenticated write/configuration requests and `403 Forbidden` on missing/invalid `X-CSRF-Token` headers for cookie-authenticated state-changing requests.

4. **Domain 4: Website OAuth (`web_oauth`, Google OIDC Relying Party + Email Allowlist)**
   - **Purpose:** Optional third-party federated login ("Sign in with Google") for human administrators on the Website UI (`/api/auth/oauth/login`, `/api/auth/oauth/callback` in `src/api/routers/web_auth.py`).
   - **Behavioral Contract:** Acts as an OpenID Connect (OIDC) Relying Party using configured `web_oauth_client_id` (`GOOGLE_CLIENT_ID`), `web_oauth_client_secret` (`GOOGLE_CLIENT_SECRET`), and `web_oauth_allowed_emails` (`GOOGLE_ALLOWED_EMAILS`). Issues a signed `dash_web_oauth_state` cookie with PKCE `S256` `code_verifier`, exchanges the authorization code with Google's token endpoint, validates the user's verified email against the explicit allowlist, and issues a Website Login session (`dash_session` with `domain="web_oauth"`).
   - **Performance Expectations:** Asynchronous non-blocking HTTP token/userinfo exchange via `httpx.AsyncClient(timeout=10.0)`.
   - **Failure Modes:** Rejects unverified emails, non-allowlisted accounts (`403 Forbidden`), mismatched/expired OAuth `state` cookies (`400 Bad Request`), or upstream Google token errors (`401`/`502`) without creating a session.

## Dependencies
- `src/api/`: The backend core logic, 4-domain authentication guards, providers, and routers.
- `src/static/`: The frontend UI elements, login modal, configure console, and OAuth consent pages.
- `data/`: Configuration and persistent JSON storage (`settings.json`, `tokens.json`, `oauth.json`, `repos.json`).
- `logs/`: Where downloaded or uploaded workflow log files are temporarily kept.

## Dependents
- `tests/`: The test suite imports the `app` instance from `src/main.py` for unit and integration testing across all four auth domains.
- Incoming external web, REST API, and MCP requests hit `src/main.py` which delegates to `src/api/` or `src/static/`.

## AI Methodology & Guidelines
For future AI incarnations working on this project:

### 1. Make code self-describing
* Code must be immediately legible to humans and AIs.
* Every module should have a `GEMINI.md` manifest that describes what it is, what it depends on, and what depends on it.
* Semantic context in every interface and class - provide rules of engagement, not just the data. Semantic context includes:
  - performance expectations
  - failure modes
  - behavioral contracts

### 2. General Practices
* **Module Independence:** Before creating new features, verify whether they belong in the root `src/main.py` or should be isolated in `src/api/`. Prefer modularizing into `src/api/`.
* **Refactoring:** When refactoring, always aim for legibility and code readability. Extract nested functions to module-level private functions if they don't depend on closure state to reduce indentation and improve readability.
* **Testing:** Never commit without running the `pytest` suite. All changes must be verified against the test suite prior to committing.

### 3. CI/CD Monitoring (The Dash)
* **Watch the Dash:** As the developer of Dash, you ABSOLUTELY MUST watch the dash. The user expects you to always do this. You MUST actively monitor the CI/CD pipeline using `gh run watch` or the dash tools immediately after EVERY `git push`.
* **Never Push and Run:** Do not assume a push was successful just because the git command completed. You are responsible for waiting for the CI pipeline to finish and confirming its success or addressing its failure before concluding your task or starting another.

### 4. Before finishing up
Ask questions that a senior or principal engineer might ask:
- Is this code comprehensive?
- Why did you call the dependency here?
- Why is this method or variable here?
- Should this method be broken up?
- Is there a way to remove redundancy while maintaining the context?
- What is the best way to handle the caching of this?
- Are we handling separation of concerns, or are we making it monolithic?

### 5. SonarCloud Configuration
* **Project Key:** `adamoutler_dash`
* **Organization Key:** `adamoutler`
