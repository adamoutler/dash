# Static Images

## Overview
Contains graphical assets and icons used by the frontend UI, manifest, and MCP/OAuth endpoints:
- `icon-192.png`: 192x192 high-resolution brand logo.
- `icon-512.png`: 512x512 high-resolution brand logo.
- `icon-48.png`: 48x48 compact brand logo for inlining into MCP `serverInfo.icons` and `tools/list` definitions.
- `icon-64.png`: 64x64 compact brand logo.
- `maskable-icon.png`: Maskable icon for PWA web manifest.
- `jenkins.svg`: Official Jenkins SVG icon used in UI.

## Dependencies
- None.

## Dependents
- `static/index.html` and `static/manifest.json`.
- `api/routers/mcp.py` and `main.py` for MCP icon metadata and static routes.
