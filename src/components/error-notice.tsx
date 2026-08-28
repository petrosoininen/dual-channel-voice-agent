export type WorkspaceErrorCategory =
  | "microphone"
  | "authentication"
  | "voice_live"
  | "voice_transport"
  | "app_transport"
  | "producer"
  | "patch"
  | "rendering";

export interface WorkspaceError {
  readonly category: WorkspaceErrorCategory;
  readonly message: string;
  readonly retryable: boolean;
}

interface ErrorNoticeProps {
  readonly error: WorkspaceError;
  readonly onRetry?: () => void;
  readonly onDismiss: () => void;
}

const LABELS: Record<WorkspaceErrorCategory, string> = {
  microphone: "Microphone",
  authentication: "Voice access",
  voice_live: "Voice Live",
  voice_transport: "Realtime audio",
  app_transport: "Workspace connection",
  producer: "Analysis",
  patch: "Document update",
  rendering: "Document rendering",
};

export function ErrorNotice({
  error,
  onRetry,
  onDismiss,
}: ErrorNoticeProps) {
  return (
    <aside className="error-notice" role="alert">
      <div>
        <strong>{LABELS[error.category]}</strong>
        <p>{error.message}</p>
      </div>
      <div className="error-actions">
        {error.retryable && onRetry ? (
          <button type="button" className="text-button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        <button type="button" className="text-button" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </aside>
  );
}
