import assert from "node:assert/strict";
import test from "node:test";
import { createVoiceClient } from "../../src/providers/voice/factory.ts";

test("off voice provider is registered and fails without network access", async () => {
  let state = "idle";
  let error;
  const client = createVoiceClient("off", {
    sessionId: "synthetic-session",
    sessionToken: "synthetic-token",
    audio: {},
    telemetry: { record() {} },
    onState(value) {
      state = value;
    },
    onSpeechStarted() {
      return "synthetic-turn";
    },
    onFinalTranscript() {},
    onVoiceStarted() {},
    onAcknowledgment() {},
    onCompleted() {},
    onInterrupted() {},
    onError(value) {
      error = value;
    },
  });

  await client.connect();
  assert.equal(state, "failed");
  assert.deepEqual(error, {
    category: "voice_transport",
    message: "Voice is disabled. Use typed input or configure a voice provider.",
    retryable: false,
  });
});
