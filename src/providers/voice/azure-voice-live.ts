import { isConstrainedAcknowledgment } from "../../lib/acknowledgment.ts";
import type { ContentFreeTelemetry } from "../../lib/telemetry.ts";
import type {
  VoiceClient,
  VoiceClientError,
  VoiceClientErrorCategory,
  VoiceConnectionState,
} from "./types.ts";

export interface AzureVoiceLiveClientOptions {
  readonly sessionId: string;
  readonly sessionToken: string;
  readonly audio: HTMLAudioElement;
  readonly telemetry: ContentFreeTelemetry;
  readonly onState: (state: VoiceConnectionState) => void;
  readonly onSpeechStarted: () => string;
  readonly onFinalTranscript: (transcript: string, turnId: string) => void;
  readonly onVoiceStarted: (turnId: string) => void;
  readonly onAcknowledgment: (
    acknowledgment: string,
    turnId: string,
  ) => void;
  readonly onCompleted: (turnId: string) => void;
  readonly onInterrupted: (
    reason: "barge_in" | "user_stop",
    turnId: string,
  ) => void;
  readonly onError: (error: VoiceClientError) => void;
  readonly peerFactory?: () => RTCPeerConnection;
  readonly webSocketFactory?: (
    url: string,
    protocols: readonly string[],
  ) => WebSocket;
  readonly mediaDevices?: Pick<MediaDevices, "getUserMedia">;
  readonly mediaRecorderFactory?: (stream: MediaStream) => MediaRecorder;
  readonly createObjectURL?: (blob: Blob) => string;
  readonly revokeObjectURL?: (url: string) => void;
}

export class AzureVoiceLiveClient implements VoiceClient {
  readonly #options: AzureVoiceLiveClientOptions;
  #peer: RTCPeerConnection | null = null;
  #socket: WebSocket | null = null;
  #dataChannel: RTCDataChannel | null = null;
  #stream: MediaStream | null = null;
  #remoteStream: MediaStream | null = null;
  #responseRecorder: MediaRecorder | null = null;
  #responseChunks: Blob[] = [];
  #responseGeneration = 0;
  #providerResponseActive = false;
  #responseDone = false;
  #acceptedAcknowledgment: string | undefined;
  #acknowledgmentRejected = false;
  #acknowledgmentDispatched = false;
  #playbackObjectUrl: string | null = null;
  #firstAudio = false;
  #speechEndedAt: number | null = null;
  #currentTurnId: string | undefined;
  readonly #completedTranscriptItems = new Set<string>();
  #stopped = false;
  #failureReported = false;
  #generation = 0;
  #connectingGeneration: number | null = null;
  #voiceStarted = false;
  #voiceCompleted = false;
  #responseActive = false;
  #responseTranscriptCharacters: number | undefined;

  constructor(options: AzureVoiceLiveClientOptions) {
    this.#options = options;
  }

  async connect(): Promise<void> {
    if (this.#peer !== null || this.#connectingGeneration !== null) {
      return;
    }
    const generation = ++this.#generation;
    this.#connectingGeneration = generation;
    this.#stopped = false;
    this.#failureReported = false;
    this.#options.onState("connecting");
    this.#options.telemetry.record("voice_connection_started");
    const media =
      this.#options.mediaDevices ?? window.navigator.mediaDevices;
    let stream: MediaStream | null = null;
    let peer: RTCPeerConnection | null = null;
    let socket: WebSocket | null = null;
    try {
      stream = await media.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (!this.#isActiveGeneration(generation)) {
        stopTracks(stream);
        if (this.#connectingGeneration === generation) {
          this.#connectingGeneration = null;
        }
        return;
      }
    } catch (error: unknown) {
      if (!this.#isActiveGeneration(generation)) {
        if (this.#connectingGeneration === generation) {
          this.#connectingGeneration = null;
        }
        return;
      }
      this.#fail(
        "microphone",
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "Microphone access was denied. Allow access or use typed input."
          : "The microphone is unavailable. Check the device or use typed input.",
        true,
      );
      if (this.#connectingGeneration === generation) {
        this.#connectingGeneration = null;
      }
      return;
    }

