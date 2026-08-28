"""Request-scoped backend-local tools for Foundry deep work."""

from backend.tools.project_context import (
    PROJECT_CONTEXT_TOOL_NAME,
    create_project_context_tool,
    load_synthetic_project_context,
)
from backend.tools.propose_document_patch import (
    PATCH_PROPOSAL_TOOL_NAME,
    PatchProposalCapture,
    create_patch_proposal_tool,
)

__all__ = [
    "PATCH_PROPOSAL_TOOL_NAME",
    "PROJECT_CONTEXT_TOOL_NAME",
    "PatchProposalCapture",
    "create_patch_proposal_tool",
    "create_project_context_tool",
    "load_synthetic_project_context",
]
