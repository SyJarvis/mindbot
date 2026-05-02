"""Cron management tools for MindBot."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from mindbot.capability.backends.tooling.models import Tool

if TYPE_CHECKING:
    from mindbot.cron.service import CronService


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _job_to_dict(job: object) -> dict:
    """Serialise a CronJob to a JSON-friendly dict."""
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule": {
            "kind": job.schedule.kind,
            "at_ms": job.schedule.at_ms,
            "every_ms": job.schedule.every_ms,
            "expr": job.schedule.expr,
            "tz": job.schedule.tz,
        },
        "payload": {
            "message": job.payload.message,
            "deliver": job.payload.deliver,
            "channel": job.payload.channel,
            "to": job.payload.to,
        },
        "state": {
            "next_run_at": _ms_to_iso(job.state.next_run_at_ms),
            "last_run_at": _ms_to_iso(job.state.last_run_at_ms),
            "last_status": job.state.last_status,
            "last_error": job.state.last_error,
        },
        "delete_after_run": job.delete_after_run,
    }


def create_cron_tools(cron_service: CronService, channel_ctx_fn: Any = None) -> list[Tool]:
    """Create cron management tools bound to *cron_service*.

    Args:
        cron_service: The cron service instance.
        channel_ctx_fn: Optional callable returning ``{"channel": ..., "to": ...}``
            for auto-filling delivery when not explicitly provided.
    """

    # ------------------------------------------------------------------
    # cron_add
    # ------------------------------------------------------------------

    async def cron_add(
        name: str,
        schedule_kind: str,
        schedule_value: str,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
    ) -> str:
        """Create a new scheduled task (cron job).

        Args:
            name: A short descriptive name for the task.
            schedule_kind: One of "at", "every", or "cron".
                - "at": Run once at a specific time. schedule_value is an ISO 8601
                  datetime string (e.g. "2025-06-01T09:00:00").
                - "every": Run repeatedly at a fixed interval. schedule_value is a
                  duration string like "5m", "1h", "30s", "2h30m".
                - "cron": Run on a cron schedule. schedule_value is a 5-field cron
                  expression (e.g. "0 9 * * *" for every day at 9:00).
            schedule_value: The schedule definition (see schedule_kind).
            message: The message/prompt that the agent should process when the job fires.
            deliver: Whether to deliver the agent's response to a channel.
            channel: Target channel name (e.g. "telegram") when deliver is True.
            to: Target user/chat ID when deliver is True.
        """
        from mindbot.cron.types import CronSchedule

        kind = schedule_kind.lower().strip()
        if kind not in ("at", "every", "cron"):
            return json.dumps(
                {"error": f"Invalid schedule_kind '{schedule_kind}'. Must be one of: at, every, cron"},
                ensure_ascii=False,
            )

        try:
            if kind == "at":
                from datetime import datetime, timezone

                dt = datetime.fromisoformat(schedule_value)
                at_ms = int(dt.timestamp() * 1000)
                schedule = CronSchedule(kind="at", at_ms=at_ms)

            elif kind == "every":
                every_ms = _parse_duration(schedule_value)
                schedule = CronSchedule(kind="every", every_ms=every_ms)

            else:  # cron
                schedule = CronSchedule(kind="cron", expr=schedule_value)

        except Exception as exc:
            return json.dumps(
                {"error": f"Failed to parse schedule: {exc}"},
                ensure_ascii=False,
            )

        # Auto-fill deliver/channel/to from current channel context
        if not deliver and channel_ctx_fn is not None:
            ctx = channel_ctx_fn()
            if ctx:
                deliver = True
                channel = channel or ctx.get("channel")
                to = to or ctx.get("to")

        job = cron_service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            channel=channel,
            to=to,
        )
        return json.dumps(
            {"ok": True, "job": _job_to_dict(job)},
            ensure_ascii=False,
            indent=2,
        )

    # ------------------------------------------------------------------
    # cron_list
    # ------------------------------------------------------------------

    async def cron_list(include_disabled: bool = False) -> str:
        """List all scheduled tasks.

        Args:
            include_disabled: If True, also show disabled tasks.
        """
        jobs = cron_service.list_jobs(include_disabled=include_disabled)
        return json.dumps(
            {
                "count": len(jobs),
                "jobs": [_job_to_dict(j) for j in jobs],
            },
            ensure_ascii=False,
            indent=2,
        )

    # ------------------------------------------------------------------
    # cron_remove
    # ------------------------------------------------------------------

    async def cron_remove(job_id: str) -> str:
        """Remove a scheduled task by its ID.

        Args:
            job_id: The unique ID of the cron job to remove.
        """
        removed = cron_service.remove_job(job_id)
        return json.dumps(
            {"ok": removed, "job_id": job_id},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # cron_toggle
    # ------------------------------------------------------------------

    async def cron_toggle(job_id: str, enabled: bool = True) -> str:
        """Enable or disable a scheduled task.

        Args:
            job_id: The unique ID of the cron job.
            enabled: True to enable, False to disable.
        """
        job = cron_service.enable_job(job_id, enabled=enabled)
        if job is None:
            return json.dumps(
                {"error": f"Job '{job_id}' not found"},
                ensure_ascii=False,
            )
        return json.dumps(
            {"ok": True, "job": _job_to_dict(job)},
            ensure_ascii=False,
            indent=2,
        )

    # ------------------------------------------------------------------
    # cron_run
    # ------------------------------------------------------------------

    async def cron_run(job_id: str) -> str:
        """Manually trigger a scheduled task immediately.

        Args:
            job_id: The unique ID of the cron job to run.
        """
        ok = await cron_service.run_job(job_id, force=True)
        return json.dumps(
            {"ok": ok, "job_id": job_id},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # cron_status
    # ------------------------------------------------------------------

    async def cron_status() -> str:
        """Return the current status of the cron service."""
        return json.dumps(
            cron_service.status(),
            ensure_ascii=False,
            indent=2,
        )

    # ------------------------------------------------------------------
    # Build tool list
    # ------------------------------------------------------------------

    return [
        Tool(
            name="cron_add",
            description=(
                "Create a new scheduled task (cron job). "
                "Supports three schedule types: "
                '"at" (one-time at ISO datetime), '
                '"every" (repeating interval like "5m", "1h", "30s"), '
                '"cron" (standard 5-field cron expression). '
                "When the job fires, the agent processes the given message."
            ),
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short descriptive name for the task",
                    },
                    "schedule_kind": {
                        "type": "string",
                        "enum": ["at", "every", "cron"],
                        "description": "Schedule type: 'at' (one-time), 'every' (interval), 'cron' (cron expression)",
                    },
                    "schedule_value": {
                        "type": "string",
                        "description": (
                            "Schedule definition. "
                            'For "at": ISO datetime (e.g. "2025-06-01T09:00:00"). '
                            'For "every": duration (e.g. "5m", "1h", "30s"). '
                            'For "cron": 5-field expression (e.g. "0 9 * * *").'
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": "The message the agent should process when the job fires",
                    },
                    "deliver": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether to deliver the response to a channel",
                    },
                    "channel": {
                        "type": "string",
                        "description": 'Target channel name (e.g. "telegram")',
                    },
                    "to": {
                        "type": "string",
                        "description": "Target user/chat ID for delivery",
                    },
                },
                "required": ["name", "schedule_kind", "schedule_value", "message"],
            },
            handler=cron_add,
        ),
        Tool(
            name="cron_list",
            description="List all scheduled tasks. Optionally include disabled tasks.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "include_disabled": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include disabled tasks in the listing",
                    },
                },
            },
            handler=cron_list,
        ),
        Tool(
            name="cron_remove",
            description="Remove a scheduled task by its ID.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The unique ID of the cron job to remove",
                    },
                },
                "required": ["job_id"],
            },
            handler=cron_remove,
        ),
        Tool(
            name="cron_toggle",
            description="Enable or disable a scheduled task.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The unique ID of the cron job",
                    },
                    "enabled": {
                        "type": "boolean",
                        "default": True,
                        "description": "True to enable, False to disable",
                    },
                },
                "required": ["job_id"],
            },
            handler=cron_toggle,
        ),
        Tool(
            name="cron_run",
            description="Manually trigger a scheduled task immediately.",
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The unique ID of the cron job to run",
                    },
                },
                "required": ["job_id"],
            },
            handler=cron_run,
        ),
        Tool(
            name="cron_status",
            description="Return the current status of the cron scheduling service.",
            parameters_schema_override={
                "type": "object",
                "properties": {},
            },
            handler=cron_status,
        ),
    ]


# ======================================================================
# Duration parser
# ======================================================================

_DURATION_RE = None


def _parse_duration(value: str) -> int:
    """Parse a human-friendly duration string to milliseconds.

    Supports formats like: "30s", "5m", "1h", "2h30m", "1d".
    """
    import re

    global _DURATION_RE
    if _DURATION_RE is None:
        _DURATION_RE = re.compile(
            r"(?:(\d+)\s*d)?"
            r"(?:(\d+)\s*h)?"
            r"(?:(\d+)\s*m)?"
            r"(?:(\d+)\s*s)?",
            re.IGNORECASE,
        )

    value = value.strip()
    match = _DURATION_RE.fullmatch(value)
    if not match:
        raise ValueError(
            f"Invalid duration '{value}'. Use format like '5m', '1h', '30s', '2h30m'."
        )

    days, hours, minutes, seconds = match.groups()
    total_ms = 0
    if days:
        total_ms += int(days) * 86_400_000
    if hours:
        total_ms += int(hours) * 3_600_000
    if minutes:
        total_ms += int(minutes) * 60_000
    if seconds:
        total_ms += int(seconds) * 1_000

    if total_ms <= 0:
        raise ValueError(f"Duration '{value}' must be positive.")

    return total_ms
