import type {
  DocumentPatchProposal,
  OpportunityDocument,
} from "./document.ts";

export type VoiceStatus =
  | "not_started"
  | "speaking"
  | "completed"
  | "interrupted"
  | "failed";

export type DocumentResultStatus =
  | "not_started"
  | "pending"
  | "committed"
  | "no_op"
  | "failed"
  | "cancelled"
  | "rejected";

export interface SanitizedError {
  readonly code:
    | "validation_error"
    | "conflict"
    | "queue_full"
    | "cancelled"
    | "internal_error";
  readonly category: "command" | "turn" | "voice" | "document";
  readonly message: string;
  readonly retryable: boolean;
}

export interface EventEnvelope {
  readonly eventId: string;
  readonly idempotencyKey: string;
  readonly sessionId: string;
  readonly turnId: string;
  readonly timestamp: string;
}

export type AppEvent =
  | (EventEnvelope & {
      readonly type: "turn.started";
      readonly sequence: number;
      readonly inputMode: "typed" | "voice";
    })
  | (EventEnvelope & {
      readonly type: "turn.queued";
      readonly position: number;
      readonly dependsOnTurnId?: string | null;
    })
  | (EventEnvelope & {
      readonly type: "turn.rejected";
      readonly reason: string;
      readonly queueDepth: number;
      readonly error: SanitizedError;
    })
  | (EventEnvelope & {
      readonly type: "turn.analysis.started";
      readonly baseDocumentVersion: number;
    })
  | (EventEnvelope & { readonly type: "turn.analysis.cancelling" })
  | (EventEnvelope & {
      readonly type: "turn.analysis.cancelled";
      readonly phase: "queued" | "running";
    })
  | (EventEnvelope & {
      readonly type: "turn.analysis.completed";
      readonly outcome: "committed" | "no_op";
      readonly summary: string;
      readonly documentVersion: number;
      readonly noOpReason?: string | null;
    })
  | (EventEnvelope & { readonly type: "voice.started" })
  | (EventEnvelope & {
      readonly type: "voice.acknowledgment";
      readonly intentSummary: string;
      readonly nextStep: string;
    })
  | (EventEnvelope & {
      readonly type: "voice.interrupted";
      readonly reason: "barge_in" | "user_stop" | "playback_error";
    })
  | (EventEnvelope & { readonly type: "voice.completed" })
  | (EventEnvelope & {
      readonly type: "document.pending";
      readonly documentId: string;
      readonly title: string;
    })
  | (EventEnvelope & {
      readonly type: "document.created";
      readonly documentId: string;
      readonly version: number;
      readonly document: OpportunityDocument;
      readonly markdownProjection: string;
      readonly sourceLabels?: readonly string[];
    })
  | (EventEnvelope & {
      readonly type: "document.patch";
      readonly documentId: string;
      readonly baseVersion: number;
      readonly version: number;
      readonly patch: DocumentPatchProposal;
    })
  | (EventEnvelope & {
      readonly type: "document.committed";
      readonly documentId: string;
      readonly version: number;
      readonly document: OpportunityDocument;
      readonly markdownProjection: string;
      readonly sourceLabels?: readonly string[];
      readonly restoredFromVersion?: number | null;
    })
  | (EventEnvelope & {
      readonly type: "document.failed";
      readonly documentId: string;
      readonly error: SanitizedError;
    })
  | (EventEnvelope & {
      readonly type: "turn.completed";
      readonly audioStatus: VoiceStatus;
      readonly documentStatus: DocumentResultStatus;
      readonly timings: {
        readonly acknowledgmentMs?: number | null;
        readonly documentMs?: number | null;
        readonly totalMs: number;
      };
    });
