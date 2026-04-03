"""ToolDefinition validator.

Implements the :class:`~mindbot.generation.protocols.ArtifactValidator`
protocol for :class:`~mindbot.generation.models.ToolDefinition`.

Two validation paths exist:

1. **Schema-only validation** (:func:`validate_tool_definition`) – used when
   the caller already has a typed :class:`ToolDefinition` object and wants to
   verify its fields satisfy the contract.

2. **Raw-output validation** (:class:`ToolDefinitionValidator`) – used by the
   :class:`~mindbot.generation.tool_generator.ToolGenerator` to parse and
   validate a raw JSON string returned by the LLM.
"""

from __future__ import annotations

import json
from typing import Any

from mindbot.generation.models import ToolDefinition, ToolDefinitionError
from mindbot.generation.protocols import GenerationRequest, GenerationValidationError
from mindbot.utils import get_logger

logger = get_logger("generation.validator")

# Required top-level fields in a serialised ToolDefinition
_REQUIRED_FIELDS = {"name", "description"}

# Allowed characters in a tool name (must be LLM-function-call safe)
import re
_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


# ---------------------------------------------------------------------------
# Schema-level validation (typed ToolDefinition)
# ---------------------------------------------------------------------------


def validate_tool_definition(defn: ToolDefinition) -> None:
    """Validate a :class:`ToolDefinition` in-place.

    Args:
        defn: The definition to validate.

    Raises:
        ToolDefinitionError: On any validation failure.
    """
    if not defn.name:
        raise ToolDefinitionError("ToolDefinition.name must not be empty")

    if not _NAME_RE.match(defn.name):
        raise ToolDefinitionError(
            f"ToolDefinition.name '{defn.name}' is invalid. "
            "Must match ^[a-zA-Z_][a-zA-Z0-9_]{0,63}$"
        )

    if not defn.description.strip():
        raise ToolDefinitionError("ToolDefinition.description must not be empty")

    _validate_parameters_schema(defn.parameters_schema, context=f"tool '{defn.name}'")


def _validate_parameters_schema(schema: dict[str, Any], *, context: str = "") -> None:
    """Validate that *schema* is a well-formed JSON Schema object.

    Args:
        schema: The schema dict to validate.
        context: A descriptive label for error messages.

    Raises:
        ToolDefinitionError: When the schema is malformed.
    """
    prefix = f"[{context}] " if context else ""

    if not isinstance(schema, dict):
        raise ToolDefinitionError(f"{prefix}parameters_schema must be a dict")

    # Empty schema is valid (tool accepts no parameters)
    if not schema:
        return

    if schema.get("type") != "object":
        raise ToolDefinitionError(
            f"{prefix}parameters_schema must have type='object', "
            f"got {schema.get('type')!r}"
        )

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ToolDefinitionError(
            f"{prefix}parameters_schema.properties must be a dict"
        )

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            raise ToolDefinitionError(
                f"{prefix}property '{prop_name}' schema must be a dict"
            )
        if "type" not in prop_schema:
            raise ToolDefinitionError(
                f"{prefix}property '{prop_name}' schema is missing 'type'"
            )


# ---------------------------------------------------------------------------
# Raw-output validator (implements ArtifactValidator protocol)
# ---------------------------------------------------------------------------


class ToolDefinitionValidator:
    """Parses and validates a raw LLM output string into a
    :class:`~mindbot.generation.models.ToolDefinition`.

    Implements :class:`~mindbot.generation.protocols.ArtifactValidator`.

    The LLM is expected to return a JSON object matching the
    :meth:`~mindbot.generation.models.ToolDefinition.to_dict` schema.  Extra
    fields are silently ignored.
    """

    def validate(self, raw: str, request: GenerationRequest) -> ToolDefinition:
        """Parse *raw* JSON and validate the result.

        Args:
            raw: Raw string from the LLM.
            request: The originating generation request.

        Returns:
            A valid :class:`~mindbot.generation.models.ToolDefinition`.

        Raises:
            GenerationValidationError: When *raw* cannot be parsed or fails
                field-level validation.
        """
        # Strip markdown code fences the LLM sometimes adds
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            # Drop first and last fence lines
            inner = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            cleaned = "\n".join(inner).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise GenerationValidationError(
                f"LLM output is not valid JSON: {exc}", raw=raw
            ) from exc

        if not isinstance(data, dict):
            raise GenerationValidationError(
                "LLM output must be a JSON object", raw=raw
            )

        missing = _REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise GenerationValidationError(
                f"LLM output is missing required fields: {missing}", raw=raw
            )

        try:
            defn = ToolDefinition.from_dict(data)
        except (KeyError, ValueError, TypeError) as exc:
            raise GenerationValidationError(
                f"Could not build ToolDefinition from LLM output: {exc}", raw=raw
            ) from exc

        try:
            validate_tool_definition(defn)
        except ToolDefinitionError as exc:
            raise GenerationValidationError(str(exc), raw=raw) from exc

        logger.debug("Validated ToolDefinition '%s'", defn.name)
        return defn
