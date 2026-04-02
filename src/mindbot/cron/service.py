"""Cron service for scheduling agent tasks."""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from src.mindbot.cron.types import (
    CronJob,
    CronJobState,
    CronPayload,
    CronSchedule,
    CronStore,
)


def _now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter
            from zoneinfo import ZoneInfo

            # Use caller-provided reference time for deterministic scheduling
            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None

    return None


class CronService:
    """Service for managing and executing scheduled jobs."""

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
    ):
        """Initialize cron service.

        Args:
            store_path: Path to store cron jobs
            on_job: Callback to execute job, returns response text
        """
        self.store_path = store_path
        self.on_job = on_job
        self._store: CronStore | None = None
        self._timer_task: asyncio.Task | None = None
        self._running = False

    def _load_store(self) -> CronStore:
        """Load jobs from disk."""
        if self._store:
            return self._store

        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                jobs = []
                for j in data.get("jobs", []):
                    jobs.append(
                        CronJob(
                            id=j["id"],
                            name=j["name"],
                            enabled=j.get("enabled", True),
                            schedule=CronSchedule(
                                kind=j["schedule"]["kind"],
                                at_ms=j["schedule"].get("atMs"),
                                every_ms=j["schedule"].get("everyMs"),
                                expr=j["schedule"].get("expr"),
                                tz=j["schedule"].get("tz"),
                            ),
                            payload=CronPayload(
                                kind=j["payload"].get("kind", "agent_turn"),
                                message=j["payload"].get("message", ""),
                                deliver=j["payload"].get("deliver", False),
                                channel=j["payload"].get("channel"),
                                to=j["payload"].get("to"),
                            ),
                            state=CronJobState(
                                next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                                last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                                last_status=j.get("state", {}).get("lastStatus"),
                                last_error=j.get("state", {}).get("lastError"),
                            ),
                            created_at_ms=j.get("createdAtMs", 0),
                            updated_at_ms=j.get("updatedAtMs", 0),
                            delete_after_run=j.get("deleteAfterRun", False),
                        )
                    )
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                logger.warning(f"Failed to load cron store: {e}")
                self._store = CronStore()
        else:
            self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """Save jobs to disk."""
        if not self._store:
            return

        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ],
        }

        self.store_path.write_text(json.dumps(data, indent=2))

    # ==================================================================
    # Public API
    # ==================================================================

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str = "",
        deliver: bool = False,
        to: str | None = None,
        channel: str | None = None,
    ) -> CronJob:
        """Add a new cron job."""
        store = self._load_store()

        job = CronJob(
            id=str(uuid.uuid4()),
            name=name,
            schedule=schedule,
            payload=CronPayload(
                message=message,
                deliver=deliver,
                to=to,
                channel=channel,
            ),
            created_at_ms=_now_ms(),
            updated_at_ms=_now_ms(),
            delete_after_run=schedule.kind == "at",
        )

        # Compute next run
        now_ms = _now_ms()
        job.state.next_run_at_ms = _compute_next_run(job.schedule, now_ms)

        store.jobs.append(job)
        self._save_store()

        logger.info(f"Added cron job: {job.name} ({job.id})")
        return job

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all cron jobs."""
        store = self._load_store()
        if include_disabled:
            return store.jobs
        return [j for j in store.jobs if j.enabled]

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job by ID."""
        store = self._load_store()
        original_len = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]

        if len(store.jobs) < original_len:
            self._save_store()
            return True
        return False

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """Enable or disable a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    # Recompute next run
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                else:
                    job.state.next_run_at_ms = None
                self._save_store()
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """Manually run a job."""
        store = self._load_store()
        job = next((j for j in store.jobs if j.id == job_id), None)

        if not job:
            return False

        if not job.enabled and not force:
            return False

        if self.on_job:
            try:
                response = await self.on_job(job)
                job.state.last_status = "ok"
                job.state.last_error = None
                logger.info(f"Job {job.name} completed: {response[:50] if response else 'no response'}...")
            except Exception as e:
                job.state.last_status = "error"
                job.state.last_error = str(e)
                logger.error(f"Job {job.name} failed: {e}")
        else:
            logger.warning(f"No on_job callback configured")

        job.state.last_run_at_ms = _now_ms()
        job.updated_at_ms = _now_ms()

        # Compute next run for repeating jobs
        if job.schedule.kind != "at" or not job.delete_after_run:
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

        # Delete "at" jobs after running
        if job.schedule.kind == "at" and job.delete_after_run:
            store.jobs = [j for j in store.jobs if j.id != job_id]

        self._save_store()
        return True

    def status(self) -> dict:
        """Get cron service status."""
        store = self._load_store()
        enabled = len([j for j in store.jobs if j.enabled])
        return {
            "jobs": len(store.jobs),
            "enabled": enabled,
            "running": self._running,
        }

    # ==================================================================
    # Lifecycle
    # ==================================================================

    async def start(self) -> None:
        """Start the cron service."""
        if self._running:
            return

        self._running = True
        self._timer_task = asyncio.create_task(self._run_loop())
        logger.info("Cron service started")

    async def stop(self) -> None:
        """Stop the cron service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
        logger.info("Cron service stopped")

    async def _run_loop(self) -> None:
        """Main cron loop."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cron loop error: {e}")

            # Sleep for 1 second between checks
            await asyncio.sleep(1)

    async def _tick(self) -> None:
        """Check and run due jobs."""
        store = self._load_store()
        now_ms = _now_ms()

        for job in store.jobs:
            if not job.enabled:
                continue

            if job.state.next_run_at_ms and job.state.next_run_at_ms <= now_ms:
                logger.info(f"Running cron job: {job.name}")
                await self.run_job(job.id)
