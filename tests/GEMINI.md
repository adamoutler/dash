# Tests Module

## Overview
The `tests/` folder contains the pytest-based test suite ensuring the reliability and correctness of the Dashboard application.

## Dependencies
- **`api/`**: Almost all internal unit tests are targeting the backend code within `api/`.
- **Root (`main.py`)**: Uses the FastAPI `TestClient` initialized from the root app to test end-to-end endpoint logic.
- **External Dependencies**: `pytest`, `pytest-asyncio`, and `httpx` (for test requests).

## Dependents
- The CI/CD pipelines (e.g., GitHub Actions in `.github/workflows/`) run this test suite to validate changes.