    try {
      peer = this.#options.peerFactory?.() ?? new RTCPeerConnection();
      const activePeer = peer;
      if (!this.#isActiveGeneration(generation)) {
        stopTracks(stream);
        activePeer.close();
        return;
      }
      this.#stream = stream;
      this.#peer = activePeer;
      for (const track of stream.getTracks()) {
        activePeer.addTrack(track, stream);
      }
      activePeer.addEventListener("track", (event) => {
        if (!this.#ownsConnection(generation, activePeer)) {
          return;
        }
        this.#remoteStream = event.streams[0] ?? null;
        if (this.#responseActive && this.#responseRecorder === null) {
          this.#startResponseRecorder(this.#responseGeneration);
        }
      });
      this.#options.audio.addEventListener("playing", this.#onPlaying);
      this.#options.audio.addEventListener("ended", this.#onPlaybackEnded);
      activePeer.addEventListener("connectionstatechange", () => {
        if (!this.#ownsConnection(generation, activePeer)) {
          return;
        }
        if (activePeer.connectionState === "connected") {
          this.#options.onState("listening");
          this.#options.telemetry.record("voice_connection_ready");
        } else if (activePeer.connectionState === "failed") {
          this.#fail(
            "voice_transport",
            "The realtime audio connection failed. Stop it and retry.",
            true,
          );
        }
      });
      const dataChannel = activePeer.createDataChannel("voice-live-events");
      this.#dataChannel = dataChannel;
      dataChannel.addEventListener("message", (event) => {
        if (this.#ownsConnection(generation, activePeer)) {
          this.#handleDataEvent(event.data);
        }
      });

