# Provider adapters

## Implemented selections

| Lane | Value | Implementation | Evidence |
| --- | --- | --- | --- |
| Voice | `off` | Disabled broker/client | CI-verified |
| Voice | `azure-voice-live` | WebRTC browser adapter and backend broker | Bring your own |
| Agent | `deterministic` | Synthetic fixture worker | CI-verified executable documentation |
| Agent | `foundry` | Prompt Agent adapter | Bring your own |

No other provider value is accepted. Candidate families are design examples, not
shipped support.

## Stable contracts

Voice adapters map provider behavior to:

- connection state;
- final user transcript;
- first output audio;
- constrained acknowledgment;
- completion;
- interruption/cancellation;
- sanitized provider failure.

Agent adapters implement `DeepWorker` and return one bounded `DeepWorkOutput`. They
cannot commit directly. The queue and patch service own ordering, validation, no-op,
atomicity, history, and cancellation suppression.

## Adapter worksheet

Before implementing a provider, answer:

1. What transport is used, and where is the browser/server trust boundary?
2. Where do credentials live, and is keyless access supported?
3. Who owns input transcription and output audio?
4. How are barge-in and interruption represented?
5. Who owns conversation/session persistence?
6. How are tools and structured output supported?
7. What are the provider's retention and privacy terms?
8. What are current rate limits, pricing, and regional constraints?
9. How does each provider event map to normalized application events?
10. How does agent output map to `DeepWorkOutput`?
11. Which unit, contract, browser, and opt-in live tests are required?
12. Which normalized features remain unsupported?

Link current vendor documentation and record the review date/version. Do not copy
volatile tables into the repository.

## Contribution gate

A provider is not supported until:

- it is registered through the appropriate factory;
- unselected-provider imports and network calls are absent;
- lifecycle, cancellation, error, authority, and cleanup contract tests pass;
- any live test is opt-in, keyless where possible, and cleanup-safe;
- docs state exact unsupported behavior and evidence classification.
