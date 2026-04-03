"""DynamicToolExecutor – executes a ToolDefinition at runtime.

Execution modes (see :class:`~mindbot.generation.models.ImplementationType`):

``CALLABLE``
    The :attr:`~mindbot.generation.models.ToolDefinition.implementation_ref`
    is a dotted import path such as ``"mypackage.mymodule.my_function"``.
    The executor imports the module and looks up the attribute, then calls
    it with the supplied arguments.  Both sync and async callables are
    supported.

``MOCK``
    Returns a predictable echo string for testing and development.  Does not
    require *implementation_ref* to be set.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from typing import Any, Callable

from mindbot.capability.models import CapabilityExecutionError, CapabilityNotFoundError
from mindbot.generation.models import ImplementationType, ToolDefinition
from mindbot.utils import get_logger, truncate

logger = get_logger("generation.executor")

_MAX_RESULT_LENGTH = 50_000


class DynamicToolExecutor:
    """Executes :class:`~mindbot.generation.models.ToolDefinition` instances.

    Callable references are resolved and cached on first call to avoid repeated
    import overhead.
    """

    def __init__(self) -> None:
        # capability_id (== ToolDefinition.id) -> resolved callable
        self._callable_cache: dict[str, Callable[..., Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute *definition* with *arguments*.

        Args:
            definition: The tool definition to execute.
            arguments: Call arguments.
            context: Optional session / step context (forwarded to the callable
                if it declares a ``context`` parameter).

        Returns:
            String result, suitable for passing back to the LLM.

        Raises:
            CapabilityNotFoundError: When the implementation cannot be resolved.
            CapabilityExecutionError: When the callable raises at runtime.
        """
        try:
            result = await self._dispatch(definition, arguments, context)
            return truncate(str(result), _MAX_RESULT_LENGTH)
        except (CapabilityNotFoundError, CapabilityExecutionError):
            raise
        except Exception as exc:
            logger.exception(
                "DynamicToolExecutor: error executing '%s'", definition.name
            )
            raise CapabilityExecutionError(definition.id, cause=exc) from exc

    # ------------------------------------------------------------------
    # Dispatch by ImplementationType
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        defn: ToolDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> Any:
        if defn.implementation_type == ImplementationType.MOCK:
            return self._mock_result(defn, arguments)

        if defn.implementation_type == ImplementationType.CALLABLE:
            handler = self._resolve_callable(defn)
            return await self._invoke(handler, arguments, context)

        raise CapabilityExecutionError(
            defn.id,
            cause=ValueError(
                f"Unsupported implementation_type: {defn.implementation_type!r}"
            ),
        )

    # ------------------------------------------------------------------
    # MOCK
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_result(defn: ToolDefinition, arguments: dict[str, Any]) -> str:
        return f"[mock] {defn.name}({arguments})"

    # ------------------------------------------------------------------
    # CALLABLE
    # ------------------------------------------------------------------

    def _resolve_callable(self, defn: ToolDefinition) -> Callable[..., Any]:
        """Resolve and cache the callable for *defn*."""
        cached = self._callable_cache.get(defn.id)
        if cached is not None:
            return cached

        ref = defn.implementation_ref
        if not ref:
            raise CapabilityNotFoundError(
                f"ToolDefinition '{defn.name}' has empty implementation_ref"
            )

        parts = ref.rsplit(".", 1)
        if len(parts) != 2:
            raise CapabilityNotFoundError(
                f"implementation_ref '{ref}' is not a valid dotted path"
            )

        module_path, attr_name = parts
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            raise CapabilityNotFoundError(
                f"Cannot import module '{module_path}' for tool '{defn.name}': {exc}"
            ) from exc

        handler = getattr(module, attr_name, None)
        if handler is None or not callable(handler):
            raise CapabilityNotFoundError(
                f"'{attr_name}' not found or not callable in '{module_path}'"
            )

        self._callable_cache[defn.id] = handler
        return handler

    @staticmethod
    async def _invoke(
        handler: Callable[..., Any],
        arguments: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> Any:
        """Invoke *handler*, passing *context* only if the signature accepts it."""
        sig = inspect.signature(handler)
        call_args = dict(arguments)
        if "context" in sig.parameters and context is not None:
            call_args["context"] = context

        if inspect.iscoroutinefunction(handler):
            return await handler(**call_args)
        return await asyncio.to_thread(handler, **call_args)
