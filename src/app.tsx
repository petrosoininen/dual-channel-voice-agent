import { useCallback, useEffect, useRef, useState } from "react";
import type {
  DocumentRevertCommand,
  TurnCancelCommand,
  TurnSubmitCommand,
  VoiceAcknowledgmentCommand,
  VoiceCompleteCommand,
  VoiceInterruptCommand,
  VoiceStartCommand,
} from "./contracts/app-commands.ts";
import type { AppEvent } from "./contracts/app-events.ts";
import { ErrorNotice, type WorkspaceError } from "./components/error-notice.tsx";
import { ModeBadge } from "./components/mode-badge.tsx";
import { TurnTimeline } from "./components/turn-timeline.tsx";
import { VoiceControls } from "./components/voice-controls.tsx";
import { WorkingDocument } from "./components/working-document.tsx";
import {
  AppEventClient,
  createAppSession,
  type AppSession,
} from "./lib/app-event-client.ts";
import { ContentFreeTelemetry } from "./lib/telemetry.ts";
import { createVoiceClient } from "./providers/voice/factory.ts";
import type {
  VoiceClient,
  VoiceConnectionState,
  VoiceProvider,
} from "./providers/voice/types.ts";
import {
  addLocalTurn,
  applyAppEvent,
  emptyConversationState,
  type ConversationState,
} from "./state/conversation-store.ts";

interface Capabilities {
  readonly agentProvider: "deterministic" | "foundry";
  readonly voiceProvider: VoiceProvider;
  readonly deepWorkAvailable: boolean;
  readonly voiceAvailable: boolean;
  readonly voiceTransport: "disabled" | "webrtc-public-preview";
  readonly voiceTransportPreview: boolean;
  readonly statePersistence: "process-memory-only";
}

type LoadState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly capabilities: Capabilities }
  | { readonly status: "failed" };

interface Bootstrap {
  readonly capabilities: Capabilities;
  readonly session: AppSession;
}