      const offer = await activePeer.createOffer();
      if (!this.#ownsConnection(generation, activePeer)) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      await activePeer.setLocalDescription(offer);
      if (!this.#ownsConnection(generation, activePeer)) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      await waitForIce(activePeer);
      if (!this.#ownsConnection(generation, activePeer)) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      if (activePeer.localDescription?.sdp === undefined) {
        throw new Error("Local SDP was unavailable.");
      }
      const url = `${webSocketOrigin()}/api/voice/session/${this.#options.sessionId}`;
      const protocols = [
        "dcr-voice.v1",
        `dcr-session.${this.#options.sessionToken}`,
      ] as const;
      socket =
        this.#options.webSocketFactory?.(url, protocols) ??
        new WebSocket(url, [...protocols]);
      if (!this.#ownsConnection(generation, activePeer)) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      this.#socket = socket;
      await waitForOpen(socket);
      if (!this.#ownsConnection(generation, activePeer) || this.#socket !== socket) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      socket.addEventListener("message", this.#onBrokerMessage);
      socket.send(
        JSON.stringify({
          type: "voice.session.start",
          sdpOffer: activePeer.localDescription.sdp,
        }),
      );
      const answer = await waitForAnswer(socket);
      if (!this.#ownsConnection(generation, activePeer) || this.#socket !== socket) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      await activePeer.setRemoteDescription({ type: "answer", sdp: answer });
      if (!this.#ownsConnection(generation, activePeer) || this.#socket !== socket) {
        this.#disposeOwned(stream, activePeer, socket);
        return;
      }
      socket.addEventListener("close", this.#onBrokerClose);
    } catch (error: unknown) {
      if (!this.#isActiveGeneration(generation)) {
        this.#disposeOwned(stream, peer, socket);
        return;
      }
      const category =
        error instanceof VoiceSessionError && error.code.includes("auth")
          ? "authentication"
          : "voice_live";
      this.#fail(
        category,
        category === "authentication"
          ? "Voice authentication failed. Verify your keyless access, then retry."
          : "Voice Live could not connect. Check configuration and retry, or use typed input.",
        true,
      );
    } finally {
      if (this.#connectingGeneration === generation) {
        this.#connectingGeneration = null;
      }
    }
  }

  setCurrentTurn(turnId: string): void {
    this.#currentTurnId = turnId;
  }

  interrupt(reason: "barge_in" | "user_stop"): void {
    if (this.#stopped) {
      return;
    }
    if (this.#responseActive) {
      const interruptedTurnId = this.#currentTurnId;
      if (
        this.#providerResponseActive &&
        this.#dataChannel?.readyState === "open"
      ) {
        this.#dataChannel.send(JSON.stringify({ type: "response.cancel" }));
        this.#options.telemetry.record("voice_response_cancel_requested", {
          turnId: interruptedTurnId,
          outcome: reason,
        });
      }
      this.#options.telemetry.record("playback_stopped", {
        turnId: interruptedTurnId,
        outcome: reason,
      });
      this.#discardBufferedResponse();
      if (interruptedTurnId !== undefined) {
        this.#options.onInterrupted(reason, interruptedTurnId);
      }
      this.#responseActive = false;
      this.#providerResponseActive = false;
      this.#responseDone = false;
      this.#responseTranscriptCharacters = undefined;
      this.#voiceCompleted = true;
    } else {
      this.#options.audio.pause();
    }
    this.#options.onState("listening");
  }

  stop(): void {
    if (this.#stopped) {
      return;
    }
    this.#stopped = true;
    this.#generation += 1;
    this.#connectingGeneration = null;
    this.#dispose();
    this.#options.onState("stopped");
  }

  #dispose(): void {
    this.#discardBufferedResponse();
    this.#options.audio.srcObject = null;
    this.#options.audio.removeEventListener("playing", this.#onPlaying);
    this.#options.audio.removeEventListener("ended", this.#onPlaybackEnded);
    for (const track of this.#stream?.getTracks() ?? []) {
      track.stop();
    }
    this.#stream = null;
    this.#remoteStream = null;
    this.#peer?.close();
    this.#peer = null;
    this.#dataChannel = null;
    this.#socket?.removeEventListener("message", this.#onBrokerMessage);
    this.#socket?.removeEventListener("close", this.#onBrokerClose);
    this.#socket?.close(1000, "Voice stopped");
    this.#socket = null;
    this.#voiceStarted = false;
    this.#voiceCompleted = false;
    this.#responseActive = false;
    this.#providerResponseActive = false;
    this.#responseDone = false;
    this.#currentTurnId = undefined;
    this.#completedTranscriptItems.clear();
    this.#firstAudio = false;
    this.#speechEndedAt = null;
  }

  #disposeOwned(
    stream: MediaStream | null,
    peer: RTCPeerConnection | null,
    socket: WebSocket | null,
  ): void {
    if (this.#stream === stream) {
      stopTracks(stream);
      this.#stream = null;
    }
    if (this.#peer === peer) {
      peer?.close();
      this.#peer = null;
      this.#dataChannel = null;
    }
    if (this.#socket === socket) {
      socket?.removeEventListener("message", this.#onBrokerMessage);
      socket?.removeEventListener("close", this.#onBrokerClose);
      socket?.close(1000, "Superseded voice connection");
      this.#socket = null;
    }
  }

  #isActiveGeneration(generation: number): boolean {
    return !this.#stopped && this.#generation === generation;
  }

  #ownsConnection(
    generation: number,
    peer: RTCPeerConnection,
  ): boolean {
    return this.#isActiveGeneration(generation) && this.#peer === peer;
  }

  readonly #onPlaying = () => {
    if (this.#stopped || this.#peer === null) {
      return;
    }
    this.#options.onState("speaking");
    if (!this.#voiceStarted && this.#currentTurnId !== undefined) {
      this.#voiceStarted = true;
      this.#options.onVoiceStarted(this.#currentTurnId);
    }
    if (
      !this.#acknowledgmentDispatched &&
      this.#acceptedAcknowledgment !== undefined &&
      this.#currentTurnId !== undefined
    ) {
      this.#acknowledgmentDispatched = true;
      this.#options.onAcknowledgment(
        this.#acceptedAcknowledgment,
        this.#currentTurnId,
      );
    }
    if (!this.#firstAudio) {
      this.#firstAudio = true;
      this.#options.telemetry.record("first_audio", {
        turnId: this.#currentTurnId,
        durationMs:
          this.#speechEndedAt === null
            ? undefined
            : Math.max(0, Math.round(performance.now() - this.#speechEndedAt)),
      });
    }
  };

  readonly #onPlaybackEnded = () => {
    if (
      this.#stopped ||
      !this.#responseActive ||
      this.#voiceCompleted ||
      this.#currentTurnId === undefined
    ) {
      return;
    }
    const completedTurnId = this.#currentTurnId;
    this.#voiceCompleted = true;
    this.#responseActive = false;
    this.#providerResponseActive = false;
    this.#cleanupPlayback();
    this.#options.onCompleted(completedTurnId);
    this.#options.onState("listening");
  };

  #handleDataEvent(raw: unknown): void {
    if (this.#stopped || this.#peer === null) {
      return;
    }
    if (typeof raw !== "string" || raw.length > 65_536) {
      this.#fail(
        "voice_live",
        "Voice Live returned an invalid event. Stop the session and retry.",
        true,
      );
      return;
    }
    let event: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("Invalid event.");
      }
      event = parsed as Record<string, unknown>;
    } catch {
      this.#fail(
        "voice_live",
        "Voice Live returned an invalid event. Stop the session and retry.",
        true,
      );
      return;
    }

    switch (event.type) {
      case "input_audio_buffer.speech_started":
        this.#options.telemetry.record("voice_input_speech_started", {
          turnId: this.#currentTurnId,
          outcome: this.#responseActive ? "during_response" : "idle",
        });
        if (this.#responseActive) {
          this.interrupt("barge_in");
        }
        this.#currentTurnId = this.#options.onSpeechStarted();
        break;
      case "input_audio_buffer.speech_stopped":
        this.#speechEndedAt = performance.now();
        this.#options.telemetry.record("speech_ended", {
          turnId: this.#currentTurnId,
        });
        break;
      case "response.created":
        this.#discardBufferedResponse();
        this.#firstAudio = false;
        this.#voiceStarted = false;
        this.#voiceCompleted = false;
        this.#responseActive = true;
        this.#providerResponseActive = true;
        this.#responseDone = false;
        this.#acceptedAcknowledgment = undefined;
        this.#acknowledgmentRejected = false;
        this.#acknowledgmentDispatched = false;
        this.#responseTranscriptCharacters = undefined;
        this.#startResponseRecorder(this.#responseGeneration);
        break;
      case "conversation.item.input_audio_transcription.completed":
        if (
          typeof event.item_id !== "string" ||
          event.item_id.length === 0 ||
          event.item_id.length > 256 ||
          !Number.isSafeInteger(event.content_index) ||
          typeof event.transcript !== "string" ||
          event.transcript.trim().length === 0 ||
          event.transcript.trim().length > 4_000
        ) {
          this.#fail(
            "voice_live",
            "Voice Live returned an invalid final transcript event. Stop the session and retry.",
            true,
          );
          break;
        }
        if (this.#completedTranscriptItems.has(event.item_id)) {
          break;
        }
        this.#completedTranscriptItems.add(event.item_id);
        this.#currentTurnId ??= this.#options.onSpeechStarted();
        this.#options.onFinalTranscript(
          event.transcript.trim(),
          this.#currentTurnId,
        );
        break;
      case "response.audio_transcript.done":
        if (
          !this.#responseActive ||
          this.#voiceCompleted ||
          this.#acknowledgmentRejected ||
          this.#acceptedAcknowledgment !== undefined
        ) {
          break;
        }
        if (typeof event.transcript === "string") {
          this.#responseTranscriptCharacters = event.transcript.trim().length;
        }
        if (
          typeof event.transcript === "string" &&
          isConstrainedAcknowledgment(event.transcript) &&
          this.#currentTurnId !== undefined
        ) {
          this.#acceptedAcknowledgment = event.transcript.trim();
        } else {
          this.#acknowledgmentRejected = true;
          this.#options.telemetry.record("voice_acknowledgment_rejected", {
            turnId: this.#currentTurnId,
          });
          this.#options.onError({
            category: "voice_live",
            message:
              "The generated acknowledgment exceeded its non-authoritative scope and was not played or added to app state.",
            retryable: false,
          });
        }
        break;
      case "response.done":
        {
          const diagnostics = responseDoneDiagnostics(event);
          this.#options.telemetry.record("voice_response_finished", {
            turnId: this.#currentTurnId,
            outcome: diagnostics.outcome,
            outputTokens: diagnostics.outputTokens,
            transcriptCharacters: this.#responseTranscriptCharacters,
          });
        }
        this.#providerResponseActive = false;
        this.#responseDone = true;
        if (
          this.#acknowledgmentRejected ||
          this.#acceptedAcknowledgment === undefined
        ) {
          if (!this.#acknowledgmentRejected) {
            this.#acknowledgmentRejected = true;
            this.#options.telemetry.record("voice_acknowledgment_rejected", {
              turnId: this.#currentTurnId,
            });
            this.#options.onError({
              category: "voice_live",
              message:
                "Voice Live completed without a valid non-authoritative acknowledgment, so no audio was played.",
              retryable: true,
            });
          }
          this.#discardResponseRecorder();
          this.#responseActive = false;
          this.#voiceCompleted = true;
          this.#options.onState("listening");
          break;
        }
        this.#stopRecorderForPlayback();
        break;
    }
  }

  #startResponseRecorder(generation: number): void {
    if (
      generation !== this.#responseGeneration ||
      this.#remoteStream === null ||
      this.#responseRecorder !== null ||
      !this.#responseActive
    ) {
      return;
    }
    try {
      const recorder =
        this.#options.mediaRecorderFactory?.(this.#remoteStream) ??
        new MediaRecorder(this.#remoteStream);
      this.#responseRecorder = recorder;
      recorder.addEventListener("dataavailable", (event) => {
        if (
          generation === this.#responseGeneration &&
          !this.#acknowledgmentRejected &&
          event.data.size > 0
        ) {
          this.#responseChunks.push(event.data);
        }
      });
      recorder.addEventListener(
        "stop",
        () => {
          if (
            generation !== this.#responseGeneration ||
            this.#responseRecorder !== recorder
          ) {
            return;
          }
          this.#responseRecorder = null;
          this.#playBufferedResponse(generation, recorder.mimeType);
        },
        { once: true },
      );
      recorder.start();
    } catch {
      this.#fail(
        "voice_transport",
        "The browser could not buffer Voice Live audio for validation. Stop the session and retry.",
        true,
      );
    }
  }

  #stopRecorderForPlayback(): void {
    const recorder = this.#responseRecorder;
    if (recorder === null) {
      this.#rejectUnavailablePlayback();
      return;
    }
    if (recorder.state === "inactive") {
      this.#responseRecorder = null;
      this.#playBufferedResponse(this.#responseGeneration, recorder.mimeType);
      return;
    }
    recorder.stop();
  }

  #playBufferedResponse(generation: number, mimeType: string): void {
    if (
      generation !== this.#responseGeneration ||
      this.#stopped ||
      !this.#responseActive ||
      !this.#responseDone ||
      this.#acceptedAcknowledgment === undefined ||
      this.#acknowledgmentRejected
    ) {
      this.#responseChunks = [];
      return;
    }
    const chunks = this.#responseChunks;
    this.#responseChunks = [];
    const blob = new Blob(chunks, {
      type: chunks.find((chunk) => chunk.type)?.type || mimeType,
    });
    if (blob.size === 0) {
      this.#rejectUnavailablePlayback();
      return;
    }
    this.#cleanupPlayback();
    const createObjectURL =
      this.#options.createObjectURL ?? URL.createObjectURL.bind(URL);
    try {
      this.#playbackObjectUrl = createObjectURL(blob);
      this.#options.audio.srcObject = null;
      this.#options.audio.src = this.#playbackObjectUrl;
      void this.#options.audio.play().catch(() => {
        if (generation !== this.#responseGeneration || this.#stopped) {
          return;
        }
        this.#cleanupPlayback();
        this.#responseActive = false;
        this.#voiceCompleted = true;
        this.#options.onState("listening");
        this.#options.onError({
          category: "voice_transport",
          message:
            "The validated Voice Live acknowledgment could not be played. Check browser audio permissions and retry.",
          retryable: true,
        });
      });
    } catch {
      this.#rejectUnavailablePlayback();
    }
  }

  #rejectUnavailablePlayback(): void {
    this.#discardResponseRecorder();
    this.#responseActive = false;
    this.#voiceCompleted = true;
    this.#options.onState("listening");
    this.#options.onError({
      category: "voice_transport",
      message:
        "Voice Live returned no buffered audio that could be validated and played. Retry the turn.",
      retryable: true,
    });
  }

  #discardResponseRecorder(): void {
    const recorder = this.#responseRecorder;
    this.#responseRecorder = null;
    this.#responseChunks = [];
    if (recorder !== null && recorder.state !== "inactive") {
      recorder.stop();
    }
  }

  #discardBufferedResponse(): void {
    this.#responseGeneration += 1;
    this.#discardResponseRecorder();
    this.#acceptedAcknowledgment = undefined;
    this.#acknowledgmentRejected = false;
    this.#acknowledgmentDispatched = false;
    this.#responseDone = false;
    this.#cleanupPlayback();
  }

  #cleanupPlayback(): void {
    this.#options.audio.pause();
    this.#options.audio.src = "";
    if (this.#playbackObjectUrl !== null) {
      const revokeObjectURL =
        this.#options.revokeObjectURL ?? URL.revokeObjectURL.bind(URL);
      revokeObjectURL(this.#playbackObjectUrl);
      this.#playbackObjectUrl = null;
    }
  }

  readonly #onBrokerMessage = (message: MessageEvent<unknown>) => {
    if (
      this.#stopped ||
      message.currentTarget != null &&
        message.currentTarget !== this.#socket
    ) {
      return;
    }
    if (typeof message.data !== "string") {
      this.#fail(
        "voice_live",
        "The voice broker returned an invalid event. Stop the session and retry.",
        true,
      );
      return;
    }
    try {
      const value: unknown = JSON.parse(message.data);
      if (
        typeof value === "object" &&
        value !== null &&
        "type" in value &&
        value.type === "voice.session.error" &&
        "code" in value &&
        typeof value.code === "string"
      ) {
        const category = value.code.includes("auth")
          ? "authentication"
          : "voice_live";
        this.#fail(
          category,
          category === "authentication"
            ? "Voice authentication failed. Verify your keyless access, then retry."
            : "Voice Live reported a session error. Stop the session and retry.",
          true,
        );
      }
    } catch {
      this.#fail(
        "voice_live",
        "The voice broker returned an invalid event. Stop the session and retry.",
        true,
      );
    }
  };

  readonly #onBrokerClose = (event: CloseEvent) => {
    if (
      !this.#stopped &&
      this.#peer !== null &&
      (event.currentTarget == null || event.currentTarget === this.#socket)
    ) {
      this.#fail(
        "voice_transport",
        "The voice control connection closed. Stop the session and retry.",
        true,
      );
    }
  };

  #fail(
    category: VoiceClientErrorCategory,
    message: string,
    retryable: boolean,
  ): void {
    if (this.#failureReported || this.#stopped) {
      return;
    }
    this.#failureReported = true;
    this.#options.telemetry.record("voice_connection_failed", {
      outcome: category,
    });
    this.#dispose();
    this.#options.onState("failed");
    this.#options.onError({ category, message, retryable });
  }
}

