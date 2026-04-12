# CI Dashboard AI/Agent Journey

This document outlines the capabilities and typical workflows for an AI, LLM, or automated agent interacting with the CI Dashboard via its REST API and MCP interface.

*   **Discover Capabilities:**
    *   Fetch `GET /llms.txt` to read human-readable instructions on how to interact with the API.
    *   Fetch `GET /api` (redirects to `/docs`) or `GET /openapi.json` to view the interactive Swagger documentation and OpenAPI specification.

*   **Monitor Repositories via REST API:**
    *   **Read All Statuses:** `GET /api/status` returns a JSON array containing the status, timing, commit info, and URLs for all tracked repositories.
    *   **Filter Data:** Use standard JSON parsing tools (like `jq`) to filter the status of a specific repository or owner.
    *   **Get Logs:** `GET /api/logs?provider=...&owner=...&repo=...` fetches the raw text logs of the most recent workflow run.
    *   **Upload Logs:** `POST /api/logs?provider=...&owner=...&repo=...` allows the AI to push log data (up to 2MB, automatically truncating older data) for systems that lack native API log access.
    *   **Get Artifacts:** `GET /api/artifacts?provider=...&owner=...&repo=...` fetches metadata about build artifacts, which is recommended for retrieving build outputs or test summaries.
    *   **Wait for Build (Long-Polling):** `GET /api/wait?provider=...&owner=...&repo=...` holds the connection open, streaming status updates until the build reaches a terminal state (success/failure).

*   **Manage Dashboard Configuration via REST API:**
    *   **List Workflows:** `GET /api/workflows?provider=...&owner=...&repo=...` queries the git provider for available workflows for a given repository.
    *   **Track a Repository:** `POST /api/repos` with a JSON payload containing `provider`, `owner`, `repo`, optional `workflow_id`, and `custom_links` to add it to the dashboard.
    *   **Untrack a Repository:** `DELETE /api/repos` to stop tracking a repository.

*   **Interact via Model Context Protocol (MCP):**
    *   Connect to the MCP JSON-RPC endpoint at `POST /mcp` using a Bearer token (generated in the user UI).
    *   Execute the `get_status` method to retrieve the current CI status, commit message, and timing for a specific repository.
    *   Execute the `get_logs` method to obtain the direct URL to the repository's logs.
    *   Execute the `wait` method to establish a streaming connection that waits for the currently running workflow to finish before returning the final status.
