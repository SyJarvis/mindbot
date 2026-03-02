"""CLI channel for MindBot."""

import asyncio
import sys
import threading
from typing import Any

from loguru import logger

from mindbot.bus.events import OutboundMessage
from mindbot.bus.queue import MessageBus
from mindbot.channels.base import BaseChannel
from mindbot.agent.models import AgentEvent, EventType, ApprovalDecision


class CLIChannel(BaseChannel):
    """CLI (stdin/stdout) channel for interactive terminal use.

    This channel handles:
    - Interactive command-line conversations
    - Streaming events with visual feedback
    - Tool approval prompts
    - User input requests
    - Interrupt handling (Ctrl+C)
    """

    name: str = "cli"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self._input_task: asyncio.Task | None = None
        self._current_request_id: str | None = None
        self._pending_approvals: dict[str, asyncio.Future] = {}
        self._pending_inputs: dict[str, asyncio.Future] = {}
        self._agent_ref: Any = None  # Reference to agent for resolving approvals

    def set_agent(self, agent: Any) -> None:
        """Set reference to agent for approval resolution."""
        self._agent_ref = agent

    async def start(self) -> None:
        """Start the CLI channel."""
        self._running = True
        self._input_task = asyncio.create_task(self._read_input())
        logger.info("CLI channel started")

    async def stop(self) -> None:
        """Stop the CLI channel."""
        self._running = False

        # Cancel all pending futures
        for future in list(self._pending_approvals.values()):
            if not future.done():
                future.cancel()
        for future in list(self._pending_inputs.values()):
            if not future.done():
                future.cancel()

        if self._input_task:
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass
        logger.info("CLI channel stopped")

    async def _read_input(self) -> None:
        """Read input from stdin and send to message bus."""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # Check if there's a pending request
                if self._current_request_id:
                    # This input is for a pending request (approval or input)
                    line = await loop.run_in_executor(None, input, "> ")
                    await self._handle_request_response(line.strip())
                else:
                    # Regular chat input
                    line = await loop.run_in_executor(None, input, ">>> ")

                if not line.strip():
                    continue

                if line.strip().lower() in ["exit", "quit", "bye"]:
                    break

                # Only send to bus if not handling a request
                if not self._current_request_id:
                    await self._handle_message(
                        sender_id="cli_user",
                        chat_id="cli",
                        content=line.strip(),
                        metadata={"session_id": "default", "use_tools": True}
                    )

            except EOFError:
                break
            except KeyboardInterrupt:
                # Handle Ctrl+C - abort current operation
                if self._agent_ref:
                    self._agent_ref.abort_execution("default")
                print("\n[Operation aborted]")
                self._current_request_id = None
            except Exception as e:
                logger.error(f"Error reading CLI input: {e}")

    async def _handle_request_response(self, response: str) -> None:
        """Handle response for a pending request."""
        if not self._current_request_id:
            return

        request_id = self._current_request_id

        # Check if it's an approval request
        if request_id in self._pending_approvals:
            future = self._pending_approvals.pop(request_id)
            if not future.done():
                future.set_result(response)
            self._current_request_id = None

        # Check if it's an input request
        elif request_id in self._pending_inputs:
            future = self._pending_inputs.pop(request_id)
            if not future.done():
                future.set_result(response)
            self._current_request_id = None

    async def _prompt_approval(
        self,
        tool_name: str,
        arguments: dict,
        risk_level: str,
        request_id: str,
    ) -> str:
        """Prompt user for tool approval and return decision."""
        print(f"\n{'='*60}")
        print(f"[Tool Call Request]")
        print(f"Tool: {tool_name}")
        print(f"Risk Level: {risk_level.upper()}")
        print(f"Arguments:")
        for key, value in arguments.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}")
        print("Options:")
        print("  1. Allow once")
        print("  2. Allow always (add to whitelist)")
        print("  3. Deny")
        print("> ", end="")

        # Create future for response
        future: asyncio.Future[str] = asyncio.Future()
        self._pending_approvals[request_id] = future
        self._current_request_id = request_id

        # Wait for user response
        try:
            response = await asyncio.wait_for(future, timeout=300)
            # Map response to decision
            response_lower = response.strip().lower()
            if response_lower in ["1", "once", "allow", "y", "yes"]:
                return "allow_once"
            elif response_lower in ["2", "always", "whitelist"]:
                return "allow_always"
            else:
                return "deny"
        except asyncio.TimeoutError:
            print("\n[Request timed out]")
            return "deny"
        finally:
            self._pending_approvals.pop(request_id, None)
            if self._current_request_id == request_id:
                self._current_request_id = None

    async def _prompt_input(self, question: str, request_id: str) -> str:
        """Prompt user for input."""
        print(f"\n[Agent asks: {question}]")
        print("> ", end="")

        # Create future for response
        future: asyncio.Future[str] = asyncio.Future()
        self._pending_inputs[request_id] = future
        self._current_request_id = request_id

        # Wait for user response
        try:
            response = await asyncio.wait_for(future, timeout=300)
            return response
        except asyncio.TimeoutError:
            print("\n[Request timed out]")
            return ""
        finally:
            self._pending_inputs.pop(request_id, None)
            if self._current_request_id == request_id:
                self._current_request_id = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to stdout."""
        # Check if message contains events
        events = msg.metadata.get("events", [])

        if events:
            await self._handle_events(events, msg.metadata.get("session_id", "default"))

        # Print final content
        if msg.content:
            print(f"\n{msg.content}\n>>> ", end="")

    async def _handle_events(self, events: list[AgentEvent], session_id: str) -> None:
        """Handle streaming events."""
        for event in events:
            if event.type == EventType.THINKING:
                print(" [Thinking...]", end="", flush=True)

            elif event.type == EventType.DELTA:
                content = event.data.get("content", "")
                # Simple inline display for streaming
                sys.stdout.write(content)
                sys.stdout.flush()

            elif event.type == EventType.TOOL_CALL_REQUEST:
                # Prompt for approval
                tool_name = event.data.get("tool_name", "")
                arguments = event.data.get("arguments", {})
                risk_level = event.data.get("risk_level", "medium")
                request_id = event.data.get("request_id", "")

                decision = await self._prompt_approval(
                    tool_name, arguments, risk_level, request_id
                )

                # Resolve the approval
                if self._agent_ref:
                    self._agent_ref.resolve_approval(request_id, decision, session_id)

            elif event.type == EventType.TOOL_EXECUTING:
                tool_name = event.data.get("tool_name", "")
                print(f"\n[Executing: {tool_name}]", end="", flush=True)

            elif event.type == EventType.TOOL_RESULT:
                result = event.data.get("result", "")
                if result:
                    print(f" → {result[:100]}...", end="", flush=True)

            elif event.type == EventType.USER_INPUT_REQUEST:
                question = event.data.get("question", "")
                request_id = event.data.get("request_id", "")

                user_input = await self._prompt_input(question, request_id)

                # Provide the input
                if self._agent_ref:
                    self._agent_ref.provide_input(request_id, user_input, session_id)

            elif event.type == EventType.ERROR:
                message = event.data.get("message", "")
                print(f"\n[Error: {message}]")

            elif event.type == EventType.ABORTED:
                print("\n[Aborted]")