function responseDoneDiagnostics(event: Record<string, unknown>): {
  readonly outcome:
    | "completed"
    | "output_limit"
    | "cancelled"
    | "incomplete"
    | "failed"
    | "unknown";
  readonly outputTokens?: number;
} {
  const response = objectRecord(event.response);
  const usage = objectRecord(response?.usage);
  const outputTokens =
    typeof usage?.output_tokens === "number" &&
    Number.isSafeInteger(usage.output_tokens) &&
    usage.output_tokens >= 0
      ? usage.output_tokens
      : undefined;
  const status = typeof response?.status === "string" ? response.status : "";
  const statusDetails = objectRecord(response?.status_details);
  const reason =
    typeof statusDetails?.reason === "string" ? statusDetails.reason : "";
  if (status === "completed") {
    return { outcome: "completed", outputTokens };
  }
  if (reason === "max_output_tokens") {
    return { outcome: "output_limit", outputTokens };
  }
  if (status === "cancelled" || status === "canceled") {
    return { outcome: "cancelled", outputTokens };
  }
  if (status === "incomplete") {
    return { outcome: "incomplete", outputTokens };
  }
  if (status === "failed") {
    return { outcome: "failed", outputTokens };
  }
  return { outcome: "unknown", outputTokens };
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

class VoiceSessionError extends Error {
  readonly code: string;

  constructor(code: string) {
    super("Voice session failed.");
    this.code = code;
  }
}

async function waitForIce(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === "complete") {
    return;
  }
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("ICE gathering timed out."));
    }, 5_000);
    const handler = () => {
      if (peer.iceGatheringState === "complete") {
        cleanup();
        resolve();
      }
    };
    const cleanup = () => {
      window.clearTimeout(timeout);
      peer.removeEventListener("icegatheringstatechange", handler);
    };
    peer.addEventListener("icegatheringstatechange", handler);
  });
}

