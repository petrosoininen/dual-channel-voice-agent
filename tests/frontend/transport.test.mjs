import assert from "node:assert/strict";
import test from "node:test";

import { AppEventClient } from "../../src/lib/app-event-client.ts";
import { ContentFreeTelemetry } from "../../src/lib/telemetry.ts";
import { AzureVoiceLiveClient } from "../../src/providers/voice/azure-voice-live.ts";

globalThis.window = {
  location: { protocol: "http:", host: "127.0.0.1:5174" },
  setTimeout,
  clearTimeout,
};
globalThis.WebSocket = { OPEN: 1 };

class FakeTarget {
  listeners = new Map();

  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) ?? [];
    handlers.push(handler);
    this.listeners.set(name, handlers);
  }

  removeEventListener(name, handler) {
    this.listeners.set(
      name,
      (this.listeners.get(name) ?? []).filter((item) => item !== handler),
    );
  }

  emit(name, event = {}) {
    for (const handler of this.listeners.get(name) ?? []) {
      handler(event);
    }
  }
}

class FakeSocket extends FakeTarget {
  readyState = 0;
  sent = [];

  open() {
    this.readyState = 1;
    this.emit("open");
  }

  send(value) {
    this.sent.push(value);
  }

  close(code = 1000) {
    this.readyState = 3;
    this.emit("close", { code, currentTarget: this });
  }
}

class FakeMediaRecorder extends FakeTarget {
  state = "inactive";
  mimeType = "audio/webm";

  start() {
    this.state = "recording";
  }

  stop() {
    if (this.state === "inactive") {
      return;
    }
    this.state = "inactive";
    this.emit("dataavailable", {
      data: new Blob(["synthetic audio"], { type: this.mimeType }),
    });
    this.emit("stop");
  }
}

test("app reconnect creates a fresh transport and never replays a sent turn", async () => {
  const sockets = [];
  const handshakes = [];
  const client = new AppEventClient(
    {
      sessionId: "10000000-0000-4000-8000-000000000001",
      sessionToken: "A".repeat(43),
    },
    {
      telemetry: new ContentFreeTelemetry(),
      onEvent() {},
      onState() {},
      onError() {},
      onSessionUnavailable() {},
      retryDelayMs: 1,
      maxReconnectAttempts: 1,
      webSocketFactory(url, protocols) {
        const socket = new FakeSocket();
        sockets.push(socket);
        handshakes.push({ url, protocols });
        return socket;
      },
    },
  );
  client.connect();
  sockets[0].open();
  client.send({
    type: "turn.submit",
    commandId: "20000000-0000-4000-8000-000000000001",
    idempotencyKey: "30000000-0000-4000-8000-000000000001",
    sessionId: "10000000-0000-4000-8000-000000000001",
    turnId: "40000000-0000-4000-8000-000000000001",
    timestamp: "2026-03-20T10:00:00Z",
    inputMode: "typed",
    transcript: "Synthetic turn",
  });
  assert.equal(sockets[0].sent.length, 1);
  sockets[0].close();
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(sockets.length, 2);
  assert.equal(handshakes[0].url.includes("A".repeat(43)), false);
  assert.deepEqual(handshakes[0].protocols, [
    "dcr-app-events.v1",
    `dcr-session.${"A".repeat(43)}`,
  ]);
  sockets[1].open();
  assert.deepEqual(sockets[1].sent, []);
  client.close();
});

