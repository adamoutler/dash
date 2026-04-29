---
name: skillsafe-scanner
description: Scan AI tool skills, local directories, or remote GitHub repositories for security risks and prompt injection using skillsafe. Use this skill when asked to run a skillsafe scan or fix/improve items mentioned by a skillsafe scan.
---

# Skillsafe Scanner

[![SafeSkill](https://safeskill.dev/api/badge/adamoutler-dash)](https://safeskill.dev/scan/adamoutler-dash)

This skill provides a procedure for scanning an AI tool skill, local directory, or remote repository for security risks and prompt injection using `skillsafe`, and subsequently handling or improving the items mentioned in the scan report.

## When to use

Use this skill whenever you need to:
- Run a security and prompt injection scan on a project, directory, or package.
- Fix issues, vulnerabilities, or improvements mentioned by a `skillsafe scan`.
- Address security risks in AI tool skills or packages.

## Workflow

When asked to scan and improve a package or directory using `skillsafe`, follow these steps in order:

### 1. Execute the Scan

**IMPORTANT: Handling Remote GitHub Repositories**
If the target is a remote GitHub repository (e.g., `adamoutler/dash`), do NOT use `npx skillsafe scan owner/repo`. `skillsafe` uses `npm pack` under the hood, which will fail with a `package.json` `ENOENT` error if the repository is not a Node.js project.
Instead, you MUST clone the repository to a temporary directory and run the scan locally:

```bash
# For a remote GitHub repository
git clone https://github.com/OWNER/REPO.git /tmp/repo-scan
cd /tmp/repo-scan
npx --yes skillsafe@0.2.9 scan .
```

If the target is the current local directory, simply run:
```bash
# For a local directory
npx --yes skillsafe@0.2.9 scan .
```

Ensure you use the `--yes` flag with `npx` so it does not hang on a prompt. Note that the command may exit with code 1 if it finds vulnerabilities or errors, so read its output carefully.

### 2. Analyze the Output
Read the command output. Note down:
- The specific files flagged by `skillsafe`.
- The line numbers or descriptions of the security risks, prompt injection vectors, or malicious code.
- The severity and recommendations provided by the tool.

### 3. Create a Remediation Plan
Determine how to fix each issue:
- If a file contains prompt injection vulnerabilities (e.g., unescaped user input passed to a command or LLM prompt), devise a way to sanitize or parameterize the input.
- If a file contains hardcoded secrets or suspicious remote downloads, remove or secure them.
- Briefly summarize your plan to the user.

### 4. Implement the Fixes
Using file editing tools (like `replace` or `write_file`), implement the fixes outlined in your plan across the affected files. Ensure you preserve the original functionality while eliminating the identified risks.

### 5. Verify the Fixes
Re-run the `skillsafe scan .` command on the modified target to ensure the issues are resolved.
If new or remaining issues are found, return to step 3. Otherwise, confirm to the user that the scan now passes cleanly.
