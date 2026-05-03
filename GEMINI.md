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

### 1. Make code self-describing
* Code must be immediately legible to humans and AIs.
* Every module should have a `GEMINI.md` manifest that describes what it is, what it depends on, and what depends on it.
* Semantic context in every interface and class - provide rules of engagement, not just the data. Semantic context includes:
  - performance expectations
  - failure modes
  - behavioral contracts

### 2. General Practices
* **Module Independence:** Before creating new features, verify whether they belong in the root `main.py` or should be isolated in `api/`. Prefer modularizing into `api/`.
* **Refactoring:** When refactoring, always aim for legibility and code readability. Extract nested functions (e.g., helpers in `api/git_providers.py`) to module-level private functions if they don't depend on closure state to reduce indentation and improve readability.
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
