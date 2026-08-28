import type {
  DisabledVoiceClientOptions,
  VoiceClient,
  VoiceConnectionState,
} from "./types.ts";

export class DisabledVoiceClient implements VoiceClient {
  readonly #options: DisabledVoiceClientOptions;
  #state: VoiceConnectionState = "idle";

  constructor(options: DisabledVoiceClientOptions) {
    this.#options = options;
  }

  async connect(): Promise<void> {
    this.#state = "failed";
    this.#options.onState(this.#state);
    this.#options.onError({
      category: "voice_transport",
      message: "Voice is disabled. Use typed input or configure a voice provider.",
      retryable: false,
    });
  }

  setCurrentTurn(): void {}

  interrupt(): void {}

  stop(): void {
    this.#state = "stopped";
    this.#options.onState(this.#state);
  }
}
