# Dash Security Model

## Overview
The Dash implements a **Two-Tiered Authentication System** designed to accommodate both human administrators and autonomous AI agents safely. By default, the application runs in an **unauthenticated (open) mode** to facilitate easy local testing. It must be explicitly locked down for production use.

## 1. Authentication Tiers

### Tier 1: Human Administrators (HTTP Basic Authentication)
*   **Mechanism:** Standard browser-based username and password authentication (`Authorization: Basic ...`).
*   **Configuration:** Governed by two environment variables: `DASHBOARD_USER` and `DASHBOARD_PASSWORD`.
*   **Access Level:** Full administrative access. This is required to view the root UI (`/`), access the configuration panel (`/configure`), and generate or revoke agent tokens.

### Tier 2: Autonomous AI Agents (Bearer Token Authentication)
*   **Mechanism:** Long-lived, securely generated 64-character hex strings (`Authorization: Bearer <token>`).
*   **Configuration:** Tokens are generated via the `/configure` UI by an Administrator and stored locally in `data/tokens.json`.
*   **Access Level:** API-only access. Tokens grant read/write access to core API endpoints (e.g., `/api/status`, `/api/logs`, `/mcp`) necessary for checking CI builds and waiting on pipelines.
*   **Restriction:** Bearer tokens **cannot** be used to access the `/configure` UI or generate new tokens, preventing privilege escalation by rogue agents.

## 2. Locking Down the Dashboard (Enforcing Security)
**The application does NOT lock down automatically when a token is created.** The security model relies entirely on the presence of the administrative environment variables.

If `DASHBOARD_USER` and `DASHBOARD_PASSWORD` are **not** set, the application bypasses all security checks. Anyone can access the dashboard, view logs, and create tokens.

### How to Secure the Application
To enforce security, you must provide the credentials when starting the application.

**Native Execution (Uvicorn):**
When running directly, ensure the variables are exported in your environment or provided via a `.env` file before starting the server:
```bash
export DASHBOARD_USER="admin"
export DASHBOARD_PASSWORD="your_secure_password"
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Docker Compose Configuration:**
When using Docker, provide the credentials in the `environment` block:
```yaml
services:
  ci-dashboard:
    build: .
    ports:
      - "28080:8000"
    environment:
      FORGEJO_URL: "https://git.yourdomain.com"
      FORGEJO_TOKEN: "${FORGEJO_TOKEN}"
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
      LOGS_DIR: "/app/logs"
      # ENABLE AUTHENTICATION BY SETTING THESE VARIABLES:
      DASHBOARD_USER: "admin"
      DASHBOARD_PASSWORD: "your_secure_password"
    volumes:
      - dashboard_data:/app/data
      - dashboard_logs:/app/logs
    restart: unless-stopped
```

Once started with these variables:
1. The dashboard UI (`/`) and configuration page (`/configure`) will prompt for the Basic Auth credentials.
2. The API endpoints (`/api/*`, `/mcp`) will return `401 Unauthorized` unless provided with either the Basic Auth credentials OR a valid Bearer token generated from the configuration page.

## 3. Token Management Lifecycle
1.  **Creation:** An Administrator logs into `/configure` using Basic Auth, provides a friendly name (e.g., "Gemini Agent") and an expiration time, and generates a new token.
2.  **Storage:** Tokens are currently persisted to `data/tokens.json`. *(Note: A pending security patch [DASH-10] will update this to store cryptographic hashes rather than plaintext).*
3.  **Usage:** The agent includes the token in the `Authorization: Bearer <token>` header for programmatic API requests.
4.  **Revocation:** Administrators can instantly revoke active tokens from the `/configure` UI if an agent's access needs to be terminated.
