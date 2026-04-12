"""Permission resolver for ACP agent requests.

Handles ``session/request_permission`` server-to-client calls.
Three-tier strategy: auto-approve safe tools, policy-based decisions,
and (future) interactive approval via chat platform.
"""

from __future__ import annotations

from loguru import logger

from mindbot.acp.types import (
    PermissionOption,
    RequestPermissionParams,
)


class PermissionResolver:
    """Resolve ACP permission requests based on configurable policy.

    Args:
        auto_approve_kinds: Tool kinds to auto-approve (e.g. ``["read", "search"]``).
        allow_paths: Directory roots the agent is allowed to access.
        interactive: Whether to prompt the user interactively (future).
    """

    def __init__(
        self,
        auto_approve_kinds: list[str] | None = None,
        allow_paths: list[str] | None = None,
        interactive: bool = False,
    ):
        self._auto_approve_kinds = set(auto_approve_kinds or ["read", "search"])
        self._allow_paths = allow_paths or []
        self._interactive = interactive

    async def resolve(self, params: dict) -> dict:
        """Resolve a ``session/request_permission`` request.

        Returns the JSON-RPC result dict with ``{"outcome": {"outcome": "selected", "optionId": ...}}``
        or ``{"outcome": {"outcome": "cancelled"}}``.
        """
        tool_call = params.get("toolCall", {})
        kind = tool_call.get("kind")
        title = tool_call.get("title", "")
        options = params.get("options", [])

        # Tier 1: auto-approve safe tool kinds
        if kind in self._auto_approve_kinds:
            approved = self._find_option(options, "allow_once") or self._find_option(options, "allow_always")
            if approved:
                logger.debug("ACP permission: auto-approved '{}' (kind={})", title, kind)
                return {"outcome": {"outcome": "selected", "optionId": approved}}

        # Tier 2: check path whitelist for file operations
        locations = tool_call.get("locations", [])
        if locations and self._allow_paths:
            path = locations[0].get("path", "") if isinstance(locations[0], dict) else getattr(locations[0], "path", "")
            if any(path.startswith(p) for p in self._allow_paths):
                approved = self._find_option(options, "allow_once")
                if approved:
                    logger.debug("ACP permission: path-approved '{}'", title)
                    return {"outcome": {"outcome": "selected", "optionId": approved}}

        # Default: reject
        rejected = self._find_option(options, "reject_once") or self._find_option(options, "reject_always")
        if rejected:
            logger.info("ACP permission: rejected '{}' (kind={})", title, kind)
            return {"outcome": {"outcome": "selected", "optionId": rejected}}

        # Fallback: cancel
        logger.info("ACP permission: no suitable option found, cancelling '{}'", title)
        return {"outcome": {"outcome": "cancelled"}}

    @staticmethod
    def _find_option(options: list[dict], kind: str) -> str | None:
        """Find an option with the given kind and return its optionId."""
        for opt in options:
            if opt.get("kind") == kind:
                return opt.get("optionId")
        return None
