"""Tool approval configuration for agent execution.

This module re-exports the approval configuration from schema.py
to maintain backward compatibility and avoid circular imports.
"""

from __future__ import annotations

from mindbot.config.schema import ToolApprovalConfig, ToolSecurityLevel, ToolAskMode

__all__ = [
    "ToolApprovalConfig",
    "ToolSecurityLevel",
    "ToolAskMode",
]
