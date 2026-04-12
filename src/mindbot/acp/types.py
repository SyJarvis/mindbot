"""ACP protocol type definitions.

Pydantic models mirroring the Agent Client Protocol specification.
See https://agentclientprotocol.com and schema/schema.json for the canonical source.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ============================================================================
# Content blocks
# ============================================================================


class TextContent(BaseModel):
    """Text content (plain text or Markdown)."""

    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    """Image content (base64-encoded)."""

    type: Literal["image"] = "image"
    data: str
    mime_type: str = Field(alias="mimeType")
    uri: str | None = None


class ResourceLink(BaseModel):
    """A reference to a resource the agent can access."""

    type: Literal["resource_link"] = "resource_link"
    name: str
    uri: str
    description: str | None = None


class EmbeddedResource(BaseModel):
    """Resource contents embedded directly in a message."""

    type: Literal["resource"] = "resource"
    uri: str
    text: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")


# Union of all content block types
ContentBlock = TextContent | ImageContent | ResourceLink | EmbeddedResource


# ============================================================================
# Tool calls
# ============================================================================


class ToolCallLocation(BaseModel):
    """A file location being accessed or modified by a tool."""

    path: str
    line: int | None = None


class Diff(BaseModel):
    """A diff representing file modifications."""

    type: Literal["diff"] = "diff"
    path: str
    new_text: str = Field(alias="newText")
    old_text: str | None = Field(default=None, alias="oldText")


class TerminalContent(BaseModel):
    """Embed a terminal by its id."""

    type: Literal["terminal"] = "terminal"
    terminal_id: str = Field(alias="terminalId")


class ToolCallContent(BaseModel):
    """Content produced by a tool call."""

    type: Literal["content", "diff", "terminal"]
    # For type == "content"
    content: TextContent | None = None
    # For type == "diff"
    path: str | None = None
    new_text: str | None = Field(default=None, alias="newText")
    old_text: str | None = Field(default=None, alias="oldText")
    # For type == "terminal"
    terminal_id: str | None = Field(default=None, alias="terminalId")


class ToolCall(BaseModel):
    """A tool call initiated by the agent."""

    tool_call_id: str = Field(alias="toolCallId")
    title: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    kind: Literal[
        "read", "edit", "delete", "move", "search",
        "execute", "think", "fetch", "switch_mode", "other",
    ] | None = None
    locations: list[ToolCallLocation] = Field(default_factory=list)
    content: list[ToolCallContent] = Field(default_factory=list)
    raw_input: Any = Field(default=None, alias="rawInput")
    raw_output: Any = Field(default=None, alias="rawOutput")


class ToolCallUpdate(BaseModel):
    """Update to an existing tool call."""

    tool_call_id: str = Field(alias="toolCallId")
    title: str | None = None
    status: Literal["pending", "in_progress", "completed", "failed"] | None = None
    kind: str | None = None
    locations: list[ToolCallLocation] | None = None
    content: list[ToolCallContent] | None = None
    raw_input: Any = Field(default=None, alias="rawInput")
    raw_output: Any = Field(default=None, alias="rawOutput")


# ============================================================================
# Plan
# ============================================================================


class PlanEntry(BaseModel):
    """A single entry in the agent's execution plan."""

    content: str
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["pending", "in_progress", "completed"] = "pending"


class Plan(BaseModel):
    """Agent execution plan."""

    entries: list[PlanEntry]


# ============================================================================
# Session updates (discriminated union via sessionUpdate field)
# ============================================================================


class AgentMessageChunk(BaseModel):
    """A chunk of the agent's response being streamed."""

    session_update: Literal["agent_message_chunk"] = Field(alias="sessionUpdate")
    content: TextContent


class AgentThoughtChunk(BaseModel):
    """A chunk of the agent's internal reasoning."""

    session_update: Literal["agent_thought_chunk"] = Field(alias="sessionUpdate")
    content: TextContent


class ToolCallNotification(BaseModel):
    """Notification that a new tool call has been initiated."""

    session_update: Literal["tool_call"] = Field(alias="sessionUpdate")
    tool_call_id: str = Field(alias="toolCallId")
    title: str
    status: str = "pending"
    kind: str | None = None
    locations: list[ToolCallLocation] = Field(default_factory=list)
    raw_input: Any = Field(default=None, alias="rawInput")


class ToolCallUpdateNotification(BaseModel):
    """Update on the status or results of a tool call."""

    session_update: Literal["tool_call_update"] = Field(alias="sessionUpdate")
    tool_call_id: str = Field(alias="toolCallId")
    title: str | None = None
    status: str | None = None
    kind: str | None = None
    locations: list[ToolCallLocation] | None = None
    content: list[ToolCallContent] | None = None
    raw_input: Any = Field(default=None, alias="rawInput")
    raw_output: Any = Field(default=None, alias="rawOutput")


class PlanNotification(BaseModel):
    """The agent's execution plan."""

    session_update: Literal["plan"] = Field(alias="sessionUpdate")
    entries: list[PlanEntry]


class SessionInfoUpdate(BaseModel):
    """Session metadata update."""

    session_update: Literal["session_info_update"] = Field(alias="sessionUpdate")
    title: str | None = None


