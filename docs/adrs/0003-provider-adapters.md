# ADR 0003: Provider adapters

Status: Accepted

Voice and agent providers are independently selected by server configuration and loaded
through factories. Provider-specific transports and SDKs remain inside adapters.
Normalized lifecycle, `DeepWorkOutput`, queue, patch, state, and browser contracts remain
stable. No unsupported provider is registered.
