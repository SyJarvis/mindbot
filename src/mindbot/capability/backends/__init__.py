"""Capability backends – concrete carrier adapters."""

from src.mindbot.capability.backends.base import ExtensionBackend
from src.mindbot.capability.backends.tool_backend import ToolBackend

__all__ = ["ExtensionBackend", "ToolBackend"]
