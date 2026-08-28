interface ModeBadgeProps {
  readonly agentProvider: "deterministic" | "foundry";
  readonly voiceProvider: "off" | "azure-voice-live";
}

export function ModeBadge({
  agentProvider,
  voiceProvider,
}: ModeBadgeProps) {
  return (
    <div
      className="mode-badge"
      aria-label={`Agent provider: ${agentProvider}; voice provider: ${voiceProvider}`}
    >
      <span className="mode-dot" aria-hidden="true" />
      <span>
        Agent <strong>{agentProvider}</strong>
      </span>
      <span>
        Voice <strong>{voiceProvider}</strong>
      </span>
      <span className="locked-label">server locked</span>
    </div>
  );
}
