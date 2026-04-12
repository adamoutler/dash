# Dash User Journey

This document outlines the capabilities and typical workflows for a human user interacting with the Dash.

*   **View Dashboard:**
    *   Navigate to the main dashboard page (`/`).
    *   Observe the list of tracked repositories and their current CI statuses (e.g., ✔ Pass, ✘ Fail, ↻ Run).
    *   View real-time progress bars and Estimated Time of Arrival (ETA) for currently running workflows.
    *   See the latest commit message, timestamp, and human-readable workflow name.

*   **Add a New Repository:**
    *   Click the "+ Add Repository" button.
    *   Select the Git provider (GitHub or Forgejo/Gitea).
    *   Enter the repository Owner (e.g., `adamoutler`) and Repo name (e.g., `dashboard`).
    *   *(Optional)* Click "Load Workflows" to fetch available workflows and select a specific one to track, instead of tracking all workflows.
    *   *(Optional)* Click "+ Add custom link" to associate relevant external links with the repository (e.g., Production environment, Jenkins job, Documentation).
    *   Click "Add" to start tracking the repository.
    *   Observe the new repository appear in the dashboard list.

*   **Interact with Tracked Repositories:**
    *   Click the repository name or commit message to open the repository or specific commit directly on the Git provider's website.
    *   Click on any of the configured custom links (e.g., "🔗 Prod") to navigate to them.
    *   Click the **Logs (📄)** button to open a modal window displaying the raw execution logs for the latest workflow run.
    *   Click the **Edit (✎)** button to modify the tracked repository configuration (e.g., add, remove, or edit custom links).
    *   Click the **Remove (✕)** button to untrack the repository and remove it from the dashboard.

*   **Manage Configuration & Authentication:**
    *   Navigate to the Configuration page (`/configure`).
    *   View a list of all currently configured and tracked projects.
    *   **Manage API Tokens:**
        *   Enter a name and click "Create Token" to generate a new API token for automated access (e.g., for AI agents or MCP clients).
        *   Copy the newly generated token (it is only shown once).
        *   View the list of active tokens.
        *   Click "Revoke" next to a token to invalidate it.
    *   View the Model Context Protocol (MCP) server connection details (URL and Auth Header format).