test("session deletion close code requests a fresh app session without reconnecting", async () => {
  const sockets = [];
  let unavailable = 0;
  const client = new AppEventClient(
    {
      sessionId: "10000000-0000-4000-8000-000000000001",
      sessionToken: "A".repeat(43),
    },
    {
      telemetry: new ContentFreeTelemetry(),
      onEvent() {},
      onState() {},
      onError() {},
      onSessionUnavailable() {
        unavailable += 1;
      },
      retryDelayMs: 1,
      maxReconnectAttempts: 2,
      webSocketFactory() {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    },
  );

  client.connect();
  sockets[0].open();
  sockets[0].close(4404);
  await new Promise((resolve) => setTimeout(resolve, 10));

  assert.equal(unavailable, 1);
  assert.equal(sockets.length, 1);
});

test("microphone denial is actionable and does not open signaling", async () => {
  const errors = [];
  let socketCreated = false;
  const audio = new FakeTarget();
  audio.pause = () => {};
  audio.srcObject = null;
  const client = new AzureVoiceLiveClient({
    sessionId: "10000000-0000-4000-8000-000000000001",
    sessionToken: "A".repeat(43),
    audio,
    telemetry: new ContentFreeTelemetry(),
    onState() {},
    onSpeechStarted() {
      return "40000000-0000-4000-8000-000000000001";
    },
    onFinalTranscript() {},
    onVoiceStarted() {},
    onAcknowledgment() {},
    onCompleted() {},
    onInterrupted() {},
    onError(error) {
      errors.push(error);
    },
    mediaDevices: {
      async getUserMedia() {
        throw new DOMException("denied", "NotAllowedError");
      },
    },
    webSocketFactory() {
      socketCreated = true;
      return new FakeSocket();
    },
  });
  await client.connect();
  assert.equal(socketCreated, false);
  assert.deepEqual(errors, [
    {
      category: "microphone",
      message: "Microphone access was denied. Allow access or use typed input.",
      retryable: true,
    },
  ]);
});

test("broker errors emitted with the SDP answer fail once with a sanitized category", async () => {
  const socket = new FakeSocket();
  const channel = new FakeSocket();
  channel.readyState = "open";
  class FakePeer extends FakeTarget {
    iceGatheringState = "complete";
    connectionState = "connected";
    localDescription = null;

    addTrack() {}
    createDataChannel() { return channel; }
    async createOffer() { return { type: "offer", sdp: "synthetic-offer" }; }
    async setLocalDescription(value) { this.localDescription = value; }
    async setRemoteDescription() {}
    close() {}
  }
  const audio = new FakeTarget();
  audio.paused = true;
  audio.srcObject = null;
  audio.pause = () => {};
  audio.play = async () => {};
  const errors = [];
  const client = new AzureVoiceLiveClient({
    sessionId: "10000000-0000-4000-8000-000000000001",
    sessionToken: "A".repeat(43),
    audio,
    telemetry: new ContentFreeTelemetry(),
    onState() {},
    onSpeechStarted() {
      return "40000000-0000-4000-8000-000000000001";
    },
    onFinalTranscript() {},
    onVoiceStarted() {},
    onAcknowledgment() {},
    onCompleted() {},
    onInterrupted() {},
    onError(error) { errors.push(error); },
    peerFactory: () => new FakePeer(),
    mediaDevices: {
      async getUserMedia() {
        return { getTracks: () => [{ stop() {} }] };
      },
    },
    webSocketFactory() {
      queueMicrotask(() => socket.open());
      socket.send = (value) => {
        socket.sent.push(value);
        queueMicrotask(() => {
          socket.emit("message", {
            data: JSON.stringify({
              type: "voice.session.answer",
              sdpAnswer: "synthetic-answer",
            }),
          });
          socket.emit("message", {
            data: JSON.stringify({
              type: "voice.session.error",
              code: "provider_session_failed",
            }),
          });
        });
      };
      return socket;
    },
  });

  await client.connect();

  assert.deepEqual(errors, [
    {
      category: "voice_live",
      message: "Voice Live reported a session error. Stop the session and retry.",
      retryable: true,
    },
  ]);
});

test("barge-in stops playback and cancels only the voice response", async () => {
  const channel = new FakeSocket();
  channel.readyState = "open";
  const socket = new FakeSocket();
  const track = { stopped: false, stop() { this.stopped = true; } };
  class FakePeer extends FakeTarget {
    iceGatheringState = "complete";
    connectionState = "connected";
    localDescription = null;

    addTrack() {}
    createDataChannel() { return channel; }
    async createOffer() { return { type: "offer", sdp: "synthetic-offer" }; }
    async setLocalDescription(value) { this.localDescription = value; }
    async setRemoteDescription() {}
    close() {}
  }
  const audio = new FakeTarget();
  audio.paused = true;
  audio.playCalls = 0;
  audio.src = "";
  audio.srcObject = null;
  audio.pause = () => { audio.paused = true; };
  audio.play = async () => {
    audio.playCalls += 1;
    audio.paused = false;
  };
  const interruptions = [];
  const transcripts = [];
  const voiceStarts = [];
  const acknowledgments = [];
  const completions = [];
  const errors = [];
  let voiceTurn = 0;
  const telemetry = new ContentFreeTelemetry();
  const peer = new FakePeer();
  const client = new AzureVoiceLiveClient({
    sessionId: "10000000-0000-4000-8000-000000000001",
    sessionToken: "A".repeat(43),
    audio,
    telemetry,
    onState() {},
    onSpeechStarted() {
      voiceTurn += 1;
      return `40000000-0000-4000-8000-${String(voiceTurn).padStart(12, "0")}`;
    },
    onFinalTranscript(value, turnId) { transcripts.push({ value, turnId }); },
    onVoiceStarted(turnId) { voiceStarts.push(turnId); },
    onAcknowledgment(value, turnId) {
      acknowledgments.push({ value, turnId });
    },
    onCompleted(turnId) { completions.push(turnId); },
    onInterrupted(value) { interruptions.push(value); },
    onError(error) { errors.push(error); },
    peerFactory: () => peer,
    mediaRecorderFactory: () => new FakeMediaRecorder(),
    createObjectURL: () => "blob:synthetic-audio",
    revokeObjectURL() {},
    mediaDevices: {
      async getUserMedia() {
        return { getTracks: () => [track] };
      },
    },
    webSocketFactory() {
      queueMicrotask(() => socket.open());
      socket.send = (value) => {
        socket.sent.push(value);
        queueMicrotask(() =>
          socket.emit("message", {
            data: JSON.stringify({
              type: "voice.session.answer",
              sdpAnswer: "synthetic-answer",
            }),
          }),
        );
      };
      return socket;
    },
  });
  await client.connect();
  peer.emit("track", {
    streams: [{ getTracks: () => [] }],
  });
  channel.emit("message", {
    data: JSON.stringify({ type: "input_audio_buffer.speech_started" }),
  });
  channel.emit("message", {
    data: JSON.stringify({ type: "input_audio_buffer.speech_stopped" }),
  });
  channel.emit("message", {
    data: JSON.stringify({ type: "response.created" }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "response.audio_transcript.done",
      transcript: "Understood. I've identified the strongest opportunity.",
    }),
  });
  assert.equal(audio.paused, true);
  assert.equal(audio.playCalls, 0);
  assert.deepEqual(channel.sent, []);
  channel.emit("message", {
    data: JSON.stringify({
      type: "response.audio_transcript.done",
      transcript:
        "Understood. I'll review the project context and identify the strongest expansion opportunity.",
    }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "synthetic-item-1",
      content_index: 0,
      transcript: "Synthetic final transcript",
    }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "synthetic-item-1",
      content_index: 0,
      transcript: "Synthetic final transcript",
    }),
  });
  channel.emit("message", {
    data: JSON.stringify({ type: "input_audio_buffer.speech_started" }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "response.audio_transcript.done",
      transcript: "A cancelled response must not update app state.",
    }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "synthetic-item-2",
      content_index: 0,
      transcript: "Synthetic follow-up transcript",
    }),
  });
  channel.emit("message", {
    data: JSON.stringify({ type: "input_audio_buffer.speech_stopped" }),
  });
  channel.emit("message", {
    data: JSON.stringify({ type: "response.created" }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "response.audio_transcript.done",
      transcript:
        "Got it. I'll focus on the operational pain and strengthen the supporting evidence next.",
    }),
  });
  channel.emit("message", {
    data: JSON.stringify({
      type: "response.done",
      response: {
        status: "completed",
        status_details: null,
        usage: { output_tokens: 72 },
      },
    }),
  });
  assert.equal(audio.playCalls, 1);
  audio.emit("playing");
  audio.emit("ended");

  assert.deepEqual(transcripts, [
    {
      value: "Synthetic final transcript",
      turnId: "40000000-0000-4000-8000-000000000001",
    },
    {
      value: "Synthetic follow-up transcript",
      turnId: "40000000-0000-4000-8000-000000000002",
    },
  ]);
  assert.deepEqual(interruptions, ["barge_in"]);
  assert.deepEqual(voiceStarts, [
    "40000000-0000-4000-8000-000000000002",
  ]);
  assert.deepEqual(acknowledgments, [
    {
      value:
        "Got it. I'll focus on the operational pain and strengthen the supporting evidence next.",
      turnId: "40000000-0000-4000-8000-000000000002",
    },
  ]);
  assert.deepEqual(completions, [
    "40000000-0000-4000-8000-000000000002",
  ]);
  client.interrupt("user_stop");
  assert.deepEqual(interruptions, ["barge_in"]);
  assert.deepEqual(errors, [
    {
      category: "voice_live",
      message:
        "The generated acknowledgment exceeded its non-authoritative scope and was not played or added to app state.",
      retryable: false,
    },
  ]);
  assert.deepEqual(channel.sent.map(JSON.parse), [{ type: "response.cancel" }]);
  assert.deepEqual(
    telemetry
      .snapshot()
      .filter(({ name }) =>
        [
          "voice_input_speech_started",
          "voice_response_cancel_requested",
          "voice_response_finished",
        ].includes(name),
      )
      .map(({ at, ...observation }) => observation),
    [
      {
        name: "voice_input_speech_started",
        turnId: undefined,
        outcome: "idle",
      },
      {
        name: "voice_input_speech_started",
        turnId: "40000000-0000-4000-8000-000000000001",
        outcome: "during_response",
      },
      {
        name: "voice_response_cancel_requested",
        turnId: "40000000-0000-4000-8000-000000000001",
        outcome: "barge_in",
      },
      {
        name: "voice_response_finished",
        turnId: "40000000-0000-4000-8000-000000000002",
        outcome: "completed",
        outputTokens: 72,
        transcriptCharacters:
          "Got it. I'll focus on the operational pain and strengthen the supporting evidence next."
            .length,
      },
    ],
  );
  assert.deepEqual(
    telemetry
      .diagnosticSnapshot()
      .filter(({ name }) => name === "voice_response_finished"),
    [
      {
        name: "voice_response_finished",
        outcome: "completed",
        outputTokens: 72,
        transcriptCharacters:
          "Got it. I'll focus on the operational pain and strengthen the supporting evidence next."
            .length,
        at: telemetry
          .snapshot()
          .find(({ name }) => name === "voice_response_finished").at,
      },
    ],
  );
  assert.equal(track.stopped, false);
  client.stop();
  assert.equal(track.stopped, true);
});

