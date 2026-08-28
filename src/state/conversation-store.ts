import type { AppEvent, SanitizedError } from "../contracts/app-events.ts";
import type {
  DocumentPatchProposal,
  OpportunityDocument,
} from "../contracts/document.ts";
import { isAppEvent } from "../contracts/validators.ts";
import { parseSafeMarkdown } from "../lib/safe-markdown.ts";

export type TurnLifecycle =
  | "submitting"
  | "accepted"
  | "queued"
  | "analyzing"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed"
  | "rejected";

export interface TurnRecord {
  readonly turnId: string;
  readonly sequence: number | null;
  readonly inputMode: "typed" | "voice";
  readonly transcript: string;
  readonly startedAt: string;
  readonly lifecycle: TurnLifecycle;
  readonly queuePosition: number | null;
  readonly acknowledgment: string | null;
  readonly audioStatus: string;
  readonly documentStatus: string;
  readonly documentVersion: number | null;
  readonly completionSummary: string | null;
  readonly noOpReason: string | null;
  readonly error: SanitizedError | null;
}

export interface DocumentSnapshot {
  readonly version: number;
  readonly turnId: string;
  readonly document: OpportunityDocument;
  readonly markdownProjection: string;
  readonly summary: string;
  readonly patch: DocumentPatchProposal | null;
  readonly restoredFromVersion?: number | null;
}

export interface ConversationState {
  readonly eventIds: ReadonlySet<string>;
  readonly eventFingerprints: ReadonlyMap<string, string>;
  readonly turns: readonly TurnRecord[];
  readonly document: OpportunityDocument | null;
  readonly markdownProjection: string | null;
  readonly versions: readonly DocumentSnapshot[];
  readonly pendingPatches: ReadonlyMap<string, DocumentPatchProposal>;
}

export function emptyConversationState(): ConversationState {
  return {
    eventIds: new Set<string>(),
    eventFingerprints: new Map<string, string>(),
    turns: [],
    document: null,
    markdownProjection: null,
    versions: [],
    pendingPatches: new Map<string, DocumentPatchProposal>(),
  };
}

export function addLocalTurn(
  state: ConversationState,
  turn: Pick<TurnRecord, "turnId" | "inputMode" | "transcript" | "startedAt">,
): ConversationState {
  if (state.turns.some((item) => item.turnId === turn.turnId)) {
    return state;
  }
  return {
    ...state,
    turns: [
      ...state.turns,
      {
        ...turn,
        sequence: null,
        lifecycle: "submitting",
        queuePosition: null,
        acknowledgment: null,
        audioStatus: "not_started",
        documentStatus: "not_started",
        documentVersion: null,
        completionSummary: null,
        noOpReason: null,
        error: null,
      },
    ],
  };
}

export function addVoiceAcknowledgment(
  state: ConversationState,
  turnId: string,
  acknowledgment: string,
): ConversationState {
  return updateTurn(state, turnId, (turn) => ({ ...turn, acknowledgment }));
}

