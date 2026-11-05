# Static Assets Module

## Overview
The `static/` folder contains all frontend assets needed to render the Dashboard UI in the browser. This includes HTML files (`index.html`, `configure.html`, `oauth_authorize.html`), scripts (`oauth-notify.js`, `sw.js`), stylesheets (`design-system.css`), and the web app manifest (`manifest.json`).

## Key Components & Behavioral Contracts
- **`configure.html`**: Renders the administrative configuration interface (`/configure`), including OAuth 2.0 request approval, API token management, Provider API Keys (with inline SVG icons for **GitHub**, **Gitea/Forgejo** combined emblem, and **Jenkins**), and Configured Projects. All dynamic text in `#projects-list`, `#tokens-list`, and OAuth lists is populated via safe DOM APIs (`textContent` and `cloneNode`) to prevent XSS.
- **`design-system.css`**: Defines light/dark theme CSS custom properties and shared layout styles, including `.provider-header-icon` and `.provider-header-icon-combined` sizing rules for provider emblems.
- **`index.html`**: Main dashboard view displaying live CI/CD status cards, logs modal, and cascading repository selector.

## Dependencies
- The frontend code relies on the REST APIs provided by the `api/` module to fetch data, authenticate, and approve/disapprove incoming OAuth 2.0 connection requests.

## Dependents
- **Root (`main.py`) & `api/routers/oauth.py`**: Mounts and serves static assets via FastAPI's `StaticFiles` and `FileResponse`.
