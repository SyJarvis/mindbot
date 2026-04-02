"""Capability layer – unified ability abstraction for MindBot.

Upper-layer modules should import exclusively from this package:

    from mindbot.capability import CapabilityFacade
    from mindbot.capability.models import Capability, CapabilityQuery, CapabilityType
    from mindbot.capability.backends import ExtensionBackend
"""

from src.mindbot.capability.executor import CapabilityExecutor
from src.mindbot.capability.facade import CapabilityFacade
from src.mindbot.capability.models import (
    Capability,
    CapabilityConflictError,
    CapabilityError,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityQuery,
    CapabilityType,
)
from src.mindbot.capability.registry import CapabilityRegistry

__all__ = [
    # Primary API
    "CapabilityFacade",
    # Supporting components (available for Phase 2+ direct use)
    "CapabilityExecutor",
    "CapabilityRegistry",
    # Models
    "Capability",
    "CapabilityQuery",
    "CapabilityType",
    # Errors
    "CapabilityError",
    "CapabilityNotFoundError",
    "CapabilityConflictError",
    "CapabilityExecutionError",
]
