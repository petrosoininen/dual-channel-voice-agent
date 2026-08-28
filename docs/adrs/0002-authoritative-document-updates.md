# ADR 0002: Authoritative document updates

Status: Accepted

Only the backend semantic patch service may mutate the canonical document. Agent output
is a proposal. Complete allowlisted operations, base version, bounds, provenance, and
correlation are validated before atomic commit. No-op and revert preserve auditability.
