"""Stdio subprocess transport for ACP agents.

Spawns an ACP agent as a child process and communicates via
stdin/stdout using NDJSON-framed JSON-RPC 2.0 messages.
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger

from mindbot.acp.protocol import JsonRpcConnection


class StdioTransport:
    """Manages an ACP agent subprocess communicating over stdio.

    Usage::

        transport = StdioTransport()
        await transport.start("npx", ["-y", "@zed-industries/claude-code-acp"], cwd="/project")
        # transport.connection is now a JsonRpcConnection
        result = await transport.connection.send_request("initialize", {...})
        await transport.stop()
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self.connection: JsonRpcConnection | None = None

    async def start(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Spawn the agent subprocess and initialise the JSON-RPC connection."""
        merged_env = {**os.environ, **(env or {})}
        cmd = [command, *(args or [])]
        logger.info("ACP: spawning agent: {}", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=merged_env,
        )

        assert self._process.stdout is not None
        assert self._process.stdin is not None
        assert self._process.stderr is not None

        # Drain stderr in the background.
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        self.connection = JsonRpcConnection(
            reader=self._process.stdout,
            writer=self._process.stdin,
        )
        await self.connection.start()
        logger.info("ACP: agent subprocess started (pid={})", self._process.pid)

    async def stop(self, timeout: float = 5.0) -> None:
        """Shut down the connection and terminate the subprocess."""
        if self.connection:
            await self.connection.close()
            self.connection = None

        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

        if self._process and self._process.returncode is None:
            logger.info("ACP: terminating agent subprocess (pid={})", self._process.pid)
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("ACP: agent did not exit in time, killing")
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None

    @property
    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        return self._process is not None and self._process.returncode is None

    async def restart(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Kill the current subprocess and start a new one."""
        await self.stop()
        await self.start(command, args, env, cwd)

    # -- internal ------------------------------------------------------------

    async def _drain_stderr(self) -> None:
        """Forward subprocess stderr to loguru."""
        assert self._process is not None and self._process.stderr is not None
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("ACP agent stderr: {}", text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("ACP stderr drain error: {}", exc)