test("stop during microphone acquisition prevents resource resurrection", async () => {
  let resolveMedia;
  const mediaPromise = new Promise((resolve) => {
    resolveMedia = resolve;
  });
  const track = {
    stopped: false,
    stop() {
      this.stopped = true;
    },
  };
  const states = [];
  let peerCreated = false;
  let socketCreated = false;
  const audio = new FakeTarget();
  audio.pause = () => {};
  audio.srcObject = null;
  const client = new AzureVoiceLiveClient({
    sessionId: "10000000-0000-4000-8000-000000000001",
    sessionToken: "A".repeat(43),
    audio,
    telemetry: new ContentFreeTelemetry(),
    onState(value) { states.push(value); },
    onSpeechStarted() {
      return "40000000-0000-4000-8000-000000000001";
    },
    onFinalTranscript() {},
    onVoiceStarted() {},
    onAcknowledgment() {},
    onCompleted() {},
    onInterrupted() {},
    onError(error) { throw new Error(error.message); },
    peerFactory() {
      peerCreated = true;
      throw new Error("A stopped connect must not create a peer.");
    },
    mediaDevices: {
      getUserMedia() {
        return mediaPromise;
      },
    },
    webSocketFactory() {
      socketCreated = true;
      return new FakeSocket();
    },
  });

  const connecting = client.connect();
  await Promise.resolve();
  client.stop();
  resolveMedia({ getTracks: () => [track] });
  await connecting;

  assert.equal(track.stopped, true);
  assert.equal(peerCreated, false);
  assert.equal(socketCreated, false);
  assert.deepEqual(states, ["connecting", "stopped"]);
});

