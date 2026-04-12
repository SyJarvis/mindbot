"""Configuration subsystem."""

from mindbot.config.loader import load_config
from mindbot.config.vision import VISION_PATTERNS
from mindbot.config.schema import (
    AgentConfig,
    Config,
    ContextConfig,
    MemoryConfig,
    ModelConfig,
    EndpointConfig,
    MultimodalConfig,
    ProviderInstanceConfig,
    ProviderConfig,  # backward-compat alias
    RoutingConfig,
    RoutingRule,
    SessionJournalConfig,
    ToolPersistenceStrategy,
    KNOWN_PROVIDER_TYPES,
)
from mindbot.config.bus import ConfigBus
from mindbot.config.persistence import ConfigPersistence
from mindbot.config.sync import ConfigSync
from mindbot.config.integration import AgentConfigIntegration

__all__ = [
    "Config",
    "AgentConfig",
    "ContextConfig",
    "MemoryConfig",
    "ModelConfig",
    "EndpointConfig",
    "MultimodalConfig",
    "ProviderInstanceConfig",
    "ProviderConfig",
    "RoutingConfig",
    "RoutingRule",
    "SessionJournalConfig",
    "ToolPersistenceStrategy",
    "KNOWN_PROVIDER_TYPES",
    "VISION_PATTERNS",
    "load_config",
    # Real-time config system (Phase 1-4)
    "ConfigBus",
    "ConfigPersistence",
    "ConfigSync",
    "AgentConfigIntegration",
]
