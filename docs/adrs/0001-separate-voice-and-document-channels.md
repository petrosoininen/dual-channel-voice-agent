# ADR 0001: Separate voice and document channels

Status: Accepted

Voice and structured agent work progress independently but share application-owned turn
correlation. This prevents verbose speech, preserves responsive turn-taking, and keeps
one channel's failure from corrupting the other. Voice interruption does not imply
deep-work cancellation.
