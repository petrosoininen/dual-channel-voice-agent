export interface CommandEnvelope {
  readonly commandId: string;
  readonly idempotencyKey: string;
  readonly sessionId: string;
  readonly timestamp: string;
}

export interface TurnSubmitCommand extends CommandEnvelope {
  readonly type: "turn.submit";
  readonly turnId: string;
  readonly inputMode: "typed" | "voice";
  readonly transcript: string;
}

export interface TurnCancelCommand extends CommandEnvelope {
  readonly type: "turn.cancel";
  readonly turnId: string;
  readonly reason: string;
}

export interface VoiceInterruptCommand extends CommandEnvelope {
  readonly type: "voice.interrupt";
  readonly turnId: string;
  readonly reason: "barge_in" | "user_stop";
}

export interface VoiceStartCommand extends CommandEnvelope {
  readonly type: "voice.start";
  readonly turnId: string;
}

export interface VoiceAcknowledgmentCommand extends CommandEnvelope {
  readonly type: "voice.acknowledge";
  readonly turnId: string;
  readonly intentSummary: string;
  readonly nextStep: string;
}

export interface VoiceCompleteCommand extends CommandEnvelope {
  readonly type: "voice.complete";
  readonly turnId: string;
}

export interface DocumentRevertCommand extends CommandEnvelope {
  readonly type: "document.revert";
  readonly turnId: string;
  readonly documentId: string;
  readonly targetVersion: number;
  readonly summary: string;
}

export type AppCommand =
  | TurnSubmitCommand
  | TurnCancelCommand
  | VoiceStartCommand
  | VoiceAcknowledgmentCommand
  | VoiceCompleteCommand
  | VoiceInterruptCommand
  | DocumentRevertCommand;
