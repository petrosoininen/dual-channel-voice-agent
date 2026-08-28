# Contributing

Thank you for improving this reference.

## Before a change

1. Read `AGENTS.md` and the matching `.agents/skills/*/SKILL.md`.
2. Open an issue for new providers, shared contract changes, or infrastructure changes.
3. Use only public or clearly synthetic data and examples.
4. Do not include real environment values, logs, screenshots, or provider identifiers.

## Development

```text
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS or Linux
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
npx playwright install chromium
python -m pytest -q tests/backend tests/contract tests/repository
npm run test:frontend
npm run typecheck
npm run build
npm run test:e2e -- --project=chromium
python -m scripts.validate_release
```

Update Bicep and Terraform together. Run what-if/plan before any explicitly authorized
ephemeral validation and verify cleanup. Never use contribution testing to modify a
pre-existing cloud resource.

## Pull requests

Keep changes focused. State which evidence is CI-verified, tenant-validated,
illustrative, bring-your-own, or unexecuted. A mock or static check is not live-provider
evidence.

By contributing, you agree that your contribution is licensed under MIT.
