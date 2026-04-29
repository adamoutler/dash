# SafeSkill Registration and Certification

To register your package (like `dash`) with the SafeSkill registry and link your scan results upstream to safeskill.dev, you must add specific topics or keywords to your project. SafeSkill does not support manual uploads of local scan reports. 

## How to Register

SafeSkill automatically crawls major AI tool marketplaces and GitHub. Ensure your project is indexed by doing one of the following:

*   **For GitHub repositories:** Add one of the following topics to your repository: `mcp-server`, `agent-skills`, `openclaw`, or `claude-skill`.
*   **For npm packages:** Use the keywords `mcp`, `claude-skill`, or `ai-tool` in your `package.json`.
*   **Manual Trigger:** You can also "register" a package in the web cache by visiting **safeskill.dev** and pasting the npm package name or GitHub repository into the scanner.

## How to Scan Locally or in CI

Run the scan locally or in your CI/CD pipeline to analyze your code and prevent vulnerable code from being merged. The CLI exits with code `1` if it scores below 40.

```bash
npx --yes skillsafe scan .
```

## Adding the Badge

Once your project is indexed by SafeSkill, you can display the dynamic badge in your `README.md` using the standard Markdown syntax:

```markdown
[![SafeSkill](https://safeskill.dev/api/badge/your-package-name)](https://safeskill.dev/scan/your-package-name)
```

*(Ensure you replace `your-package-name` with the exact package name defined in your `package.json` or manifest.)*
