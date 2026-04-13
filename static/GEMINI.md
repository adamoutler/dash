# Static Assets Module

## Overview
The `static/` folder contains all frontend assets needed to render the Dashboard UI in the browser. This includes HTML files (`index.html`, `configure.html`), stylesheets (`design-system.css`), and the Progressive Web App (PWA) logic (`sw.js`, `manifest.json`).

## Dependencies
- The frontend code relies on the REST APIs provided by the `api/` module to fetch data, authenticate, and manage configuration.

## Dependents
- **Root (`main.py`)**: Mounts this directory to serve static assets via FastAPI's `StaticFiles`.