# Union of all session update types
SessionUpdate = (
    AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallNotification
    | ToolCallUpdateNotification
    | PlanNotification
    | SessionInfoUpdate
)


# ============================================================================
# Initialize
# ============================================================================


class PromptCapabilities(BaseModel):
    """Prompt capabilities supported by the agent."""

    image: bool = False
    audio: bool = False
    embedded_context: bool = Field(default=False, alias="embeddedContext")


class FileSystemCapabilities(BaseModel):
    """File system capabilities of the client."""

    read_text_file: bool = Field(default=False, alias="readTextFile")
    write_text_file: bool = Field(default=False, alias="writeTextFile")


class ClientCapabilities(BaseModel):
    """Capabilities advertised by the client during initialization."""

    fs: FileSystemCapabilities = Field(default_factory=FileSystemCapabilities)
    terminal: bool = False


class AgentCapabilities(BaseModel):
    """Capabilities advertised by the agent during initialization."""

    prompt_capabilities: PromptCapabilities = Field(
        default_factory=PromptCapabilities, alias="promptCapabilities"
    )
    load_session: bool = Field(default=False, alias="loadSession")


class Implementation(BaseModel):
    """Metadata about client/agent implementation."""

    name: str
    version: str = "0.1.0"
    title: str | None = None


class AuthMethod(BaseModel):
    """An available authentication method."""

    id: str
    name: str
    description: str | None = None


# ============================================================================
# Request / Response types
# ============================================================================


class InitializeResponse(BaseModel):
    """Response to the ``initialize`` method."""

    protocol_version: int = Field(alias="protocolVersion")
    agent_capabilities: AgentCapabilities = Field(
        default_factory=AgentCapabilities, alias="agentCapabilities"
    )
    agent_info: Implementation | None = Field(default=None, alias="agentInfo")
    auth_methods: list[AuthMethod] = Field(default_factory=list, alias="authMethods")


class McpServerStdio(BaseModel):
    """Stdio transport configuration for an MCP server."""

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: list[dict[str, str]] = Field(default_factory=list)


class SessionMode(BaseModel):
    """A mode the agent can operate in."""

    id: str
    name: str
    description: str | None = None


class SessionModeState(BaseModel):
    """The set of modes and the currently active one."""

    current_mode_id: str = Field(alias="currentModeId")
    available_modes: list[SessionMode] = Field(alias="availableModes")


class SessionConfigOption(BaseModel):
    """A session configuration option (e.g. model selector)."""

    id: str
    name: str
    type: str = "select"
    category: str | None = None
    description: str | None = None
    current_value: str | None = Field(default=None, alias="currentValue")


class NewSessionResponse(BaseModel):
    """Response to ``session/new``."""

    session_id: str = Field(alias="sessionId")
    modes: SessionModeState | None = None
    config_options: list[SessionConfigOption] | None = Field(default=None, alias="configOptions")


class PromptResponse(BaseModel):
    """Response to ``session/prompt``."""

    stop_reason: Literal["end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"] = Field(
        alias="stopReason"
    )


# ============================================================================
# Permission request (server-to-client)
# ============================================================================


class PermissionOption(BaseModel):
    """An option presented to the user for a permission request."""

    option_id: str = Field(alias="optionId")
    name: str
    kind: Literal["allow_once", "allow_always", "reject_once", "reject_always"]


class RequestPermissionParams(BaseModel):
    """Parameters for ``session/request_permission``."""

    session_id: str = Field(alias="sessionId")
    tool_call: ToolCallUpdate = Field(alias="toolCall")
    options: list[PermissionOption]


# ============================================================================
# File system requests (server-to-client)
# ============================================================================


class ReadTextFileParams(BaseModel):
    """Parameters for ``fs/read_text_file``."""

    session_id: str = Field(alias="sessionId")
    path: str
    line: int | None = None
    limit: int | None = None


class ReadTextFileResult(BaseModel):
    """Result for ``fs/read_text_file``."""

    content: str


class WriteTextFileParams(BaseModel):
    """Parameters for ``fs/write_text_file``."""

    session_id: str = Field(alias="sessionId")
    path: str
    content: str


# ============================================================================
# Terminal requests (server-to-client)
# ============================================================================


class CreateTerminalParams(BaseModel):
    """Parameters for ``terminal/create``."""

    session_id: str = Field(alias="sessionId")
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: list[dict[str, str]] = Field(default_factory=list)


class CreateTerminalResult(BaseModel):
    """Result for ``terminal/create``."""

    terminal_id: str = Field(alias="terminalId")


class TerminalOutputParams(BaseModel):
    """Parameters for ``terminal/output``."""

    session_id: str = Field(alias="sessionId")
    terminal_id: str = Field(alias="terminalId")


class TerminalOutputResult(BaseModel):
    """Result for ``terminal/output``."""

    output: str
    truncated: bool = False
    exit_status: dict[str, Any] | None = Field(default=None, alias="exitStatus")


class ReleaseTerminalParams(BaseModel):
    """Parameters for ``terminal/release``."""

    session_id: str = Field(alias="sessionId")
    terminal_id: str = Field(alias="terminalId")
