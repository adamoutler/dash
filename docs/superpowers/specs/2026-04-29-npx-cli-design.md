# Implementation Plan: `npx @adamoutler/dash` CLI Design

## Objective
Create a Node.js CLI tool embedded within the existing Python dashboard repository to allow users to interact with their CI/CD monitoring hub from the terminal.

## UX Architecture (Modern Interactive Approach)

### 1. Output Formatting
*   **Color & Styling:** Use `picocolors` (zero dependencies, extremely fast) for semantic coloring:
    *   Green (`picocolors.green`): Success/Passed
    *   Red (`picocolors.red`): Failed/Errors
    *   Yellow (`picocolors.yellow`): Running/Pending
    *   Cyan (`picocolors.cyan`): Information/Links
*   **Indicators:** Use clear unicode icons (✅, ❌, ⏳, ℹ️) to make statuses easily scannable.
*   **Layout:** Simple, indented list format. Avoid complex tables to ensure mobile/small-terminal compatibility.

### 2. First-Run Experience (Onboarding)
*   If `~/.config/dash/config.json` (or `~/.dashrc`) does not exist or is missing required fields, the CLI will automatically intercept any command and enter an interactive setup mode.
*   **Prompting:** Use `@inquirer/prompts` (lightweight, modern) to ask the user:
    1.  `Dashboard URL:` (e.g., https://dash.example.com)
    2.  `Auth Token:` (input hidden/masked as `***`)
*   Configuration is immediately saved, and the original command resumes seamlessly without requiring the user to type it again.

### 3. Error Handling
*   **API/Network Errors:** If the dashboard is unreachable, display a clear, actionable error: 
    `❌ Error: Cannot connect to dashboard at https://dash.example.com. Please check your connection or update your URL using 'dash config'.`
*   **Authentication Errors:** Catch 401/403 responses and suggest running `dash login` or checking the token.
*   **Build Failures:** For `dash wait`, if a build fails, exit with a non-zero exit code (`process.exit(1)`) so the CLI can be used reliably in scripts.

### 4. Command Structure & Help Menus
*   **Library:** Use `commander` for robust argument parsing, automatic `--help` generation, and versioning.
*   **Commands:**
    *   `dash status [repo]` - View current status of a repository's pipelines.
    *   `dash wait [repo]` - Block and poll until the current running pipeline completes.
    *   `dash login` (or `dash config`) - Manually trigger the interactive setup to update credentials.
*   **Help Output:** `commander` automatically provides a well-formatted help menu displaying commands, arguments, and options.

## Project Structure
The CLI will reside in a dedicated `cli/` directory.

```text
/cli/
├── bin/
│   └── dash.js         # Entry point, sets up 'commander'
├── lib/
│   ├── commands/
│   │   ├── status.js   # Logic for 'status'
│   │   ├── wait.js     # Logic for 'wait'
│   │   └── login.js    # Logic for manual config update
│   ├── config.js       # Handles reading/writing ~/.config/dash/config.json
│   ├── api.js          # Native fetch wrappers with error handling
│   └── ui.js           # Reusable output formatters (colors, icons)
└── package.json        # Merged with root or as a workspace (needs definition in root package.json)
```
