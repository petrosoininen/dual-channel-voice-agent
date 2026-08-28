# Testing and evidence

## Evidence taxonomy

- **CI-verified:** no cloud credentials; covers static checks, schemas, contracts, unit
  tests, deterministic browser behavior, IaC validation, skills, dependencies, and
  sensitive-reference scans.
- **Tenant-validated:** one named IaC implementation completed preview, apply,
  bootstrap, preflights/smoke where available, destroy, and verified cleanup.
- **Illustrative:** historical media only.
- **Bring your own:** requires the user's provider environment and validation.

## Credential-free commands

```text
python -m pytest -q tests/backend tests/contract tests/repository
npm run test:frontend
npm run typecheck
npm run build
npm run test:e2e -- --project=chromium
python -m scripts.generate_contract_schemas --check
python -m scripts.verify_contract_freeze
python -m scripts.validate_iac_parity
python -m scripts.validate_release
az bicep build --file infra/bicep/main.bicep --stdout
az bicep lint --file infra/bicep/main.bicep
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
```

The complete local browser matrix may additionally use installed Chrome and Edge. Public
CI uses bundled Chromium and does not claim physical microphone or provider audio.

## Contract coverage

Schemas link to Python/TypeScript validators through `docs/contract-freeze.md`. Shared
valid/invalid fixtures cover commands, events, and patches. Provider tests cover factory
selection, startup, stable conversation, exactly-once staged tools, no-op, summary
authority, cancellation, sanitized errors, and mode parity.

## Live tests

Live Foundry testing is explicitly enabled with `DCR_RUN_LIVE_FOUNDRY=1` after sanitized
preflight. Browser Voice Live testing requires a real microphone and supported browser.
Neither runs in public pull-request CI.

Tenant results live in [sanitized evidence](evidence/tenant-validation.md). A blocked
provider, policy, role, quota, region, or preview step remains blocked rather than
becoming a deterministic pass.
