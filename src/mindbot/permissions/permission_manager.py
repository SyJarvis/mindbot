"""Core permission manager implementation."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from mindbot.agent.models import AgentEvent


class PermissionType(Enum):
    """Types of permissions that can be requested."""

    DIRECTORY_ACCESS = auto()  # Access to a specific directory
    CONFIG_MODIFY = auto()  # Modification of configuration
    TOOL_EXECUTION = auto()  # Execution of a tool
    FILE_DELETE = auto()  # Deletion of files/directories
    SHELL_COMMAND = auto()  # Execution of shell commands
    UNKNOWN = auto()  # Fallback


class PermissionDecision(Enum):
    """User's decision for a permission request."""

    GRANT_SESSION = auto()  # Grant for this session only
    GRANT_ALWAYS = auto()  # Grant and persist to config
    DENY = auto()  # Deny this request
    DENY_ALWAYS = auto()  # Deny and add to denylist
    CLARIFY = auto()  # Need more clarification


class PermissionScope(Enum):
    """Authorization scope."""

    SESSION = auto()   # Only for this session
    PERSISTENT = auto()  # Saved to config


@dataclass
class PermissionGrant:
    """A recorded permission grant."""

    resource: str  # Path, tool name, or config key
    permission_type: PermissionType
    scope: str  # "session" or "persistent"
    granted_at: datetime
    expires_at: datetime | None = None  # None means never expires

    def is_expired(self) -> bool:
        """Check if this grant has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


@dataclass
class PermissionRequest:
    """A request for user permission."""

    request_id: str
    permission_type: PermissionType
    resource: str
    context: dict[str, Any]
    reason: str
    risk_level: str = "medium"  # low, medium, high
    suggested_action: str | None = None

    def to_natural_language(self) -> str:
        """Generate a natural language prompt for this request."""
        prompts = {
            PermissionType.DIRECTORY_ACCESS: self._directory_prompt,
            PermissionType.CONFIG_MODIFY: self._config_prompt,
            PermissionType.TOOL_EXECUTION: self._tool_prompt,
            PermissionType.FILE_DELETE: self._delete_prompt,
            PermissionType.SHELL_COMMAND: self._shell_prompt,
        }
        generator = prompts.get(self.permission_type, self._generic_prompt)
        return generator()

    def _directory_prompt(self) -> str:
        path = self.context.get("path", self.resource)
        action = self.context.get("action", "访问")
        return (
            f"[yellow]⚠️ 目录访问权限请求[/yellow]\n\n"
            f"MindBot 需要 {action}以下目录:\n"
            f"  [cyan]{path}[/cyan]\n\n"
            f"原因: {self.reason}\n\n"
            f"您可以用自然语言回复，例如:\n"
            f"  • \"确认\" / \"可以\" / \"ok\" - 仅本次允许\n"
            f"  • \"永久允许\" / \"记住\" / \"always\" - 永久授权\n"
            f"  • \"拒绝\" / \"不行\" / \"no\" - 拒绝访问"
        )

    def _config_prompt(self) -> str:
        key = self.resource
        value = self.context.get("value", "...")
        return (
            f"[yellow]⚠️ 配置修改请求[/yellow]\n\n"
            f"MindBot 想要修改配置:\n"
            f"  [cyan]{key}[/cyan] = {value}\n\n"
            f"原因: {self.reason}\n\n"
            f"您可以用自然语言回复，例如:\n"
            f"  • \"确认\" / \"可以\" - 仅本次允许\n"
            f"  • \"永久允许\" / \"记住\" - 永久授权此配置修改\n"
            f"  • \"拒绝\" / \"不行\" - 拒绝修改"
        )

    def _tool_prompt(self) -> str:
        tool_name = self.resource
        args = self.context.get("arguments", {})
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        risk_emoji = "🔴" if self.risk_level == "high" else "🟡" if self.risk_level == "medium" else "🟢"
        return (
            f"[yellow]{risk_emoji} 工具执行请求[/yellow]\n\n"
            f"MindBot 想要执行工具: [cyan]{tool_name}[/cyan]\n"
            f"参数: {args_str}\n\n"
            f"风险等级: {self.risk_level}\n"
            f"原因: {self.reason}\n\n"
            f"您可以用自然语言回复，例如:\n"
            f"  • \"确认\" / \"可以\" / \"ok\" - 仅本次允许\n"
            f"  • \"永久允许\" / \"always allow {tool_name}\" - 永久授权\n"
            f"  • \"拒绝\" / \"no\" - 拒绝执行"
        )

    def _delete_prompt(self) -> str:
        path = self.context.get("path", self.resource)
        return (
            f"[red]🔴 危险操作: 文件删除[/red]\n\n"
            f"MindBot 想要删除: [cyan]{path}[/cyan]\n\n"
            f"⚠️ 此操作不可撤销！\n"
            f"原因: {self.reason}\n\n"
            f"请明确回复:\n"
            f"  • \"确认删除\" / \"yes delete\" - 允许本次删除\n"
            f"  • \"拒绝\" / \"no\" - 取消删除"
        )

    def _shell_prompt(self) -> str:
        command = self.context.get("command", self.resource)
        return (
            f"[yellow]⚠️ Shell 命令执行[/yellow]\n\n"
            f"MindBot 想要执行命令:\n"
            f"  [cyan]$ {command}[/cyan]\n\n"
            f"原因: {self.reason}\n\n"
            f"您可以用自然语言回复，例如:\n"
            f"  • \"确认\" / \"可以\" / \"run it\" - 仅本次允许\n"
            f"  • \"永久允许\" - 永久授权此类命令\n"
            f"  • \"拒绝\" / \"no\" - 拒绝执行"
        )

    def _generic_prompt(self) -> str:
        return (
            f"[yellow]⚠️ 权限请求[/yellow]\n\n"
            f"MindBot 请求: {self.reason}\n"
            f"资源: [cyan]{self.resource}[/cyan]\n\n"
            f"您可以用自然语言回复，例如:\n"
            f"  • \"确认\" / \"可以\" - 仅本次允许\n"
            f"  • \"永久允许\" - 永久授权\n"
            f"  • \"拒绝\" / \"不行\" - 拒绝"
        )


class NaturalLanguageResolver:
    """Resolves natural language responses to permission decisions."""

    # Intent patterns for different languages
    PATTERNS = {
        PermissionDecision.GRANT_SESSION: [
            # Chinese
            r"^是的?$", r"^确认$", r"^同意$", r"^可以$", r"^行$",
            r"^好[的吧]?$", r"^ok$", r"^确定$",
            r"^这次[可以吧]?$", r"^仅?本次?$", r"^临时$",
            r"^session$", r"^s$", r"^once$", r"^this time$",
            r"^run it$", r"^do it$", r"^go ahead$",
            r"^y$", r"^yes$", r"^yeah$", r"^sure$",
            r"^执行$", r"^允许$",
        ],
        PermissionDecision.GRANT_ALWAYS: [
            # Chinese
            r"^永久$", r"^记住$", r"^保存$", r"^以后[都也]?[可以]?$",
            r"^always?$", r"^persist$", r"^save$", r"^remember$",
            r"^永久允许$", r"^always allow",
            r"^add to whitelist$", r"^whitelist$",
            r"^以后都?行$", r"^以后都?可以$",
        ],
        PermissionDecision.DENY: [
            # Chinese
            r"^否$", r"^拒绝$", r"^不可以$", r"^不行$", r"^不能$",
            r"^不[要吧]?$", r"^算了$", r"^取消$", r"^别$",
            r"^no$", r"^n$", r"^deny$", r"^cancel$", r"^stop$",
            r"^skip$", r"^pass$",
        ],
        PermissionDecision.DENY_ALWAYS: [
            r"^永久拒绝$", r"^never$", r"^always deny$",
            r"^加入黑名单$", r"^blacklist$", r"^block$",
        ],
    }

    def resolve(self, message: str) -> tuple[PermissionDecision, float]:
        """Resolve a natural language message to a permission decision.

        Returns:
            Tuple of (decision, confidence)
        """
        text = message.strip().lower()

        for decision, patterns in self.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    return decision, 0.95

        # Check for ambiguous responses
        ambiguous = ["maybe", "perhaps", "或许", "可能", "?"]
        if any(word in text for word in ambiguous):
            return PermissionDecision.CLARIFY, 0.5

        return PermissionDecision.CLARIFY, 0.3


@dataclass
class PendingPermission:
    """A pending permission request."""

    request: PermissionRequest
    future: asyncio.Future[PermissionDecision]
    created_at: datetime


class PermissionManager:
    """Manages all permission requests with natural language support.

    This manager handles:
    - Directory access authorization
    - Configuration modification approval
    - Tool execution approval
    - Persistent grant storage

    Example:
        manager = PermissionManager(config)

        # Request directory access
        decision = await manager.request_permission(
            PermissionRequest(
                permission_type=PermissionType.DIRECTORY_ACCESS,
                resource="/external/project",
                context={"path": "/external/project", "action": "访问"},
                reason="用户请求列出此目录",
            ),
            on_event=lambda e: print(e),
        )

        # Later, resolve from user message
        decision = manager.resolve_from_message("永久允许访问")
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        config_path: Path | None = None,
    ):
        """Initialize the permission manager.

        Args:
            config: Configuration dict with permission settings
            config_path: Path to config file for persisting grants
        """
        self._config = config or {}
        self._config_path = config_path
        self._resolver = NaturalLanguageResolver()
        self._pending: dict[str, PendingPermission] = {}
        self._lock = asyncio.Lock()

        # Session-level grants (not persisted)
        self._session_grants: dict[str, PermissionGrant] = {}

        # Loaded from config (persisted grants)
        self._persistent_grants: dict[str, PermissionGrant] = {}
        self._denylist: set[str] = set()

        self._load_grants()

    def _load_grants(self) -> None:
        """Load persisted grants from config."""
        agent_config = self._config.get("agent", {})

        # Load trusted_paths as directory grants
        for path in agent_config.get("trusted_paths", []):
            self._persistent_grants[self._grant_key(PermissionType.DIRECTORY_ACCESS, path)] = PermissionGrant(
                resource=path,
                permission_type=PermissionType.DIRECTORY_ACCESS,
                scope="persistent",
                granted_at=datetime.now(),
            )

        # Load tool whitelist
        approval_config = agent_config.get("approval", {})
        for tool_name in approval_config.get("whitelist", {}):
            self._persistent_grants[self._grant_key(PermissionType.TOOL_EXECUTION, tool_name)] = PermissionGrant(
                resource=tool_name,
                permission_type=PermissionType.TOOL_EXECUTION,
                scope="persistent",
                granted_at=datetime.now(),
            )

    def grant_key(self, permission_type: PermissionType, resource: str) -> str:
        """Generate a unique key for a grant (public API)."""
        return self._grant_key(permission_type, resource)

    def _grant_key(self, permission_type: PermissionType, resource: str) -> str:
        """Generate a unique key for a grant."""
        return f"{permission_type.name}:{resource}"

    def _is_granted(self, permission_type: PermissionType, resource: str) -> bool:
        """Check if a permission is already granted."""
        key = self._grant_key(permission_type, resource)

        # Check denylist first
        if key in self._denylist:
            return False

        # Check session grants
        if key in self._session_grants:
            return not self._session_grants[key].is_expired()

        # Check persistent grants
        if key in self._persistent_grants:
            return True

        return False

    def check_permission(
        self,
        permission_type: PermissionType,
        resource: str,
    ) -> tuple[bool, str]:
        """Check if a permission is granted without prompting.

        Returns:
            Tuple of (is_granted, reason)
        """
        if self._is_granted(permission_type, resource):
            return True, "Permission already granted"

        # Check auto-approve policies
        if permission_type == PermissionType.DIRECTORY_ACCESS:
            # Check if within workspace
            workspace = self._config.get("agent", {}).get("workspace", "~/.mindbot/workspace")
            try:
                Path(resource).relative_to(Path(workspace).expanduser().resolve())
                return True, "Resource within workspace"
            except ValueError:
                pass

        return False, "Permission not granted"

    async def request_permission(
        self,
        request: PermissionRequest,
        on_event: Callable[[Any], None] | None = None,
        timeout: float = 300.0,
    ) -> PermissionDecision:
        """Request permission from the user.

        Args:
            request: The permission request
            on_event: Callback for sending events to the user
            timeout: Timeout in seconds

        Returns:
            The user's decision
        """
        # Check if already granted
        if self._is_granted(request.permission_type, request.resource):
            return PermissionDecision.GRANT_SESSION

        # Check if in denylist
        key = self._grant_key(request.permission_type, request.resource)
        if key in self._denylist:
            return PermissionDecision.DENY

        # Create pending request
        async with self._lock:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            pending = PendingPermission(
                request=request,
                future=future,
                created_at=datetime.now(),
            )
            self._pending[request.request_id] = pending

        try:
            # Send prompt event
            if on_event:
                from mindbot.agent.models import AgentEvent
                event = AgentEvent.permission_request(
                    request_id=request.request_id,
                    prompt=request.to_natural_language(),
                    permission_type=request.permission_type.name,
                    resource=request.resource,
                    risk_level=request.risk_level,
                )
                on_event(event)

            # Wait for decision
            return await asyncio.wait_for(future, timeout=timeout)

        except asyncio.TimeoutError:
            return PermissionDecision.DENY
        finally:
            async with self._lock:
                self._pending.pop(request.request_id, None)

    def resolve_from_message(
        self,
        request_id: str,
        message: str,
    ) -> PermissionDecision | None:
        """Resolve a pending request from a user message.

        Args:
            request_id: The request ID to resolve
            message: The user's natural language response

        Returns:
            The decision if resolved, None if request not found
        """
        pending = self._pending.get(request_id)
        if not pending:
            return None

        decision, _ = self._resolver.resolve(message)

        if decision == PermissionDecision.CLARIFY:
            return decision  # Don't resolve yet, need clarification

        # Apply the decision
        self._apply_decision(pending.request, decision)

        # Complete the future
        if not pending.future.done():
            pending.future.set_result(decision)

        return decision

    def _apply_decision(
        self,
        request: PermissionRequest,
        decision: PermissionDecision,
    ) -> None:
        """Apply a permission decision."""
        key = self._grant_key(request.permission_type, request.resource)

        if decision == PermissionDecision.GRANT_SESSION:
            self._session_grants[key] = PermissionGrant(
                resource=request.resource,
                permission_type=request.permission_type,
                scope="session",
                granted_at=datetime.now(),
            )

        elif decision == PermissionDecision.GRANT_ALWAYS:
            self._session_grants[key] = PermissionGrant(
                resource=request.resource,
                permission_type=request.permission_type,
                scope="persistent",
                granted_at=datetime.now(),
            )
            self._persistent_grants[key] = self._session_grants[key]
            self._persist_grant(request)

        elif decision == PermissionDecision.DENY_ALWAYS:
            self._denylist.add(key)

    def _persist_grant(self, request: PermissionRequest) -> None:
        """Persist a grant to the config file."""
        if not self._config_path:
            return

        try:
            import json

            config_data = json.loads(self._config_path.read_text(encoding="utf-8"))

            if request.permission_type == PermissionType.DIRECTORY_ACCESS:
                agent = config_data.setdefault("agent", {})
                trusted = agent.setdefault("trusted_paths", [])
                if request.resource not in trusted:
                    trusted.append(request.resource)

            elif request.permission_type == PermissionType.TOOL_EXECUTION:
                agent = config_data.setdefault("agent", {})
                approval = agent.setdefault("approval", {})
                whitelist = approval.setdefault("whitelist", {})
                if request.resource not in whitelist:
                    whitelist[request.resource] = [".*"]  # Allow all args

            self._config_path.write_text(
                json.dumps(config_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        except Exception:
            # Silently fail if we can't persist
            pass

    def get_pending_request(self, request_id: str) -> PermissionRequest | None:
        """Get a pending request by ID."""
        pending = self._pending.get(request_id)
        return pending.request if pending else None

    def has_pending(self) -> bool:
        """Check if there are any pending requests."""
        return bool(self._pending)

    def get_grants(self, scope: str | None = None) -> list[PermissionGrant]:
        """Get all grants, optionally filtered by scope.

        Args:
            scope: "session", "persistent", or None for all
        """
        grants: list[PermissionGrant] = []

        if scope in (None, "session"):
            grants.extend(
                g for g in self._session_grants.values() if not g.is_expired()
            )

        if scope in (None, "persistent"):
            grants.extend(self._persistent_grants.values())

        return grants

    def revoke_grant(
        self,
        permission_type: PermissionType,
        resource: str,
        scope: str | None = None,
    ) -> bool:
        """Revoke a permission grant.

        Args:
            permission_type: The type of permission
            resource: The resource to revoke
            scope: "session", "persistent", or None for both

        Returns:
            True if a grant was removed
        """
        key = self._grant_key(permission_type, resource)
        removed = False

        if scope in (None, "session"):
            if key in self._session_grants:
                del self._session_grants[key]
                removed = True

        if scope in (None, "persistent"):
            if key in self._persistent_grants:
                del self._persistent_grants[key]
                removed = True
                # Also remove from config file
                self._remove_from_config(permission_type, resource)

        return removed

    def _remove_from_config(
        self,
        permission_type: PermissionType,
        resource: str,
    ) -> None:
        """Remove a grant from the config file."""
        if not self._config_path:
            return

        try:
            import json

            config_data = json.loads(self._config_path.read_text(encoding="utf-8"))

            if permission_type == PermissionType.DIRECTORY_ACCESS:
                agent = config_data.get("agent", {})
                trusted = agent.get("trusted_paths", [])
                if resource in trusted:
                    trusted.remove(resource)

            elif permission_type == PermissionType.TOOL_EXECUTION:
                agent = config_data.get("agent", {})
                approval = agent.get("approval", {})
                whitelist = approval.get("whitelist", {})
                if resource in whitelist:
                    del whitelist[resource]

            self._config_path.write_text(
                json.dumps(config_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        except Exception:
            pass

    def clear_session_grants(self) -> None:
        """Clear all session-level grants."""
        self._session_grants.clear()

    # ------------------------------------------------------------------
    # Compatibility layer with ApprovalManager (DEPRECATED)
    # ------------------------------------------------------------------
    # These methods are kept for backward compatibility and will be
    # removed in a future version (v0.5 or v1.0).
    # See: docs/technical-debt.md
    # ------------------------------------------------------------------

    async def request_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        on_event: Callable[[Any], None] | None = None,
        timeout: float = 300.0,
    ) -> Any:
        """Compatibility method for ApprovalManager.request_approval().

        Maps ApprovalDecision to PermissionDecision.

        Args:
            tool_name: Name of the tool being called
            arguments: Arguments passed to the tool
            on_event: Optional callback for events
            timeout: Timeout in seconds

        Returns:
            ApprovalDecision for backward compatibility
        """
        from mindbot.agent.models import ApprovalDecision

        # Determine risk level and reason
        risk_level = self._get_tool_risk_level(tool_name, arguments)
        reason = self._get_tool_approval_reason(tool_name, risk_level)

        request = PermissionRequest(
            request_id=str(uuid.uuid4()),
            permission_type=PermissionType.TOOL_EXECUTION,
            resource=tool_name,
            context={"arguments": arguments, "tool_name": tool_name},
            reason=reason,
            risk_level=risk_level,
        )

        decision = await self.request_permission(request, on_event, timeout)

        # Map PermissionDecision to ApprovalDecision
        mapping = {
            PermissionDecision.GRANT_SESSION: ApprovalDecision.ALLOW_ONCE,
            PermissionDecision.GRANT_ALWAYS: ApprovalDecision.ALLOW_ALWAYS,
            PermissionDecision.DENY: ApprovalDecision.DENY,
            PermissionDecision.DENY_ALWAYS: ApprovalDecision.DENY,
            PermissionDecision.CLARIFY: ApprovalDecision.DENY,  # Treat unclear as deny
        }
        return mapping.get(decision, ApprovalDecision.DENY)

    def _get_tool_risk_level(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Determine risk level for a tool call."""
        dangerous_tools = ["delete_file", "remove_file", "rm", "exec", "eval"]
        if tool_name in dangerous_tools:
            return "high"

        dangerous_keywords = ["delete", "remove", "rm", "drop", "truncate"]
        args_str = str(arguments).lower()
        if any(keyword in args_str for keyword in dangerous_keywords):
            return "high"

        return "medium"

    def _get_tool_approval_reason(self, tool_name: str, risk_level: str) -> str:
        """Generate reason for tool approval request."""
        if risk_level == "high":
            return f"工具 '{tool_name}' 被认为是危险操作"
        return f"工具 '{tool_name}' 需要您的确认"

    def add_to_whitelist(self, tool_name: str, pattern: str = ".*") -> None:
        """Compatibility method for ApprovalManager.add_to_whitelist()."""
        key = self._grant_key(PermissionType.TOOL_EXECUTION, tool_name)
        self._persistent_grants[key] = PermissionGrant(
            resource=tool_name,
            permission_type=PermissionType.TOOL_EXECUTION,
            scope="persistent",
            granted_at=datetime.now(),
        )

    def remove_from_whitelist(self, tool_name: str, pattern: str | None = None) -> None:
        """Compatibility method for ApprovalManager.remove_from_whitelist()."""
        key = self._grant_key(PermissionType.TOOL_EXECUTION, tool_name)
        if key in self._session_grants:
            del self._session_grants[key]
        if key in self._persistent_grants:
            del self._persistent_grants[key]
            self._remove_from_config(PermissionType.TOOL_EXECUTION, tool_name)

    def is_whitelisted(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Compatibility method for ApprovalManager.is_whitelisted()."""
        return self._is_granted(PermissionType.TOOL_EXECUTION, tool_name)

    def get_pending_requests(self) -> list[Any]:
        """Compatibility method for ApprovalManager.get_pending_requests()."""
        return [p.request for p in self._pending.values()]

    def resolve(self, request_id: str, decision: Any) -> None:
        """Compatibility method for ApprovalManager.resolve().

        Maps ApprovalDecision to PermissionDecision.
        """
        from mindbot.agent.models import ApprovalDecision

        mapping = {
            ApprovalDecision.ALLOW_ONCE: PermissionDecision.GRANT_SESSION,
            ApprovalDecision.ALLOW_ALWAYS: PermissionDecision.GRANT_ALWAYS,
            ApprovalDecision.DENY: PermissionDecision.DENY,
        }
        perm_decision = mapping.get(decision, PermissionDecision.DENY)

        pending = self._pending.get(request_id)
        if pending:
            self._apply_decision(pending.request, perm_decision)
            if not pending.future.done():
                pending.future.set_result(perm_decision)

    def add_session_grant(self, grant: PermissionGrant) -> None:
        """Add a session-level grant."""
        key = self._grant_key(grant.permission_type, grant.resource)
        self._session_grants[key] = grant

    def add_persistent_grant(self, grant: PermissionGrant) -> None:
        """Add a persistent grant."""
        key = self._grant_key(grant.permission_type, grant.resource)
        self._session_grants[key] = grant
        self._persistent_grants[key] = grant

    def add_to_denylist(self, permission_type: PermissionType, resource: str) -> None:
        """Add a resource to the denylist."""
        key = self._grant_key(permission_type, resource)
        self._denylist.add(key)
