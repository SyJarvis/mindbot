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
]
