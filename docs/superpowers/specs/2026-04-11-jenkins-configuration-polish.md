# [UX & Architecture] Jenkins Configuration and Error Handling Polish

## 🎯 Goal
Improve developer experience by providing accurate configuration status, clear error messages, and preventing silent failures when interacting with the Jenkins integration. Ensure robust testing by introducing a mock Jenkins environment.

## 🏗️ Architecture Updates (Backend API Contract)

The API must stop masking errors as generic 404s and stop silently returning empty lists `[]` when prerequisites are not met. It must return appropriate HTTP status codes with semantic error payloads.

**1. Missing Configuration (`/api/explore/jenkins/*`)**
- **Condition:** `JENKINS_URL` (or other required fields) is missing.
- **Status Code:** `400 Bad Request`
- **Response Payload:**
  {
    "error": "configuration_missing",
    "message": "Jenkins URL is not configured. Please update your settings.",
    "missing_fields": ["JENKINS_URL"]
  }

**2. Authentication Failure**
- **Condition:** Jenkins API returns a 401/403 (invalid token, bad user).
- **Status Code:** `401 Unauthorized`
- **Response Payload:**
  {
    "error": "authentication_failed",
    "message": "Jenkins authentication failed. Please verify your User and Token in the configuration."
  }

**3. Actual Not Found**
- **Condition:** The requested Jenkins path or resource truly does not exist.
- **Status Code:** `404 Not Found`
- **Response Payload:**
  {
    "error": "resource_not_found",
    "message": "The requested Jenkins resource could not be found."
  }

## 🎨 UX Structure (Frontend Implementation)

### 1. Configuration Page (`configure.html`)
- **Current State:** Shows "✅ Configured" if *any* auth fields exist (ignoring missing URLs).
- **New State:**
  - Must validate **all** required fields (`JENKINS_URL`, `JENKINS_USER`, `JENKINS_TOKEN`).
  - If any required fields are missing but others exist, display: `⚠️ Incomplete Configuration` (use a warning color like `var(--warning-color, #f59e0b)`).
  - Provide inline validation: Highlight the specific missing input fields (e.g., subtle red border on the URL input).

### 2. Dashboard / Data Exploration Views
When fetching nodes or paths (e.g., `/api/explore/jenkins/nodes`), the UI must gracefully handle the new explicit error states instead of silently rendering an empty list.

**Error States UI Component:**
Display a user-friendly error card or inline alert in the data container:

- **Missing Config (400):**
  - **Icon:** ⚙️ or ⚠️
  - **Title:** Configuration Required
  - **Message:** "Jenkins URL is not configured."
  - **Action:** Render a `[Go to Settings]` button or link.

- **Auth Failed (401):**
  - **Icon:** 🔒
  - **Title:** Authentication Failed
  - **Message:** "Unable to connect to Jenkins. Please verify your credentials."
  - **Action:** Render an `[Update Credentials]` button or link.

- **Generic/Network Error (500+):**
  - **Icon:** 🔌
  - **Title:** Connection Error
  - **Message:** "Could not reach the Jenkins server. Please check the URL and your network connection."

## 💻 Developer Implementation Guide

1. **Backend:** Update the Jenkins API wrapper (likely in `api/explore.py` or `api/git_providers.py`) to validate settings *before* making the request. Catch specific `httpx` or `requests` exceptions for upstream Jenkins calls and map them to the standardized JSON responses above.
2. **Frontend Settings:** Update the validation logic in the settings Javascript to check for truthy values on *all* required Jenkins keys before setting the 'Configured' UI status.
3. **Frontend Views:** Add error handling to the fetch logic. Read the `error` key from the JSON response and render the appropriate error state template instead of iterating over an empty array.
4. **Testing (Mock Jenkins):** Introduce a mock Jenkins setup in the test suite (e.g., using `httpx` mocking or `unittest.mock.MagicMock` similar to existing GitHub tests in `test_git_providers.py`). Ensure tests cover the new 400 and 401/403 error states for `jenkins_explore` and validate that missing `JENKINS_URL` correctly flags the provider as unconfigured.
