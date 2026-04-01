# CI Status Dashboard Design

## Purpose
A Dockerized dashboard to monitor CI/CD action statuses across multiple git providers (GitHub and Forgejo/Gitea).

## User Interface
- A clean list view with large fonts.
- Each entry takes up 2 lines.
- Left block: Color-coded status (Pass/Fail/Running) which acts as a clickable link to the specific CI action run.
- Right block: Repository owner/repo name, last updated time, and the first line of the last commit message. Clickable link to the repository.
- Header: A "+" button to add new repositories to monitor.
- Repository items: An "x" button to remove the repository from the dashboard.
- "Add" flow: Select provider (GitHub/Forgejo), input owner/repo.

## Architecture
- **Backend:** Node.js (Express) or Python (FastAPI). Let's go with **Python (FastAPI)** as it's excellent for rapid API development and handles concurrent async requests (like polling multiple git APIs) very cleanly.
- **Frontend:** Vanilla HTML/CSS/JS. No heavy frameworks needed for a simple polling dashboard.
- **Storage:** A local JSON file (`data/repos.json`) storing the list of monitored repositories (`provider`, `owner`, `repo`). A Docker volume will be used to persist this file.
- **Authentication:** Credentials provided via Environment Variables to the Docker container:
  - `FORGEJO_URL` (e.g., `https://git.adamoutler.com`)
  - `FORGEJO_TOKEN`
  - `GITHUB_TOKEN`

## Data Flow
1. Frontend polls the backend API every X seconds (e.g., 30s) for status updates.
2. Backend reads `repos.json` to get the list of monitored repos.
3. Backend concurrently fetches the latest CI run status and latest commit info from GitHub and Forgejo APIs using the provided tokens.
4. Backend aggregates the results and returns them to the frontend.
5. When a user adds/removes a repo via the UI, the frontend calls a backend endpoint which updates `repos.json`.

## Error Handling
- Invalid repo names or missing permissions will return an "Error" status for that item.
- Network timeouts or API rate limits will log an error on the backend and potentially show a "warning/stale" state on the frontend.
