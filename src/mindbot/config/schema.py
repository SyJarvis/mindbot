"""Mindbot configuration schema — single source of truth."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============================================================================
# Approval Enums (moved here to avoid circular imports)
# ============================================================================

from enum import Enum


class ToolSecurityLevel(str, Enum):
    """Security level for tool execution."""
    DENY = "deny"           # Tools are denied by default
    ALLOWLIST = "allowlist" # Only whitelisted tools allowed
    FULL = "full"           # Full access (with approval prompt)


class ToolAskMode(str, Enum):
    """When to ask for user approval for tool calls."""
    OFF = "off"             # Never ask for approval
    ON_MISS = "on_miss"     # Ask when not in whitelist
    ALWAYS = "always"       # Always ask for approval


class ModelConfig(BaseModel):
    """Capability declaration for a specific model.

    ``role`` distinguishes how the model is used in the pipeline:

    - ``"chat"``  — conversational / instruction-following (default)
    - ``"embed"`` — embedding / vector representation only

    OCR and rerank roles are reserved for future use.
    """

    id: str
    role: Literal["chat", "embed"] = "chat"
    vision: bool = False
    tool: bool = True
    level: str = "medium"
    enabled: bool = True


class EndpointConfig(BaseModel):
    """A single endpoint configuration for a provider.

    Represents one API endpoint with its credentials and available models.
    A provider can have multiple endpoints for load balancing or failover.
    """

    base_url: str
    api_key: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    models: list[str | ModelConfig] = Field(default_factory=list)
    weight: int = Field(default=1, ge=0, description="Load balancing weight (higher = more requests)")


class ProviderConfig(BaseModel):
    """Any OpenAI-compatible LLM provider.

    Supports two configuration modes:

    1. **Legacy mode** (backward compatible): Use ``base_url`` and ``api_key`` directly.
       These are automatically converted to a single endpoint.

    2. **Multi-endpoint mode**: Use ``endpoints`` list to configure multiple
       API endpoints for load balancing and failover.

    Example (multi-endpoint)::

        providers:
          openai:
            strategy: "round-robin"  # round-robin | random | priority
            endpoints:
              - base_url: "https://api.openai.com/v1"
                api_key: "sk-key1"
                weight: 2
                models:
                  - id: "gpt-4"
                    level: "high"
              - base_url: "https://api.backup.com/v1"
                api_key: "sk-key2"
                weight: 1
                models:
                  - id: "gpt-4"
                    level: "high"
    """

    strategy: Literal["round-robin", "random", "priority"] = "round-robin"
    endpoints: list[EndpointConfig] = Field(default_factory=list)

    # Legacy fields for backward compatibility
    base_url: str | None = None
    api_key: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    models: list[str | ModelConfig] = Field(default_factory=list)

    @field_validator("endpoints", mode="before")
    @classmethod
    def normalize_endpoints(cls, v: Any, info) -> list[EndpointConfig]:
        """Normalize endpoints and handle legacy configuration."""
        # If endpoints are already provided as list, validate them
        if isinstance(v, list) and len(v) > 0:
            if isinstance(v[0], EndpointConfig):
                return v
            elif isinstance(v[0], dict):
                return [EndpointConfig(**item) for item in v]

        # Legacy mode: create endpoint from base_url/api_key
        values = info.data
        base_url = values.get("base_url")
        if base_url:
            return [
                EndpointConfig(
                    base_url=base_url,
                    api_key=values.get("api_key", ""),
                    temperature=values.get("temperature"),
                    max_tokens=values.get("max_tokens"),
                    models=values.get("models", []),
                )
            ]

        return v or []

    @field_validator("base_url", mode="before")
    @classmethod
    def clear_base_url_when_endpoints_present(cls, v: Any, info) -> str | None:
        """Clear base_url when endpoints are explicitly provided."""
        endpoints = info.data.get("endpoints")
        if endpoints and len(endpoints) > 0:
            return None
        return v

    def get_effective_endpoints(self) -> list[EndpointConfig]:
        """Return the effective list of endpoints for this provider."""
        if self.endpoints:
            return self.endpoints
        # Fallback for legacy config (shouldn't happen due to validator)
        return [
            EndpointConfig(
                base_url=self.base_url or "",
                api_key=self.api_key,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                models=self.models,
            )
        ]

    def get_all_models(self) -> list[tuple[str, str, ModelConfig | str]]:
        """Return all (endpoint_index, provider, model) tuples from all endpoints.

        This is used by the routing system to discover available models.
        """
        result = []
        for idx, endpoint in enumerate(self.get_effective_endpoints()):
            for model in endpoint.models:
                if isinstance(model, str):
                    result.append((str(idx), model, ModelConfig(id=model, role="chat", level="medium")))
                else:  # ModelConfig
                    result.append((str(idx), model.id, model))
        return result


class RoutingRule(BaseModel):
    """Single routing rule matching user input to a model level."""

    keywords: list[str] = Field(default_factory=list)
    min_length: int | None = None
    max_length: int | None = None
    level: str = "medium"
    priority: int = 0


class RoutingConfig(BaseModel):
    """Model routing configuration."""

    auto: bool = False
    rules: list[RoutingRule] = Field(default_factory=list)


class ToolApprovalConfig(BaseModel):
    """Configuration for tool approval behavior.

    This controls when and how the agent asks for user approval
    before executing tools.

    Attributes:
        security: Default security level for tools
        ask: When to ask for approval
        timeout: Default timeout for approval requests (seconds)
        whitelist: Dictionary mapping tool names to argument patterns
        dangerous_tools: List of tools that require extra confirmation
    """

    security: ToolSecurityLevel = ToolSecurityLevel.ALLOWLIST
    ask: ToolAskMode = ToolAskMode.ON_MISS
    timeout: int = Field(default=300, ge=1, le=3600)  # 5 minutes default
    whitelist: dict[str, list[str]] = Field(default_factory=dict)
    dangerous_tools: list[str] = Field(
        default_factory=lambda: ["delete_file", "remove_file", "rm", "shell", "execute_command"]
    )

    # Helper methods for compatibility with dataclass-based code

    def is_whitelisted(self, tool_name: str, arguments: dict) -> bool:
        """Check if a tool call is whitelisted."""
        if tool_name not in self.whitelist:
            return False

        patterns = self.whitelist[tool_name]
        if not patterns or ".*" in patterns:
            return True

        args_str = str(arguments)
        for pattern in patterns:
            try:
                if re.search(pattern, args_str):
                    return True
            except re.error:
                continue

        return False

    def is_dangerous(self, tool_name: str) -> bool:
        """Check if a tool is considered dangerous."""
        return tool_name in self.dangerous_tools

    def get_risk_level(self, tool_name: str, arguments: dict) -> str:
        """Determine the risk level of a tool call."""
        if self.is_dangerous(tool_name):
            return "high"

        dangerous_keywords = ["delete", "remove", "rm", "drop", "truncate"]
        args_str = str(arguments).lower()
        if any(keyword in args_str for keyword in dangerous_keywords):
            return "high"

        return "low" if self.is_whitelisted(tool_name, arguments) else "medium"

    def add_to_whitelist(self, tool_name: str, pattern: str = ".*") -> None:
        """Add a tool to the whitelist."""
        if tool_name not in self.whitelist:
            self.whitelist[tool_name] = []
        if pattern not in self.whitelist[tool_name]:
            self.whitelist[tool_name].append(pattern)

    def remove_from_whitelist(self, tool_name: str, pattern: str | None = None) -> None:
        """Remove a tool from the whitelist."""
        if tool_name not in self.whitelist:
            return

        if pattern is None:
            del self.whitelist[tool_name]
        else:
            self.whitelist[tool_name] = [
                p for p in self.whitelist[tool_name] if p != pattern
            ]
            if not self.whitelist[tool_name]:
                del self.whitelist[tool_name]


class ToolModelsConfig(BaseModel):
    """Explicit assignments for non-chat tool models.

    Each field accepts a ``"provider/model"`` reference string, identical in
    format to ``agent.model``.  When set, this takes precedence over
    auto-discovery via ``ModelConfig.role``.

    Example::

        tool_models:
          embed: "openai/text-embedding-3-small"
          ocr: "easyocr/default"    # Phase 1.4
    """

    embed: str | None = None
    ocr: str | None = None    # reserved for Phase 1.4
    rerank: str | None = None  # reserved for future use


class ToolPersistenceStrategy(str, Enum):
    """How tool-call messages are persisted after each turn."""
    NONE = "none"
    SUMMARY = "summary"
    FULL = "full"


class AgentConfig(BaseModel):
    """Agent behaviour settings."""

    model: str = "ollama/qwen3"
    max_tokens: int = 8192
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tool_iterations: int = 20
    approval: ToolApprovalConfig = Field(default_factory=ToolApprovalConfig)

    memory_top_k: int = Field(
        default=5,
        ge=0,
        description="Number of memory chunks retrieved per turn by the Scheduler.",
    )
    max_sessions: int = Field(
        default=1000,
        ge=1,
        description="Maximum concurrent sessions to cache per agent instance (LRU eviction).",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt injected into the system_identity block "
        "by the Scheduler at session creation time.",
    )
    tool_persistence: ToolPersistenceStrategy = Field(
        default=ToolPersistenceStrategy.NONE,
        description="Strategy for persisting tool messages into conversation "
        "history after each turn (none | summary | full).",
    )


class MemoryConfig(BaseModel):
    """Memory subsystem settings."""

    model_config = ConfigDict(extra="forbid")

    storage_path: str = "~/.mindbot/data/memory.db"
    markdown_path: str = "~/.mindbot/data/memory"
    short_term_retention_days: int = Field(default=7, ge=1)
    enable_fts: bool = True


class ContextBlocksConfig(BaseModel):
    """Per-block token budgets for the context window.

    Each value is a hard upper limit in tokens.  When ``None``, the budget
    is computed automatically from ``ContextConfig.max_tokens`` using
    built-in default ratios (system 15%, memory 20%, conversation 50%,
    user_input 15%).
    """

    system_identity: int | None = None
    memory: int | None = None
    conversation: int | None = None
    user_input: int | None = None


class ContextCompressionConfig(BaseModel):
    """Strategy-specific knobs for context compression."""

    recent_keep: int = Field(default=4, ge=1)
    extract_threshold: int = Field(default=2, ge=0)


class ContextConfig(BaseModel):
    """Context window management."""

    max_tokens: int = Field(default=8000, ge=1)
    compression: str = "truncate"
    blocks: ContextBlocksConfig = Field(default_factory=ContextBlocksConfig)
    compression_config: ContextCompressionConfig = Field(
        default_factory=ContextCompressionConfig,
    )


class MultimodalConfig(BaseModel):
    """Multimodal (VLM) limits and behaviour."""

    max_images: int = Field(default=10, ge=1)
    max_file_size_mb: float = Field(default=20.0, gt=0)


# ============================================================================
# Channel Configs
# ============================================================================

class HTTPChannelConfig(BaseModel):
    """HTTP channel configuration."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 31211


