# Final Security & Code Quality Audit Report
**Scope:** Project as a whole
**Target:** `/home/adamoutler/git/dashboard`

## Executive Summary
The CI Dashboard application has several critical security and stability issues that need immediate attention. The most severe vulnerabilities involve Stored Cross-Site Scripting (XSS) in the frontend and Server-Side Request Forgery (SSRF) combined with Path Traversal in the backend Git integrations. Additionally, there are notable code quality issues, including a critical race condition in data storage and failing test suites, which could lead to data corruption and unreliable deployments.

---

## Priority 1: CRITICAL & HIGH Vulnerabilities (Immediate Action Required)

### 1. Stored Cross-Site Scripting (XSS) via DOM Injection (CRITICAL)
- **Location:** `static/index.html`
- **Description:** The frontend relies on `.innerHTML` to render dynamic content (e.g., `item.commit_message`, `item.custom_links`, and log files from `fetchLogs()`) without proper HTML escaping. An attacker who creates a malicious commit message or uploads a crafted HTML log file can execute arbitrary JavaScript in the browser of any user viewing the dashboard.
- **Remediation:** Replace `.innerHTML` with `.textContent` or `.innerText` for untrusted data. If HTML rendering is required, sanitize the input using a library like DOMPurify.

### 2. Path Traversal / SSRF in Git API Integrations (HIGH)
- **Location:** `api/git_providers.py` and `main.py`
- **Description:** The `owner` and `repo` parameters sourced from `data/repos.json` are concatenated directly into URLs for HTTP requests (e.g., `f"{forgejo_url}/api/v1/repos/{owner}/{repo}"`). An attacker who injects traversal characters (e.g., `owner="..", repo="../admin/users"`) can force the backend to make privileged requests to unintended internal API endpoints.
- **Remediation:** Strictly validate `owner` and `repo` variables against an alphanumeric regex (e.g., `^[a-zA-Z0-9_-]+$`) before saving them or making HTTP requests.

### 3. Data Corruption via Storage Race Condition (HIGH)
- **Location:** `api/storage.py` (`RepoStorage`)
- **Description:** `RepoStorage` reads and writes to `data/repos.json` using `json.load()` and `json.dump()` without any file locking (unlike the auth storage). Concurrent API requests will lead to race conditions, causing silent data corruption or loss of repository configurations.
- **Remediation:** Implement `filelock.FileLock` in `RepoStorage` to ensure atomic reads and writes.

---

## Priority 2: MEDIUM Vulnerabilities

### 4. Cleartext Storage of Authentication Tokens
- **Location:** `api/auth.py` and `data/tokens.json`
- **Description:** Bearer tokens are stored in plain text inside `data/tokens.json`. If this file is leaked (e.g., via a misconfigured backup or directory traversal), all active programmatic access is fully compromised.
- **Remediation:** Store only a cryptographic hash (e.g., SHA-256) of the tokens in the JSON file.

### 5. Privilege Escalation Risk: Docker Runs as Root
- **Location:** `Dockerfile`
- **Description:** The application process runs as the `root` user inside the container by default. Any Remote Code Execution (RCE) vulnerability would immediately grant the attacker root privileges within the container.
- **Remediation:** Create an unprivileged user in the Dockerfile and switch to it using the `USER` directive before the `CMD` instruction.

### 6. Lack of Rate Limiting & Brute-Force Protection
- **Location:** `main.py`
- **Description:** The application does not implement rate limiting for HTTP Basic Auth or heavy endpoints (like `/api/logs` which accepts large payloads). This leaves the system vulnerable to brute-force credential stuffing and CPU/Disk exhaustion (Denial of Service).
- **Remediation:** Implement a rate-limiting middleware (e.g., `slowapi`) to throttle login attempts and heavy POST endpoints.

---

## Priority 3: LOW Vulnerabilities & Code Quality Issues

### 7. Missing Security Headers
- **Location:** `main.py`
- **Description:** The application does not return HTTP security headers (`Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`), weakening the client-side security posture against XSS and clickjacking.
- **Remediation:** Add middleware to inject standard security headers into all responses.

### 8. Log Filename Collisions
- **Location:** `main.py` (`get_log_filename`)
- **Description:** Stripping non-alphanumeric characters to prevent path traversal causes naming collisions (e.g., `my.repo` and `myrepo` resolve to the same file), allowing cross-repository log overwriting.
- **Remediation:** Use a hash function (like MD5/SHA256) of the repo details to generate unique, filesystem-safe log filenames.

### 9. Failing Automated Tests & Unpinned Dependencies
- **Description:**
  - `test_async_client.py` is failing because it lacks the `@pytest.mark.asyncio` decorator and is written as a standalone script instead of a standard pytest function.
  - The `requirements.txt` file uses lower bounds (e.g., `>=`) instead of exact versions (`==`), which can lead to unpredictable and broken builds in production.
- **Remediation:** Fix the failing test and use `pip-compile` or `uv` to generate a fully pinned lockfile.

### 10. Broad Error Handling
- **Location:** `api/git_providers.py`
- **Description:** Asynchronous HTTP requests catch bare exceptions (`except Exception:`), which swallows all errors (including syntax/key errors) and obscures debugging.
- **Remediation:** Catch specific exceptions like `httpx.RequestError` or `httpx.HTTPStatusError`.

---

## Critical Follow-up Questions for the Team
1. **Endpoint Authentication:** Are the API endpoints that write to `data/repos.json` fully authenticated? If an attacker can write traversal characters or inject malicious HTML into repository configurations, how is that endpoint currently protected?
2. **Log Sources:** For the XSS found in logs, what is the exact source of these logs? Are they strictly generated by trusted internal CI runners, or can arbitrary external users/webhooks upload logs?
3. **Environment Access:** Given that `data/tokens.json` stores plain text tokens, who currently has read access to the Docker container or the host filesystem where this is mounted?