async function waitForOpen(socket: WebSocket): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      window.clearTimeout(timeout);
      socket.removeEventListener("open", opened);
      socket.removeEventListener("error", failed);
      socket.removeEventListener("close", closed);
    };
    const opened = () => {
      cleanup();
      resolve();
    };
    const failed = () => {
      cleanup();
      reject(new Error("Voice broker failed."));
    };
    const closed = () => {
      cleanup();
      reject(new Error("Voice broker closed."));
    };
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error("Voice broker timed out."));
    }, 10_000);
    socket.addEventListener("open", opened);
    socket.addEventListener("error", failed);
    socket.addEventListener("close", closed);
  });
}

async function waitForAnswer(socket: WebSocket): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    const cleanup = () => {
      window.clearTimeout(timeout);
      socket.removeEventListener("message", received);
      socket.removeEventListener("close", closed);
    };
    const failed = (error: Error) => {
      cleanup();
      reject(error);
    };
    const received = (message: MessageEvent<unknown>) => {
      if (typeof message.data !== "string") {
        failed(new Error("Voice negotiation returned an invalid frame."));
        return;
      }
      try {
        const value: unknown = JSON.parse(message.data);
        if (
          typeof value === "object" &&
          value !== null &&
          "type" in value &&
          value.type === "voice.session.answer" &&
          "sdpAnswer" in value &&
          typeof value.sdpAnswer === "string"
        ) {
          cleanup();
          resolve(value.sdpAnswer);
        } else if (
          typeof value === "object" &&
          value !== null &&
          "type" in value &&
          value.type === "voice.session.error" &&
          "code" in value &&
          typeof value.code === "string"
        ) {
          failed(new VoiceSessionError(value.code));
        } else {
          failed(new Error("Voice negotiation returned an invalid response."));
        }
      } catch {
        failed(new Error("Voice negotiation returned invalid JSON."));
      }
    };
    const closed = () => failed(new Error("Voice negotiation closed."));
    const timeout = window.setTimeout(
      () => failed(new Error("Voice negotiation timed out.")),
      30_000,
    );
    socket.addEventListener("message", received);
    socket.addEventListener("close", closed);
  });
}

function webSocketOrigin(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}`;
}

function stopTracks(stream: MediaStream | null): void {
  for (const track of stream?.getTracks() ?? []) {
    track.stop();
  }
}
