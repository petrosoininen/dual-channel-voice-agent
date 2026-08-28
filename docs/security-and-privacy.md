# Security and privacy

## Trust boundaries

- Browser commands, WebSocket frames, model output, provider events, and tool arguments
  are untrusted.
- Backend-created session/turn/document IDs are authoritative; provider IDs are opaque.
- Environment files and IaC runtime artifacts are operator secrets/private metadata.
- The canonical document changes only through the semantic patch service.

## Implemented controls

- keyless `DefaultAzureCredential`; no access-key fallback;
- strict provider selection and fail-closed startup;
- local Origin/Host checks plus random process-memory WebSocket session secret;
- bounded JSON contracts with unknown fields rejected;
- exact tool allowlist and one staged patch transaction per Foundry turn;
- full patch validation and atomic commit;
- cancellation and late-result suppression;
- constrained Markdown rendering without raw HTML;
- sanitized client/server errors and content-free telemetry;
- no application audio persistence;
- generated-state, secret, path, hostname, identifier, and external-term scans.

## Data flow

Audio travels between the browser and selected voice provider over realtime media. The
backend controls negotiation but does not store audio. Final transcript text enters the
app event lane and exists in process memory. The agent receives bounded synthetic
context and the current canonical document. Provider-side processing follows your
resource configuration and service terms.

## Non-goals

This reference does not implement production user identity, authorization, tenant
isolation, durable encrypted storage, retention/deletion policy, private networking,
DLP, audit trails, backup/recovery, regulatory controls, load protection, incident
response, or regional failover.

## Threat-oriented change checklist

- Does a new input cross a trust boundary without bounds or validation?
- Can any provider output bypass document authority?
- Can cancellation race with commit?
- Can a URL, token, identifier, transcript, or provider error reach logs or UI?
- Can an unselected provider import credentials or initiate network access?
- Can a cleanup command target a pre-existing resource?
- Does a new dependency or workflow broaden supply-chain permissions?

Report vulnerabilities through the private process in `SECURITY.md`; do not include
secrets or real environment details.
