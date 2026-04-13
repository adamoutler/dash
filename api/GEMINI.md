# API Module

## Overview
The `api/` module provides the core backend functionality for the Dashboard. It manages authentication, configuration, git provider integrations, exploring data, and repo storage.

## Dependencies
- **External Packages**: `fastapi`, `httpx`, `pydantic`, etc.
- **Internal Modules**:
  - `data/` for reading/writing configuration (`settings.json`, `tokens.json`, `repos.json`).
  - `logs/` for writing fetched workflow logs to disk.

## Dependents
- **Root (`main.py`)**: Mounts routers and endpoints from this module.
- **`static/`**: Frontend makes asynchronous HTTP requests to `api/` endpoints to render data.
- **`tests/`**: Extensively tests internal functions and API handlers.
