# Static Assets Module

## Overview
The `static/` folder contains all frontend assets needed to render the Dashboard UI in the browser. This includes HTML files (`index.html`, `configure.html`, `oauth_authorize.html`), scripts (`oauth-notify.js`, `sw.js`), stylesheets (`design-system.css`), and the web app manifest (`manifest.json`).

## Dependencies
- The frontend code relies on the REST APIs provided by the `api/` module to fetch data, authenticate, and approve/disapprove incoming OAuth 2.0 connection requests.

## Dependents
- **Root (`main.py`) & `api/routers/oauth.py`**: Mounts and serves static assets via FastAPI's `StaticFiles` and `FileResponse`.
