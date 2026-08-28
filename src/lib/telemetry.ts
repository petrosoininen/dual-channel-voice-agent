export type TelemetryName =
  | "app_transport_connected"
  | "app_transport_disconnected"
  | "voice_connection_started"
  | "voice_connection_ready"
  | "voice_connection_failed"
  | "voice_acknowledgment_rejected"
  | "voice_input_speech_started"
  | "voice_response_cancel_requested"
  | "voice_response_finished"
  | "speech_ended"
  | "first_audio"
  | "document_pending"
  | "document_committed"
  | "document_failed"
  | "playback_stopped"
  | "turn_outcome";

export interface TelemetryObservation {
  readonly name: TelemetryName;
  readonly sessionId?: string;
  readonly turnId?: string;
  readonly durationMs?: number;
  readonly outcome?: string;
  readonly outputTokens?: number;
  readonly transcriptCharacters?: number;
  readonly at: number;
}

export type ContentFreeDiagnosticObservation = Omit<
  TelemetryObservation,
  "sessionId" | "turnId"
>;

export class ContentFreeTelemetry {
  readonly #observations: TelemetryObservation[] = [];

  record(
    name: TelemetryName,
    fields: Omit<TelemetryObservation, "name" | "at"> = {},
  ): void {
    if (
      fields.durationMs !== undefined &&
      (!Number.isSafeInteger(fields.durationMs) || fields.durationMs < 0)
    ) {
      throw new Error("Telemetry duration is invalid.");
    }
    if (
      fields.outcome !== undefined &&
      !/^[a-z0-9_]{1,40}$/.test(fields.outcome)
    ) {
      throw new Error("Telemetry outcome is invalid.");
    }
    for (const count of [
      fields.outputTokens,
      fields.transcriptCharacters,
    ]) {
      if (
        count !== undefined &&
        (!Number.isSafeInteger(count) || count < 0)
      ) {
        throw new Error("Telemetry count is invalid.");
      }
    }
    this.#observations.push({ name, ...fields, at: performance.now() });
  }

  snapshot(): readonly TelemetryObservation[] {
    return this.#observations.map((observation) => ({ ...observation }));
  }

  diagnosticSnapshot(): readonly ContentFreeDiagnosticObservation[] {
    return this.#observations.map(({ sessionId, turnId, ...observation }) => {
      void sessionId;
      void turnId;
      return { ...observation };
    });
  }
}