export function App() {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [conversation, setConversation] = useState<ConversationState>(
    emptyConversationState,
  );
  const conversationRef = useRef(conversation);
  const [session, setSession] = useState<AppSession | null>(null);
  const [appConnection, setAppConnection] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const [voiceState, setVoiceState] =
    useState<VoiceConnectionState>("idle");
  const [typedValue, setTypedValue] = useState("");
  const [error, setError] = useState<WorkspaceError | null>(null);
  const appClient = useRef<AppEventClient | null>(null);
  const voiceClient = useRef<VoiceClient | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const activeVoiceTurn = useRef<string | null>(null);
  const submittedVoiceTurns = useRef(new Set<string>());
  const pendingVoiceCommands = useRef(
    new Map<
      string,
      (
        | VoiceStartCommand
        | VoiceAcknowledgmentCommand
        | VoiceCompleteCommand
        | VoiceInterruptCommand
      )[]
    >(),
  );
  const initializationGeneration = useRef(0);
  const initializeRef = useRef<() => void>(() => undefined);
  const telemetry = useRef(new ContentFreeTelemetry()).current;

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }
    Reflect.set(
      window,
      "getDcrContentFreeTelemetry",
      () => telemetry.diagnosticSnapshot(),
    );
    return () => {
      Reflect.deleteProperty(window, "getDcrContentFreeTelemetry");
    };
  }, [telemetry]);

  const replaceConversation = useCallback((next: ConversationState) => {
    conversationRef.current = next;
    setConversation(next);
  }, []);

  const handleEvent = useCallback(
    (event: AppEvent) => {
      try {
        replaceConversation(applyAppEvent(conversationRef.current, event));
        if (event.type === "document.pending") {
          telemetry.record("document_pending", {
            sessionId: event.sessionId,
            turnId: event.turnId,
          });
        } else if (
          event.type === "document.created" ||
          event.type === "document.committed"
        ) {
          telemetry.record("document_committed", {
            sessionId: event.sessionId,
            turnId: event.turnId,
            outcome: "committed",
          });
        } else if (event.type === "document.failed") {
          telemetry.record("document_failed", {
            sessionId: event.sessionId,
            turnId: event.turnId,
            outcome: event.error.code,
          });
          setError({
            category:
              event.error.code === "validation_error" ? "patch" : "producer",
            message: event.error.message,
            retryable: event.error.retryable,
          });
        } else if (event.type === "turn.completed") {
          telemetry.record("turn_outcome", {
            sessionId: event.sessionId,
            turnId: event.turnId,
            outcome: event.documentStatus,
          });
        }
      } catch {
        setError({
          category: "rendering",
          message:
            "An invalid document update was rejected. The prior working document remains visible.",
          retryable: false,
        });
      }
    },
    [replaceConversation, telemetry],
  );

  const initialize = useCallback(async () => {
    const generation = ++initializationGeneration.current;
    appClient.current?.close();
    appClient.current = null;
    voiceClient.current?.stop();
    voiceClient.current = null;
    activeVoiceTurn.current = null;
    submittedVoiceTurns.current.clear();
    pendingVoiceCommands.current.clear();
    setSession(null);
    setAppConnection("connecting");
    setVoiceState("idle");
    replaceConversation(emptyConversationState());
    setLoadState({ status: "loading" });
    try {
      const { capabilities, session: newSession } = await loadBootstrap();
      if (generation !== initializationGeneration.current) {
        return;
      }
      setLoadState({ status: "ready", capabilities });
      setSession(newSession);
      const client = new AppEventClient(newSession, {
        telemetry,
        onEvent: handleEvent,
        onState: setAppConnection,
        onError: (transportError) => setError(transportError),
        onSessionUnavailable: () => {
          if (appClient.current === client) {
            initializeRef.current();
          }
        },
      });
      appClient.current = client;
      client.connect();
    } catch {
      if (generation !== initializationGeneration.current) {
        return;
      }
      setLoadState({ status: "failed" });
      setError({
        category: "app_transport",
        message:
          "The isolated backend is unavailable. Start it, then retry this workspace.",
        retryable: true,
      });
    }
  }, [handleEvent, replaceConversation, telemetry]);
  initializeRef.current = () => {
    void initialize();
  };

  useEffect(() => {
    void initialize();
    return () => {
      initializationGeneration.current += 1;
      appClient.current?.close();
      voiceClient.current?.stop();
    };
  }, [initialize]);

  const submitTurn = useCallback(
    (
      transcript: string,
      inputMode: "typed" | "voice",
      existingTurnId?: string,
    ): boolean => {
      if (session === null) {
        setError({
          category: "app_transport",
          message: "The workspace is not ready. Retry the connection.",
          retryable: true,
        });
        return false;
      }
      const trimmed = transcript.trim();
      if (trimmed.length === 0) {
        return false;
      }
      const turnId = existingTurnId ?? crypto.randomUUID();
      const now = new Date().toISOString();
      const command: TurnSubmitCommand = {
        type: "turn.submit",
        commandId: crypto.randomUUID(),
        idempotencyKey: crypto.randomUUID(),
        sessionId: session.sessionId,
        turnId,
        timestamp: now,
        inputMode,
        transcript: trimmed,
      };
      try {
        const client = appClient.current;
        if (client === null) {
          throw new Error("Application transport is unavailable.");
        }
        client.send(command);
        replaceConversation(
          addLocalTurn(conversationRef.current, {
            turnId,
            inputMode,
            transcript: trimmed,
            startedAt: now,
          }),
        );
        if (inputMode === "voice") {
          activeVoiceTurn.current = turnId;
          voiceClient.current?.setCurrentTurn(turnId);
          submittedVoiceTurns.current.add(turnId);
          for (const pending of pendingVoiceCommands.current.get(turnId) ?? []) {
            client.send(pending);
          }
          pendingVoiceCommands.current.delete(turnId);
        }
        return true;
      } catch {
        setError({
          category: "app_transport",
          message:
            "That turn was not sent while the workspace reconnected. Submit it again.",
          retryable: true,
        });
        return false;
      }
    },
    [replaceConversation, session],
  );

  const startVoice = useCallback(() => {
    if (
      loadState.status !== "ready" ||
      !loadState.capabilities.voiceAvailable ||
      appConnection !== "connected" ||
      audioRef.current === null ||
      session === null
    ) {
      return;
    }
    voiceClient.current?.stop();
    const sendVoiceLifecycle = (
      command:
        | VoiceStartCommand
        | VoiceAcknowledgmentCommand
        | VoiceCompleteCommand
        | VoiceInterruptCommand,
    ) => {
      if (!submittedVoiceTurns.current.has(command.turnId)) {
        const pending = pendingVoiceCommands.current.get(command.turnId) ?? [];
        pending.push(command);
        pendingVoiceCommands.current.set(command.turnId, pending);
        return;
      }
      try {
        const appTransport = appClient.current;
        if (appTransport === null) {
          throw new Error("Application transport is unavailable.");
        }
        appTransport.send(command);
      } catch {
        setError({
          category: "app_transport",
          message:
            "A voice lifecycle update could not be delivered. Reconnect before continuing.",
          retryable: true,
        });
      }
    };
    const client = createVoiceClient(capabilities.voiceProvider, {
      sessionId: session.sessionId,
      sessionToken: session.sessionToken,
      audio: audioRef.current,
      telemetry,
      onState: setVoiceState,
      onSpeechStarted: () => {
        const turnId = crypto.randomUUID();
        activeVoiceTurn.current = turnId;
        return turnId;
      },
      onFinalTranscript: (transcript, turnId) =>
        submitTurn(transcript, "voice", turnId),
      onVoiceStarted: (turnId) => {
        sendVoiceLifecycle({
          type: "voice.start",
          commandId: crypto.randomUUID(),
          idempotencyKey: crypto.randomUUID(),
          sessionId: session.sessionId,
          turnId,
          timestamp: new Date().toISOString(),
        });
      },
      onAcknowledgment: (acknowledgment, turnId) => {
        const parts = splitAcknowledgment(acknowledgment);
        sendVoiceLifecycle({
          type: "voice.acknowledge",
          commandId: crypto.randomUUID(),
          idempotencyKey: crypto.randomUUID(),
          sessionId: session.sessionId,
          turnId,
          timestamp: new Date().toISOString(),
          intentSummary: parts.intentSummary,
          nextStep: parts.nextStep,
        });
      },
      onCompleted: (turnId) => {
        sendVoiceLifecycle({
          type: "voice.complete",
          commandId: crypto.randomUUID(),
          idempotencyKey: crypto.randomUUID(),
          sessionId: session.sessionId,
          turnId,
          timestamp: new Date().toISOString(),
        });
      },
      onInterrupted: (reason, turnId) => {
        sendVoiceLifecycle({
          type: "voice.interrupt",
          commandId: crypto.randomUUID(),
          idempotencyKey: crypto.randomUUID(),
          sessionId: session.sessionId,
          turnId,
          timestamp: new Date().toISOString(),
          reason,
        });
      },
      onError: setError,
    });
    voiceClient.current = client;
    void client.connect();
  }, [
    loadState,
    appConnection,
    session,
    submitTurn,
    telemetry,
  ]);

  const cancelTurn = useCallback(
    (turnId: string) => {
      if (session === null) {
        return;
      }
      const command: TurnCancelCommand = {
        type: "turn.cancel",
        commandId: crypto.randomUUID(),
        idempotencyKey: crypto.randomUUID(),
        sessionId: session.sessionId,
        turnId,
        timestamp: new Date().toISOString(),
        reason: "User requested cancellation.",
      };
      try {
        const client = appClient.current;
        if (client === null) {
          throw new Error("Application transport is unavailable.");
        }
        client.send(command);
      } catch {
        setError({
          category: "app_transport",
          message: "Cancellation was not sent. Reconnect and try again.",
          retryable: true,
        });
      }
    },
    [session],
  );

  const revertDocument = useCallback(
    (targetVersion: number) => {
      const document = conversationRef.current.document;
      if (session === null || document === null) {
        return;
      }
      const turnId = crypto.randomUUID();
      const now = new Date().toISOString();
      const command: DocumentRevertCommand = {
        type: "document.revert",
        commandId: crypto.randomUUID(),
        idempotencyKey: crypto.randomUUID(),
        sessionId: session.sessionId,
        turnId,
        timestamp: now,
        documentId: document.documentId,
        targetVersion,
        summary: `Restore version ${targetVersion} as a new immutable version.`,
      };
      try {
        const client = appClient.current;
        if (client === null) {
          throw new Error("Application transport is unavailable.");
        }
        client.send(command);
      } catch {
        setError({
          category: "app_transport",
          message: "The restore action was not sent. Reconnect and retry.",
          retryable: true,
        });
      }
    },
    [session],
  );

  if (loadState.status === "loading") {
    return (
      <main className="loading-shell">
        <p className="section-kicker">Opportunity analysis workspace</p>
        <h1>Preparing the dual-channel session…</h1>
        <p role="status">Connecting to the isolated local service.</p>
      </main>
    );
  }

  if (loadState.status === "failed") {
    return (
      <main className="loading-shell">
        <p className="section-kicker">Connection required</p>
        <h1>The workspace could not start.</h1>
        <p>Start the isolated FastAPI service, then create a fresh session.</p>
        <button className="send-button" type="button" onClick={() => void initialize()}>
          Retry workspace
        </button>
      </main>
    );
  }

  const capabilities = loadState.capabilities;
  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">Dual-channel opportunity studio</p>
          <h1>Speak briefly. Build the complete case.</h1>
          <p className="lede">
            Keep the conversation natural while one authoritative document
            accumulates the detailed analysis.
          </p>
        </div>
        <div className="header-trust">
          <ModeBadge
            agentProvider={capabilities.agentProvider}
            voiceProvider={capabilities.voiceProvider}
          />
          <p>
            <strong>Ephemeral workspace.</strong> Restarting the backend deletes
            application-owned history.
          </p>
        </div>
      </header>

      <div className="preview-banner">
        <strong>Public preview voice transport</strong>
        <span>
          Voice Live WebRTC has no production SLA and is not recommended for
          production workloads. The app event lane remains independent.
        </span>
      </div>

      {error ? (
        <ErrorNotice
          error={error}
          onRetry={
            error.category === "app_transport"
              ? initialize
              : [
                    "microphone",
                    "authentication",
                    "voice_live",
                    "voice_transport",
                  ].includes(error.category)
                ? startVoice
                : undefined
          }
          onDismiss={() => setError(null)}
        />
      ) : null}

      <VoiceControls
        voiceAvailable={capabilities.voiceAvailable}
        voiceState={voiceState}
        appConnected={appConnection === "connected"}
        typedValue={typedValue}
        onTypedValue={setTypedValue}
        onTypedSubmit={() => {
          if (submitTurn(typedValue, "typed")) {
            setTypedValue("");
          }
        }}
        onVoiceStart={startVoice}
        onVoiceStop={() => {
          voiceClient.current?.interrupt("user_stop");
          voiceClient.current?.stop();
        }}
      />

      <div className="workspace-grid">
        <TurnTimeline turns={conversation.turns} onCancel={cancelTurn} />
        <WorkingDocument state={conversation} onRevert={revertDocument} />
      </div>

      <footer className="workspace-footer">
        <span>Synthetic opportunity data only</span>
        <span>Audio is never stored by this application</span>
        <span>Mode changes require server restart</span>
      </footer>
      <audio ref={audioRef} autoPlay className="sr-only" aria-hidden="true" />
    </main>
  );
}

