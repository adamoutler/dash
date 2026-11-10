# Static Assets Module (`src/static/`)

## Overview
The `src/static/` directory contains all frontend HTML, CSS, JavaScript, service worker, and LLM documentation assets required to render the Dashboard UI, the administrative Configuration UI, and the OAuth 2.0 + PKCE authorization flows.

## Key Components & 4-Domain Authentication Contracts

### 1. `index.html` — Public Read-Only Dashboard & Website Login / OAuth Modal (Domains 3 & 4)
- **Behavioral Contract:**
  - Renders the main CI/CD status dashboard (`GET /`) without forcing a browser-level HTTP Basic Auth popup, enabling read-only status and log viewing out of the box.
  - Queries `GET /api/auth/status` on startup (`checkAuthStatus()`) to determine whether the user has an active **Domain 3 (`web_login`)** or **Domain 4 (`web_oauth`)** session.
  - Toggles `document.body.dataset.authenticated` (`"true"` / `"false"`). When `"false"`, all mutating controls (`.write-only`, including `+ Add Repository`, repository delete buttons, `⚙️ Configure` button, and `Logout`) are hidden via CSS (`body:not([data-authenticated="true"]) .write-only { display: none !important; }`), and a `🔒 Login` button is displayed in the header.
  - Provides an accessible `#loginModal` supporting:
    - **Domain 3 (`web_login`)**: Username and password login form submitting `POST /api/auth/login` with CSRF header protection (`X-CSRF-Token` and `X-Requested-With: XMLHttpRequest`).
    - **Domain 4 (`web_oauth`)**: Conditional "Sign in with Google" OIDC button (`/api/auth/oauth/login`) rendered automatically when `website_oauth_enabled` is true in `/api/auth/status`.
- **Performance Expectations:**
  - Asynchronous non-blocking `fetch` calls with `cache: 'no-store'` for auth state and periodic status polling.
- **Failure Modes:**
  - Displays inline error messages inside `#loginError` (`role="alert"`) on `401`/`403` login failures or network errors without losing page state.
  - Automatically opens `#loginModal` if an interactive exploration or mutation request returns `401` or `403`.

### 2. `configure.html` — Administrative Configuration Console (Domains 1, 2, 3, & 4)
- **Behavioral Contract:**
  - Served at `GET /configure` (protected by Website Login `require_web_login` / `require_basic_auth`).
  - Manages all four security and provider domains:
    - **Domain 1 (`api_token`)**: Generates and revokes programmatic Bearer API tokens (`/configure/tokens`), displaying raw tokens only once upon creation and opaque IDs (`tok_<hex>`) thereafter.
    - **Domain 2 (`mcp_oauth`)**: Displays live incoming MCP OAuth 2.0 connection requests (`#oauth-pending-list`) with **Approve** / **Disapprove** buttons and lists connected MCP OAuth sessions (`#oauth-sessions-list`) with revocation controls.
    - **Domain 3 & 4 (`web_login` / `web_oauth`)**: Configures Website OAuth (Google OIDC Client ID, Client Secret, and comma-separated Allowed Emails) alongside CI Provider API Keys (**GitHub**, **Gitea/Forgejo** combined emblem, and **Jenkins**) and Configured Projects.
  - Populates all dynamic text in `#projects-list`, `#tokens-list`, and OAuth lists using safe DOM APIs (`textContent` and `cloneNode`) to prevent DOM XSS.

### 3. `oauth_authorize.html` & `oauth-notify.js` — Domain 2 MCP OAuth Consent & Live Approval Popup
- **Behavioral Contract:**
  - `oauth_authorize.html`: Served at `GET /oauth/authorize` for MCP clients initiating an OAuth 2.0 + PKCE (`S256`) authorization request. Validates the redirect URI client-side (`isSafeRedirectUri` allowing only `https:` or `http://localhost|127.0.0.1|[::1]`), submits the user's identifier to `POST /oauth/authorize`, displays the human-verifiable `user_code` (`DASH-XXXX-XXXX`), and polls `GET /oauth/authorize/status/{request_id}?poll_token=...` every 1.5s until approved, denied, or expired.
  - `oauth-notify.js`: Polls `GET /api/oauth/pending` every 3s when an administrator is logged into the web UI, rendering an accessible live notification toast (`#oauth-popup-container`, `aria-live="polite"`) to approve or deny incoming MCP OAuth requests from any screen.
- **Failure Modes:**
  - Rejects unsafe `redirect_uri` schemes (e.g., `javascript:`, `data:`, or external plain `http:`) on cancel/redirect to prevent open-redirect and XSS attacks.

### 4. `design-system.css` & `sw.js` — Styling & Service Worker
- **`design-system.css`**: Defines light/dark theme CSS custom properties, status card layouts, `.write-only` visibility rules (`body:not([data-authenticated="true"]) .write-only`), login modal styles (`.login-modal-card`, `.google-oauth-btn`), and OAuth toast styles.
- **`sw.js`**: Caches static CSS/icon assets while bypassing HTML templates so authentication state changes take effect immediately.
- **`ProtectedStaticFiles` (`src/main.py`)**: Direct requests to `/static/*.html` return `404 Not Found` so templates can only be served through their authenticated FastAPI route handlers.

### 5. `llms.txt` — Self-Describing Agent & Human Documentation
- Served at `GET /llms.txt` (and referenced by `/.well-known/oauth-protected-resource` `resource_documentation`). Documents how humans and AI agents authenticate and interact with Dash via REST API Tokens (Domain 1) vs. MCP OAuth 2.0 + PKCE (Domain 2).

## Dependencies
- **`src/api/`**: Relies on `/api/auth/*`, `/api/*`, `/configure/*`, and `/oauth/*` endpoints.

## Dependents
- **`src/main.py` & `src/api/routers/oauth.py`**: Serves static files and HTML views via `FileResponse` and `ProtectedStaticFiles`.
