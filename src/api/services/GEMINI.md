# Workflow Services Module

## Overview
This module houses backend services that coordinate CI/CD status fetching, branch discovery, artifact downloads, and build log resolution across GitHub, Forgejo, and Jenkins providers.

## Key Components

### 1. `workflow_service.py` (`WorkflowService`)
- **`normalize_selector(value)`**:
  - Normalizes branch and workflow filter parameters.
  - Strips leading/trailing whitespace and maps sentinel wildcard strings (`""`, `"any"`, `"all"`, `"none"`, `"null"`, `"undefined"`) as well as `None` to `None`.
  - Ensures file system naming and disk log matching never leak sentinel query tokens into file lookups.
- **`get_log_filename(provider, owner, repo, workflow_id, branch)`**:
  - Constructs sanitized, bounded log filenames: `{provider}_{owner}_{repo}{_branch}{_wf}_latest.log`.
  - Applies character sanitization (`[A-Za-z0-9-_]`) and length caps to prevent filesystem corruption or oversized names.
- **`get_candidate_log_filenames(provider, owner, repo, workflow_id, branch)`**:
  - Returns a prioritized list of candidate filenames from most specific (e.g. branch + workflow) down to the base repository log (`{provider}_{owner}_{repo}_latest.log`).
- **`WorkflowService`**:
  - Instantiates providers dynamically using credentials loaded via `ConfigManager`.
  - Dispatches parallel status checks, branch exploration, and log fetching across configured providers.

## Dependencies
- `src/api/config.py`: Configuration and credential manager.
- `src/api/models/domain.py`: ProviderType and data models.
- `src/api/providers/factory.py`: Provider instantiation factory.

## Dependents
- `src/api/routers/workflows.py`: Route handlers for `/api/status`, `/api/logs`, `/api/wait`, etc.
- `src/api/routers/mcp.py`: MCP tool definitions that query workflows, logs, and statuses.
- `tests/test_workflow_service.py` and `tests/test_logs.py`: Unit and integration test suites.
