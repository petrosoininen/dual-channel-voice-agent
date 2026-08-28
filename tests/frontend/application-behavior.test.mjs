import assert from "node:assert/strict";
import test from "node:test";

import { isConstrainedAcknowledgment } from "../../src/lib/acknowledgment.ts";
import { parseSafeMarkdown } from "../../src/lib/safe-markdown.ts";
import {
  addLocalTurn,
  applyAppEvent,
  emptyConversationState,
} from "../../src/state/conversation-store.ts";

const UUID = "10000000-0000-4000-8000-000000000001";
const TURN = "20000000-0000-4000-8000-000000000001";
const DOCUMENT = "30000000-0000-4000-8000-000000000001";
const NOW = "2026-03-20T10:00:00Z";

test("acknowledgments allow generative future-process language but reject claims", () => {
  assert.equal(
    isConstrainedAcknowledgment(
      "Understood. I'll review the project context and identify the strongest expansion opportunity.",
    ),
    true,
  );
  assert.equal(
    isConstrainedAcknowledgment(
      "Got it. I'll focus on the operational pain and strengthen the supporting evidence next.",
    ),
    true,
  );
  assert.equal(
    isConstrainedAcknowledgment(
      "Thanks. I can compare the missing evidence and refine the next customer action.",
    ),
    true,
  );
  assert.equal(
    isConstrainedAcknowledgment(
      "Understood. I've identified the strongest opportunity.",
    ),
    false,
  );
  assert.equal(
    isConstrainedAcknowledgment(
      "Understood. The evidence shows that expansion will improve revenue.",
    ),
    false,
  );
});

test("constrained Markdown rejects active content and unsupported syntax", () => {
  assert.deepEqual(parseSafeMarkdown("# Title\n\n## Signals\n- Synthetic item"), [
    { type: "heading", level: 1, text: "Title" },
    { type: "heading", level: 2, text: "Signals" },
    { type: "list", items: ["Synthetic item"] },
  ]);
  for (const invalid of [
    "<img src=x onerror=alert(1)>",
    "[external](https://example.invalid)",
    "![image](data:x)",
    "### Unsupported",
    "Text &lt;script&gt;",
  ]) {
    assert.throws(() => parseSafeMarkdown(invalid));
  }
});

test("invalid document projection fails without replacing the prior card", () => {
  const initial = addLocalTurn(emptyConversationState(), {
    turnId: TURN,
    inputMode: "typed",
    transcript: "Analyze synthetic signals",
    startedAt: NOW,
  });
  const document = {
    documentId: DOCUMENT,
    version: 1,
    title: "Synthetic opportunity",
    status: "draft",
    customerGoal: null,
    currentSituation: null,
    opportunityHypothesis: null,
    supportingSignals: [],
    expectedValue: null,
    stakeholders: [],
    assumptionsAndUncertainties: [],
    missingEvidence: [],
    recommendedNextActions: [],
    confidenceAndRationale: null,
  };
  const committed = applyAppEvent(initial, {
    eventId: "40000000-0000-4000-8000-000000000001",
    idempotencyKey: "50000000-0000-4000-8000-000000000001",
    sessionId: UUID,
    turnId: TURN,
    timestamp: NOW,
    type: "document.created",
    documentId: DOCUMENT,
    version: 1,
    document,
    markdownProjection: "# Synthetic opportunity",
    sourceLabels: [],
  });

  assert.throws(() =>
    applyAppEvent(committed, {
      eventId: "40000000-0000-4000-8000-000000000002",
      idempotencyKey: "50000000-0000-4000-8000-000000000002",
      sessionId: UUID,
      turnId: TURN,
      timestamp: NOW,
      type: "document.committed",
      documentId: DOCUMENT,
      version: 2,
      document: { ...document, version: 2 },
      markdownProjection: "<script>alert(1)</script>",
      sourceLabels: [],
      restoredFromVersion: null,
    }),
  );
  assert.equal(committed.document.version, 1);
  assert.equal(committed.versions.length, 1);
});

test("one canonical document accumulates immutable versions and queue state", () => {
  let state = addLocalTurn(emptyConversationState(), {
    turnId: TURN,
    inputMode: "typed",
    transcript: "Analyze synthetic signals",
    startedAt: NOW,
  });
  state = applyAppEvent(state, {
    eventId: "40000000-0000-4000-8000-000000000003",
    idempotencyKey: "50000000-0000-4000-8000-000000000003",
    sessionId: UUID,
    turnId: TURN,
    timestamp: NOW,
    type: "turn.queued",
    position: 2,
    dependsOnTurnId: null,
  });
  assert.equal(state.turns[0].lifecycle, "queued");
  assert.equal(state.turns[0].queuePosition, 2);
  assert.equal(state.document, null);
});

test("canonical voice and completion events project without deep status regression", () => {
  let state = addLocalTurn(emptyConversationState(), {
    turnId: TURN,
    inputMode: "voice",
    transcript: "Analyze synthetic signals",
    startedAt: NOW,
  });
  const event = (eventId, type, payload = {}) => ({
    eventId,
    idempotencyKey: eventId.replace("40000000", "50000000"),
    sessionId: UUID,
    turnId: TURN,
    timestamp: NOW,
    type,
    ...payload,
  });

  state = applyAppEvent(
    state,
    event("40000000-0000-4000-8000-000000000020", "voice.started"),
  );
  state = applyAppEvent(
    state,
    event(
      "40000000-0000-4000-8000-000000000021",
      "voice.acknowledgment",
      {
        intentSummary: "I understand the requested review.",
        nextStep: "Next, I will assess the synthetic context.",
      },
    ),
  );
  state = applyAppEvent(
    state,
    event(
      "40000000-0000-4000-8000-000000000022",
      "turn.analysis.completed",
      {
        outcome: "no_op",
        summary: "No document changes were needed.",
        documentVersion: 0,
        noOpReason: "The canonical document already contains the supported detail.",
      },
    ),
  );
  state = applyAppEvent(
    state,
    event("40000000-0000-4000-8000-000000000023", "voice.completed"),
  );
  state = applyAppEvent(
    state,
    event(
      "40000000-0000-4000-8000-000000000024",
      "turn.completed",
      {
        audioStatus: "speaking",
        documentStatus: "no_op",
        timings: { totalMs: 20 },
      },
    ),
  );

  assert.equal(state.turns[0].acknowledgment, [
    "I understand the requested review.",
    "Next, I will assess the synthetic context.",
  ].join(" "));
  assert.equal(state.turns[0].completionSummary, "No document changes were needed.");
  assert.equal(
    state.turns[0].noOpReason,
    "The canonical document already contains the supported detail.",
  );
  assert.equal(state.turns[0].documentVersion, 0);
  assert.equal(state.turns[0].audioStatus, "completed");
});
