# Customization

## Safe customization order

1. Define a wholly synthetic or public domain scenario.
2. Update `fixtures/synthetic-project.json`.
3. Update the three correlated prompts and expected patches in
   `fixtures/scripted-turns.json`.
4. Update deterministic worker mapping, Prompt Agent instructions, document labels, and
   UI copy together.
5. Preserve evidence/inference/unknown classification.
6. Run fixture, patch, parity, frontend, browser, and sensitive-reference checks.

## When a schema revision is required

Text and fixture values do not require a shared contract revision. New fields,
operations, event shapes, bounds, or queue semantics do. For a contract revision:

1. document the rationale and new semantic version;
2. update Python and TypeScript validators;
3. regenerate schemas and fixtures;
4. update `contracts/contract-freeze.json`;
5. rerun every provider, contract, frontend, and browser suite.

## Boundaries

- Do not use real customer/company records, identifiers, prompts, schemas, screenshots,
  environment values, or private repository text.
- Do not weaken atomic patches, authority, cancellation, history, or no-op semantics to
  fit a domain.
- Do not make deterministic fixture text the primary live-product promise.
- Run the external prohibited-term list locally before release review.