class CLIChannelConfig(BaseModel):
    """CLI channel configuration."""

    enabled: bool = False


class TelegramChannelConfig(BaseModel):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""


class FeishuChannelConfig(BaseModel):
    """Feishu channel configuration."""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""


class SessionJournalConfig(BaseModel):
    """Session Journal – per-session append-only message persistence."""

    enabled: bool = Field(default=False, description="Enable session journal recording.")
    path: str = Field(
        default="~/.mindbot/data/journal",
        description="Base directory for JSONL session files.",
    )


class DebugConfig(BaseModel):
    """Debug / introspection options."""

    # If set, each turn writes the full prompt (context block summary + messages) to this path.
    dump_prompt_path: str | None = None


class ChannelsConfig(BaseModel):
    """All channels configuration."""

    http: HTTPChannelConfig = Field(default_factory=HTTPChannelConfig)
    cli: CLIChannelConfig = Field(default_factory=CLIChannelConfig)
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    feishu: FeishuChannelConfig = Field(default_factory=FeishuChannelConfig)


class Config(BaseSettings):
    """Root configuration for MindBot.

    Supports environment variables prefixed with ``MIND_`` and nested
    delimiter ``__``.  Example: ``MIND_AGENT__TEMPERATURE=0.5``.
    """

    model_config = SettingsConfigDict(
        env_prefix="MIND_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    agent: AgentConfig = Field(default_factory=AgentConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    session_journal: SessionJournalConfig = Field(default_factory=SessionJournalConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    tool_models: ToolModelsConfig = Field(default_factory=ToolModelsConfig)
    multimodal: MultimodalConfig = Field(default_factory=MultimodalConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)

    @classmethod
    def from_env(cls) -> Config:
        """Load config from environment variables (MIND_*)."""
        return cls()

    @classmethod
    def from_file(cls, path: str | Path) -> Config:
        """Load config from a YAML/JSON file. See :func:`mindbot.config.load_config`."""
        from mindbot.config.loader import load_config
        return load_config(path)
