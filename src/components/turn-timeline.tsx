import type { TurnRecord } from "../state/conversation-store.ts";

interface TurnTimelineProps {
  readonly turns: readonly TurnRecord[];
  readonly onCancel: (turnId: string) => void;
}

const STATUS_LABELS: Record<TurnRecord["lifecycle"], string> = {
  submitting: "Submitting",
  accepted: "Accepted",
  queued: "Queued",
  analyzing: "Analyzing",
  cancelling: "Cancelling",
  cancelled: "Cancelled",
  completed: "Complete",
  failed: "Failed",
  rejected: "Queue full",
};

export function TurnTimeline({ turns, onCancel }: TurnTimelineProps) {
  return (
    <section className="timeline-panel" aria-labelledby="timeline-heading">
      <div className="section-heading">
        <div>
          <p className="section-kicker">Immutable activity</p>
          <h2 id="timeline-heading">Turn timeline</h2>
        </div>
        <span className="count-label">{turns.length} turns</span>
      </div>
      {turns.length === 0 ? (
        <div className="empty-state">
          <span aria-hidden="true">01</span>
          <p>
            Start with voice or typed input. Detailed analysis will build in the
            working document—not as disconnected chat replies.
          </p>
        </div>
      ) : (
        <ol className="turn-list">
          {turns.map((turn, index) => (
            <li key={turn.turnId} className="turn-item">
              <div className="turn-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="turn-body">
                <div className="turn-meta">
                  <span>{turn.inputMode === "voice" ? "Voice" : "Typed"}</span>
                  <span className={`turn-status status-${turn.lifecycle}`}>
                    {STATUS_LABELS[turn.lifecycle]}
                    {turn.queuePosition ? ` · ${turn.queuePosition} in queue` : ""}
                  </span>
                </div>
                <p className="turn-transcript">{turn.transcript}</p>
                {turn.acknowledgment ? (
                  <p className="acknowledgment">
                    <span>Voice acknowledgment</span>
                    {turn.acknowledgment}
                  </p>
                ) : null}
                {turn.completionSummary ? (
                  <div className="analysis-completion">
                    <span>Analysis summary · canonical document remains authoritative</span>
                    <p>{turn.completionSummary}</p>
                    {turn.noOpReason ? (
                      <p>
                        <strong>No document change:</strong> {turn.noOpReason}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {turn.error ? (
                  <p className="inline-error">{turn.error.message}</p>
                ) : null}
                {["queued", "analyzing"].includes(turn.lifecycle) ? (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => onCancel(turn.turnId)}
                  >
                    Cancel deep work
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