export function applyAppEvent(
  state: ConversationState,
  value: unknown,
): ConversationState {
  if (!isAppEvent(value)) {
    throw new Error("Application event validation failed.");
  }
  if (
    value.type === "document.created" ||
    value.type === "document.committed"
  ) {
    parseSafeMarkdown(value.markdownProjection);
  }
  const fingerprint = canonicalJson(value);
  if (state.eventIds.has(value.eventId)) {
    if (state.eventFingerprints.get(value.eventId) !== fingerprint) {
      throw new Error("Event identity was reused with different content.");
    }
    return state;
  }

  const eventIds = new Set(state.eventIds);
  const eventFingerprints = new Map(state.eventFingerprints);
  eventIds.add(value.eventId);
  eventFingerprints.set(value.eventId, fingerprint);
  return projectEvent({ ...state, eventIds, eventFingerprints }, value);
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

function projectEvent(
  state: ConversationState,
  event: AppEvent,
): ConversationState {
  switch (event.type) {
    case "turn.started": {
      const existing = state.turns.find((turn) => turn.turnId === event.turnId);
      if (existing !== undefined) {
        return updateTurn(state, event.turnId, (turn) => ({
          ...turn,
          sequence: event.sequence,
          lifecycle: "accepted",
        }));
      }
      return {
        ...state,
        turns: [
          ...state.turns,
          {
            turnId: event.turnId,
            sequence: event.sequence,
            inputMode: event.inputMode,
            transcript: "Submitted turn",
            startedAt: event.timestamp,
            lifecycle: "accepted",
            queuePosition: null,
            acknowledgment: null,
            audioStatus: "not_started",
            documentStatus: "not_started",
            documentVersion: null,
            completionSummary: null,
            noOpReason: null,
            error: null,
          },
        ],
      };
    }
    case "turn.queued":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle: "queued",
        queuePosition: event.position,
      }));
    case "turn.rejected":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle: "rejected",
        documentStatus: "rejected",
        error: event.error,
      }));
    case "turn.analysis.started":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle: "analyzing",
        queuePosition: null,
        documentStatus: "pending",
      }));
    case "turn.analysis.cancelling":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle: "cancelling",
      }));
    case "turn.analysis.cancelled":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle: "cancelled",
        documentStatus: "cancelled",
      }));
    case "turn.analysis.completed":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        completionSummary: event.summary,
        noOpReason: event.noOpReason ?? null,
        documentVersion: event.documentVersion,
      }));
    case "voice.started":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        audioStatus: "speaking",
      }));
    case "voice.acknowledgment":
      return addVoiceAcknowledgment(
        state,
        event.turnId,
        `${event.intentSummary} ${event.nextStep}`,
      );
    case "voice.interrupted":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        audioStatus: "interrupted",
      }));
    case "voice.completed":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        audioStatus: "completed",
      }));
    case "document.patch": {
      const pendingPatches = new Map(state.pendingPatches);
      pendingPatches.set(event.turnId, event.patch);
      return { ...state, pendingPatches };
    }
    case "document.failed":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle: "failed",
        documentStatus: "failed",
        error: event.error,
      }));
    case "turn.completed":
      return updateTurn(state, event.turnId, (turn) => ({
        ...turn,
        lifecycle:
          event.documentStatus === "failed"
            ? "failed"
            : event.documentStatus === "rejected"
              ? "rejected"
              : event.documentStatus === "cancelled"
                ? "cancelled"
                : "completed",
        audioStatus: preserveLaterVoiceStatus(
          turn.audioStatus,
          event.audioStatus,
        ),
        documentStatus: event.documentStatus,
      }));
    case "document.created":
    case "document.committed":
      return projectDocument(state, event);
    default:
      return state;
  }

  function preserveLaterVoiceStatus(
    current: string,
    completedSnapshot: string,
  ): string {
    if (
      ["completed", "interrupted", "failed"].includes(current) &&
      ["not_started", "speaking"].includes(completedSnapshot)
    ) {
      return current;
    }
    return completedSnapshot;
  }
}

function projectDocument(
  state: ConversationState,
  event: Extract<AppEvent, { type: "document.created" | "document.committed" }>,
): ConversationState {
  if (
    event.documentId !== event.document.documentId ||
    event.version !== event.document.version
  ) {
    throw new Error("Document event correlation is invalid.");
  }
  const currentVersion = state.document?.version ?? 0;
  if (event.version < currentVersion || event.version > currentVersion + 1) {
    throw new Error("Document event version is stale or out of order.");
  }
  const existing = state.versions.find(
    (version) => version.version === event.version,
  );
  if (existing !== undefined) {
    if (
      canonicalJson(existing.document) !== canonicalJson(event.document) ||
      existing.markdownProjection !== event.markdownProjection
    ) {
      throw new Error("Document version identity was reused with different content.");
    }
    return {
      ...state,
      document: event.document,
      markdownProjection: event.markdownProjection,
    };
  }
  const patch = state.pendingPatches.get(event.turnId) ?? null;
  const pendingPatches = new Map(state.pendingPatches);
  pendingPatches.delete(event.turnId);
  return {
    ...state,
    document: event.document,
    markdownProjection: event.markdownProjection,
    pendingPatches,
    versions: [
      ...state.versions,
      {
        version: event.version,
        turnId: event.turnId,
        document: event.document,
        markdownProjection: event.markdownProjection,
        summary: patch?.summary ?? "Restored an earlier document version.",
        patch,
        ...(event.type === "document.committed"
          ? { restoredFromVersion: event.restoredFromVersion }
          : {}),
      },
    ],
  };
}

function updateTurn(
  state: ConversationState,
  turnId: string,
  updater: (turn: TurnRecord) => TurnRecord,
): ConversationState {
  let found = false;
  const turns = state.turns.map((turn) => {
    if (turn.turnId !== turnId) {
      return turn;
    }
    found = true;
    return updater(turn);
  });
  return found ? { ...state, turns } : state;
}
