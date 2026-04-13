# Dashboard Root Module

## Overview
This is the root folder of the Dashboard project. It contains the main application entrypoint (`main.py`), deployment configurations (`docker-compose.yml`, `Dockerfile`), and top-level settings (`requirements.txt`, `pytest.ini`).

## Dependencies
- `api/`: The backend core logic and endpoints.
- `static/`: The frontend UI elements.
- `data/`: Configuration and persistent JSON storage.
- `logs/`: Where downloaded or fetched log files are temporarily kept.

## Dependents
- `tests/`: The test suite imports the `app` instance from `main.py` for API testing.
- Incoming external web requests hit `main.py` which delegates to the `api/` or `static/` modules.

## AI Methodology & Guidelines
For future AI incarnations working on this project:
1. **Module Independence:** Before creating new features, verify whether they belong in the root `main.py` or should be isolated in `api/`. Prefer modularizing into `api/`.
2. **Documentation Maintenance:** When adding a new directory or significant module, ensure you create a `GEMINI.md` file within that directory outlining its Overview, Dependencies, and Dependents to maintain context for future agents.
3. **Refactoring:** When refactoring, always aim for legibility and code readability. Extract nested functions (e.g., helpers in `api/git_providers.py`) to module-level private functions if they don't depend on closure state to reduce indentation and improve readability.
4. **Testing:** Never commit without running the `pytest` suite. All changes must be verified against the test suite prior to committing.