test("stop during an awaited peer boundary closes owned resources once", async () => {
  let resolveOffer;
  const offerPromise = new Promise((resolve) => {
    resolveOffer = resolve;
  });
  const track = {
    stopCount: 0,
    stop() {
      this.stopCount += 1;
    },
  };
  const channel = new FakeSocket();
  channel.readyState = "open";
  class DeferredPeer extends FakeTarget {
    iceGatheringState = "complete";
    connectionState = "new";
    localDescription = null;
    closeCount = 0;

    addTrack() {}
    createDataChannel() { return channel; }
    createOffer() { return offerPromise; }
    async setLocalDescription(value) { this.localDescription = value; }
    async setRemoteDescription() {}
    close() { this.closeCount += 1; }
  }
  const peer = new DeferredPeer();
  const audio = new FakeTarget();
  audio.pause = () => {};
  audio.srcObject = null;
  let socketCreated = false;
  const client = new AzureVoiceLiveClient({
    sessionId: "10000000-0000-4000-8000-000000000001",
    sessionToken: "A".repeat(43),
    audio,
    telemetry: new ContentFreeTelemetry(),
    onState() {},
    onSpeechStarted() {
      return "40000000-0000-4000-8000-000000000001";
    },
    onFinalTranscript() {},
    onVoiceStarted() {},
    onAcknowledgment() {},
    onCompleted() {},
    onInterrupted() {},
    onError(error) { throw new Error(error.message); },
    peerFactory: () => peer,
    mediaDevices: {
      async getUserMedia() {
        return { getTracks: () => [track] };
      },
    },
    webSocketFactory() {
      socketCreated = true;
      return new FakeSocket();
    },
  });

  const connecting = client.connect();
  await Promise.resolve();
  await Promise.resolve();
  client.stop();
  resolveOffer({ type: "offer", sdp: "synthetic-offer" });
  await connecting;

  assert.equal(socketCreated, false);
  assert.equal(track.stopCount, 1);
  assert.equal(peer.closeCount, 1);
});
