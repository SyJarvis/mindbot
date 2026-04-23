"""Unified permission management system.

This module provides a natural language-based permission system for:
- Directory access authorization
- Configuration modification
- Tool execution approval

All permissions are managed through a single interface with natural language
prompts and persistent user preference storage.

Quick Start::
    from mindbot.permissions import PermissionManager, PermissionRequest, PermissionType

    manager = PermissionManager(config=config_dict, config_path=config_path)
    decision = await manager.request_permission(
        PermissionRequest(
            permission_type=PermissionType.TOOL_EXECUTION,
            resource="delete_file",
            context={"arguments": {"path": "/tmp/test"}},
            reason="用户请求删除临时文件",
            risk_level="high",
        )
    )

Natural language responses supported:
- "确认", "可以", "ok" → Grant for this session
- "永久允许", "记住", "always" → Grant and persist
- "拒绝", "不行", "no" → Deny
"""

from __future__ import annotations

# Re-export public classes
from .permission_manager import (
    PermissionType,
    PermissionDecision,
    PermissionScope,
    PermissionGrant,
    PermissionRequest,
    NaturalLanguageResolver,
    PendingPermission,
    PermissionManager,
)

__all__ = [
    "PermissionType",
    "PermissionDecision",
    "PermissionScope",
    "PermissionGrant",
    "PermissionRequest",
    "NaturalLanguageResolver",
    "PendingPermission",
    "PermissionManager",
]
