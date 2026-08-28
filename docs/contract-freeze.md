# Shared contract freeze

## Contract marker

The transport-neutral public contract is **version 1.0.0**. Its machine-readable
authority is `contracts/contract-freeze.json`; `python -m
scripts.verify_contract_freeze` verifies the declared semantics and canonical file
digests.

The freeze covers:

- every app command and event shape;
- the semantic patch schema and bounded opportunity document model;
- one FIFO worker plus three pending turns per conversation;
- queued and running cancellation, late-result suppression, and barge-in
  independence;
- the shared valid/invalid contract fixtures, synthetic project, exact
  three-turn script, and acknowledgment-authority prompt.

## Version 1.0.0 semantics

- The backend owns one canonical document. A valid patch atomically creates one
  next version; a reasoned no-op creates none.
- Each queued turn resolves the latest canonical base only when it starts.
- Duplicate delivery is idempotent only when the complete payload matches.
- Revert creates a new restoring version rather than mutating history.
- Queue capacity is one running plus three pending. Cancellation and rejection
  never commit, including after a non-cooperative late result.
- Voice interruption changes only the audio lane. The committed document is the
  sole findings authority.
- Voice Live generates a natural acknowledgment under concise future-process
  instructions, the lowest supported temperature, and a bounded output-token budget.
- The acknowledgment guard rejects assertive findings and outcomes rather than banning
  analysis vocabulary that is valid in a future next-step statement.
- Generated RTP audio is buffered in the browser until the completed transcript passes
  the acknowledgment guard. Rejected speech is neither played nor added to app state.
- A late transcript event from an interrupted response cannot update acknowledgment
  state.
- Browser-observed voice start, constrained acknowledgment, completion, and
  interruption are strict app commands projected as correlated canonical events.
- Validated analysis completion metadata names the canonical document version; a
  no-op requires its exact accepted reason. Neither field can replace document
  authority.
- Reconnect atomically receives recorded validated events followed by live events.
  Subscriber overflow closes the socket and requires replay recovery.
- Both local WebSocket routes require an allowlisted Origin and Host plus a
  cryptographically random process-memory session secret offered by subprotocol.
- All state is process memory and a new backend process starts empty.

## Change policy

The Foundry Prompt Agent uses a separate two-tool contract and `strict-json-v1`
completion envelope identified by `DCR_DEEP_WORK_CONTRACT_VERSION: 1.0.0`.
Provider metadata cannot expand its authority or alter the browser contract.

Any shared contract change requires:

1. a new semantic contract version and written rationale;
2. regenerated schemas and updated shared fixtures;
3. updated digests in the marker;
4. all implemented producer-mode suites and all affected frontend/browser
   suites to pass again.

Credential-free provider parity and affected browser suites must pass for every
revision. Live provider acceptance remains separate, explicitly labeled evidence.
