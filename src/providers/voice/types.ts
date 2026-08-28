export type VoiceProvider = "off" | "azure-voice-live";

export type VoiceConnectionState =
  | "idle"
  | "connecting"
  | "listening"
  | "speaking"
  | "stopped"
  | "failed";

export type VoiceClientErrorCategory =
  | "microphone"
  | "authentication"
  | "voice_live"
  | "voice_transport";

export interface VoiceClientError {
  readonly category: VoiceClientErrorCategory;
  readonly message: string;
  readonly retryable: boolean;
}

export interface VoiceClient {
  connect(): Promise<void>;
  setCurrentTurn(turnId: string): void;
  interrupt(reason: "barge_in" | "user_stop"): void;
  stop(): void;
}

export interface DisabledVoiceClientOptions {
  readonly onState: (state: VoiceConnectionState) => void;
  readonly onError: (error: VoiceClientError) => void;
}
