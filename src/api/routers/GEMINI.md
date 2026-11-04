# API Routers Module

## Overview
The `api/routers/` module defines the FastAPI route handlers for the Dashboard REST API, Configure UI, OAuth 2.0 + PKCE authorization server (`oauth.py`), and Model Context Protocol (`mcp.py`) server.

## Dependencies
- **`api/auth.py`**: Authentication dependencies (`require_basic_auth`, `get_current_user`, `get_mcp_user`, `token_manager`) and RFC 9728 header builders.
- **`api/storage.py` & `api/config.py`**: Persistent JSON storage for repositories and provider credentials.
- **`api/services/workflow_service.py`**: Core CI/CD status and log retrieval service.

## Dependents
- **Root (`src/main.py`)**: Includes `explore_router`, `settings_router`, `repos_router`, `workflows_router`, `mcp_router`, `config_ui_router`, and `oauth_router`.
- **`tests/`**: Verified by `tests/test_oauth.py`, `tests/test_mcp.py`, `tests/test_configure.py`, and `tests/test_main.py`.
