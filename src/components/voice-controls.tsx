import type { FormEvent } from "react";
import type { VoiceConnectionState } from "../providers/voice/types.ts";

interface VoiceControlsProps {
  readonly voiceAvailable: boolean;
  readonly voiceState: VoiceConnectionState;
  readonly appConnected: boolean;
  readonly typedValue: string;
  readonly onTypedValue: (value: string) => void;
  readonly onTypedSubmit: () => void;
  readonly onVoiceStart: () => void;
  readonly onVoiceStop: () => void;
}

const VOICE_LABELS: Record<VoiceConnectionState, string> = {
  idle: "Ready",
  connecting: "Connecting",
  listening: "Listening",
  speaking: "Speaking",
  stopped: "Stopped",
  failed: "Needs attention",
};

export function VoiceControls({
  voiceAvailable,
  voiceState,
  appConnected,
  typedValue,
  onTypedValue,
  onTypedSubmit,
  onVoiceStart,
  onVoiceStop,
}: VoiceControlsProps) {
  const active = ["connecting", "listening", "speaking"].includes(voiceState);
  const voiceLabel = voiceAvailable ? VOICE_LABELS[voiceState] : "Unavailable";
  const voiceStatusClass = voiceAvailable ? voiceState : "failed";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onTypedSubmit();
  };

  return (
    <section className="input-panel" aria-labelledby="input-heading">
      <div className="input-heading-row">
        <div>
          <p className="section-kicker">Conversation input</p>
          <h2 id="input-heading">Shape the opportunity</h2>
        </div>
        <div className="connection-states" aria-live="polite">
          <span className={`state-chip state-${appConnected ? "ok" : "warn"}`}>
            Workspace {appConnected ? "connected" : "reconnecting"}
          </span>
          <span className={`state-chip state-${voiceStatusClass}`}>
            Voice {voiceLabel}
          </span>
        </div>
      </div>

      <button
        type="button"
        className={`voice-primary ${active ? "voice-active" : ""}`}
        onClick={active ? onVoiceStop : onVoiceStart}
        disabled={(!voiceAvailable || !appConnected) && !active}
      >
        <span className="mic-mark" aria-hidden="true">
          {active ? "■" : "●"}
        </span>
        <span>
          <strong>{active ? "Stop voice" : "Start voice"}</strong>
          <small>
            {voiceAvailable
              ? !appConnected
                ? "Workspace connection required"
                : active
                ? "Stops microphone and playback"
                : "Realtime preview · microphone required"
              : "Voice is not configured · typed input remains available"}
          </small>
        </span>
      </button>

      <div className="or-divider" aria-hidden="true">
        <span>or type</span>
      </div>
      <form onSubmit={submit} className="typed-form">
        <label htmlFor="typed-turn">Send the same analysis command path</label>
        <div className="typed-row">
          <textarea
            id="typed-turn"
            rows={3}
            value={typedValue}
            onChange={(event) => onTypedValue(event.target.value)}
            placeholder="Ask for an opportunity review or refine the current analysis…"
            maxLength={4000}
          />
          <button
            className="send-button"
            type="submit"
            disabled={!appConnected || typedValue.trim().length === 0}
          >
            Send turn
          </button>
        </div>
      </form>
    </section>
  );
}
