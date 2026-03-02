"""Tool call approval mechanism for agent execution.

This module provides a human-in-the-loop system for approving tool calls,
inspired by OpenClaw's approval workflow. It supports:
- Security levels (deny, allowlist, full)
- Whitelist management
- User approval prompts
- Timeout handling
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from mindbot.agent.models import (
    AgentEvent,
    ApprovalDecision,
    ToolApprovalRequest,
    ToolAskMode,
    ToolSecurityLevel,
)


@dataclass
class ToolApprovalConfig:
    """Configuration for tool approval behavior.

    Attributes:
        security: Default security level for tools
        ask: When to ask for approval
        timeout: Default timeout for approval requests (seconds)
        whitelist: Dictionary mapping tool names to argument patterns
        dangerous_tools: List of tools that require extra confirmation
    """
    security: ToolSecurityLevel = ToolSecurityLevel.ALLOWLIST
    ask: ToolAskMode = ToolAskMode.ON_MISS
    timeout: int = 300  # 5 minutes default
    whitelist: dict[str, list[str]] = field(default_factory=dict)
    dangerous_tools: list[str] = field(default_factory=lambda: ["delete_file", "remove_file", "rm"])

    def is_whitelisted(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Check if a tool call is whitelisted.

        Args:
            tool_name: Name of the tool
            arguments: Arguments passed to the tool

        Returns:
            True if the tool/arguments combo is whitelisted
        """
        if tool_name not in self.whitelist:
            return False

        patterns = self.whitelist[tool_name]
        if not patterns or ".*" in patterns:
            return True

        # Check if any pattern matches the arguments
        args_str = str(arguments)
        for pattern in patterns:
            try:
                if re.search(pattern, args_str):
                    return True
            except re.error:
                # Invalid regex pattern, skip
                continue

        return False

    def is_dangerous(self, tool_name: str) -> bool:
        """Check if a tool is considered dangerous.

        Args:
            tool_name: Name of the tool

        Returns:
            True if the tool is in the dangerous tools list
        """
        return tool_name in self.dangerous_tools

    def get_risk_level(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Determine the risk level of a tool call.

        Args:
            tool_name: Name of the tool
            arguments: Arguments passed to the tool

        Returns:
            Risk level: "low", "medium", or "high"
        """
        if self.is_dangerous(tool_name):
            return "high"

        # Check for potentially dangerous arguments
        dangerous_keywords = ["delete", "remove", "rm", "drop", "truncate"]
        args_str = str(arguments).lower()
        if any(keyword in args_str for keyword in dangerous_keywords):
            return "high"

        return "low" if self.is_whitelisted(tool_name, arguments) else "medium"


@dataclass
class PendingApproval:
    """A pending approval request waiting for user response."""
    request: ToolApprovalRequest
    future: asyncio.Future[ApprovalDecision]
    created_at: float


class ApprovalManager:
    """Manages tool call approval workflow.

    The approval manager coordinates:
    1. Checking security policies
    2. Managing whitelist
    3. Requesting user approval
    4. Handling timeouts
    5. Resolving decisions

    Usage:
        manager = ApprovalManager(config)

        # In agent execution
        decision = await manager.request_approval(
            tool_name="write_file",
            arguments={"path": "/tmp/test.txt", "content": "hello"},
            on_event=lambda e: print(e),
        )

        # In user interface (separate thread/async context)
        manager.resolve(request_id, ApprovalDecision.ALLOW_ONCE)
    """

    def __init__(
        self,
        config: ToolApprovalConfig,
    ) -> None:
        """Initialize the approval manager.

        Args:
            config: Approval configuration
        """
        self.config = config
        self._pending: dict[str, PendingApproval] = {}
        self._lock = asyncio.Lock()

    async def request_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> ApprovalDecision:
        """Request approval for a tool call.

        This method:
        1. Checks security level
        2. Checks whitelist
        3. Sends request event if needed
        4. Waits for user decision

        Args:
            tool_name: Name of the tool being called
            arguments: Arguments passed to the tool
            on_event: Optional callback for events

        Returns:
            The approval decision

        Raises:
            asyncio.TimeoutError: If approval request times out
        """
        # Check security level - DENY means all tools are denied
        if self.config.security == ToolSecurityLevel.DENY:
            if on_event:
                on_event(AgentEvent.tool_call_denied(
                    request_id="",
                    reason="Security level set to DENY"
                ))
            return ApprovalDecision.DENY

        # Check whitelist
        risk_level = self.config.get_risk_level(tool_name, arguments)
        is_whitelisted = self.config.is_whitelisted(tool_name, arguments)

        # Determine if we need to ask
        need_approval = self._should_ask_for_approval(tool_name, is_whitelisted, risk_level)

        if not need_approval:
            # Auto-approve
            return ApprovalDecision.ALLOW_ONCE

        # Create request
        request_id = str(uuid.uuid4())
        reason = self._get_approval_reason(tool_name, is_whitelisted, risk_level)

        request = ToolApprovalRequest(
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
            risk_level=risk_level,
            reason=reason,
            timeout=self.config.timeout,
        )

        # Send request event
        if on_event:
            on_event(AgentEvent.tool_call_request(
                request_id=request_id,
                tool_name=tool_name,
                arguments=arguments,
                risk_level=risk_level,
            ))

        # Wait for decision
        return await self._wait_for_decision(request)

    def _should_ask_for_approval(
        self,
        tool_name: str,
        is_whitelisted: bool,
        risk_level: str,
    ) -> bool:
        """Determine if approval should be requested based on config."""
        # Always ask mode
        if self.config.ask == ToolAskMode.ALWAYS:
            return True

        # Off mode - never ask
        if self.config.ask == ToolAskMode.OFF:
            return False

        # On miss mode - ask if not whitelisted
        if self.config.ask == ToolAskMode.ON_MISS:
            return not is_whitelisted

        return False

    def _get_approval_reason(
        self,
        tool_name: str,
        is_whitelisted: bool,
        risk_level: str,
    ) -> str:
        """Generate a reason string for the approval request."""
        if risk_level == "high":
            return f"Tool '{tool_name}' is considered dangerous"

        if not is_whitelisted:
            return f"Tool '{tool_name}' is not in the whitelist"

        return f"Tool '{tool_name}' requires approval"

    async def _wait_for_decision(self, request: ToolApprovalRequest) -> ApprovalDecision:
        """Wait for user decision with timeout."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[ApprovalDecision] = loop.create_future()
            self._pending[request.request_id] = PendingApproval(
                request=request,
                future=future,
                created_at=loop.time(),
            )

        try:
            # Wait for decision with timeout
            decision = await asyncio.wait_for(future, timeout=request.timeout)
            return decision
        except asyncio.TimeoutError:
            # Clean up on timeout
            async with self._lock:
                self._pending.pop(request.request_id, None)
            raise
        finally:
            # Clean up after decision
            async with self._lock:
                self._pending.pop(request.request_id, None)

    def resolve(self, request_id: str, decision: ApprovalDecision) -> None:
        """Resolve a pending approval request.

        This is called from the user interface when the user makes a decision.

        Args:
            request_id: The ID of the request to resolve
            decision: The user's decision

        Raises:
            KeyError: If request_id is not found
        """
        pending = self._pending.get(request_id)
        if pending is None:
            raise KeyError(f"Request {request_id} not found or already resolved")

        future = pending.future
        if not future.done():
            future.set_result(decision)

            # Add to whitelist if always allowed
            if decision == ApprovalDecision.ALLOW_ALWAYS:
                self.add_to_whitelist(
                    tool_name=pending.request.tool_name,
                    pattern=".*",  # Allow all arguments for this tool
                )

    def add_to_whitelist(self, tool_name: str, pattern: str) -> None:
        """Add a tool/pattern to the whitelist.

        Args:
            tool_name: Name of the tool
            pattern: Regex pattern for arguments (use ".*" for all)
        """
        if tool_name not in self.config.whitelist:
            self.config.whitelist[tool_name] = []

        if pattern not in self.config.whitelist[tool_name]:
            self.config.whitelist[tool_name].append(pattern)

    def remove_from_whitelist(self, tool_name: str, pattern: str | None = None) -> None:
        """Remove a tool/pattern from the whitelist.

        Args:
            tool_name: Name of the tool
            pattern: Pattern to remove (if None, removes all patterns for the tool)
        """
        if tool_name not in self.config.whitelist:
            return

        if pattern is None:
            # Remove all patterns for this tool
            del self.config.whitelist[tool_name]
        else:
            # Remove specific pattern
            self.config.whitelist[tool_name] = [
                p for p in self.config.whitelist[tool_name] if p != pattern
            ]

            if not self.config.whitelist[tool_name]:
                del self.config.whitelist[tool_name]

    def get_pending_requests(self) -> list[ToolApprovalRequest]:
        """Get all pending approval requests.

        Returns:
            List of pending requests
        """
        return [pending.request for pending in self._pending.values()]

    def cancel_all(self) -> None:
        """Cancel all pending approval requests."""
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()