async function loadBootstrap(): Promise<Bootstrap> {
  const [response, session] = await Promise.all([
    fetch("/api/capabilities"),
    createAppSession(),
  ]);
  if (!response.ok) {
    throw new Error("Capability request failed.");
  }
  const value: unknown = await response.json();
  if (!isCapabilities(value)) {
    throw new Error("Capability response validation failed.");
  }
  return { capabilities: value, session };
}

function splitAcknowledgment(value: string): {
  readonly intentSummary: string;
  readonly nextStep: string;
} {
  const sentences = value
    .trim()
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
  if (sentences.length === 2) {
    return {
      intentSummary: sentences[0],
      nextStep: sentences[1],
    };
  }
  const single = sentences[0] ?? value.trim();
  const nextStepIndex = single.search(/\b(?:next|now|then),?\s/i);
  if (nextStepIndex > 0) {
    return {
      intentSummary: single.slice(0, nextStepIndex).trim(),
      nextStep: single.slice(nextStepIndex).trim(),
    };
  }
  return {
    intentSummary: single,
    nextStep: "Next, I will continue the requested analysis.",
  };
}

function isCapabilities(value: unknown): value is Capabilities {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  return (
    Object.keys(value).length === 7 &&
    "agentProvider" in value &&
    (value.agentProvider === "deterministic" ||
      value.agentProvider === "foundry") &&
    "voiceProvider" in value &&
    (value.voiceProvider === "off" ||
      value.voiceProvider === "azure-voice-live") &&
    "deepWorkAvailable" in value &&
    value.deepWorkAvailable === true &&
    "voiceAvailable" in value &&
    typeof value.voiceAvailable === "boolean" &&
    "voiceTransport" in value &&
    (value.voiceTransport === "disabled" ||
      value.voiceTransport === "webrtc-public-preview") &&
    "voiceTransportPreview" in value &&
    typeof value.voiceTransportPreview === "boolean" &&
    "statePersistence" in value &&
    value.statePersistence === "process-memory-only"
  );
}
