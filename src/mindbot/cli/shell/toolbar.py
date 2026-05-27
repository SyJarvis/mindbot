"""底部工具栏渲染 — 参考 kimi-cli 两行布局。

Layout:
  ──────────────────────────────────────────────  (separator)
  agent (model-name ○)  ~/cwd [main ± ↑3↓1]  │ tip1 | tip2
    toast message                    context: 45.2%
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import time
from dataclasses import dataclass

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.utils import get_cwidth

from mindbot.cli.shell.toast import current_toast


# ---------------------------------------------------------------------------
# StatusSnapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """Agent 状态快照，供工具栏渲染使用。"""

    model_name: str
    workspace: str
    session_id: str
    thinking: bool = False
    context_usage: float = 0.0  # 0.0 ~ 1.0
    context_tokens: int = 0
    max_context_tokens: int = 0
    queued_count: int = 0      # 消息队列中的待处理消息数


# ---------------------------------------------------------------------------
# Tips
# ---------------------------------------------------------------------------

_TIPS = [
    "alt-enter: newline",
    "ctrl-o: editor",
    "ctrl-v: paste",
    "/help: commands",
    "/model: switch",
    "/status: info",
    "/theme: dark/light",
]

_TIP_SEPARATOR = " | "
_TIP_ROTATE_INTERVAL = 30  # 秒


# ---------------------------------------------------------------------------
# Git（非阻塞 + TTL 缓存，移植自 kimi-cli）
# ---------------------------------------------------------------------------

_GIT_BRANCH_TTL = 5.0
_GIT_STATUS_TTL = 15.0
_MAX_CWD_COLS = 30
_MAX_BRANCH_COLS = 22

_GIT_STATUS_AB_RE = re.compile(r"\[(?:ahead (\d+))?(?:, )?(?:behind (\d+))?\]")


@dataclass
class _GitBranchState:
    timestamp: float = 0.0
    branch: str | None = None
    proc: subprocess.Popen[str] | None = None


@dataclass
class _GitStatusState:
    timestamp: float = 0.0
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    proc: subprocess.Popen[str] | None = None


_git_branch_state = _GitBranchState()
_git_status_state = _GitStatusState()
_tip_rotation_index: int = 0


def _get_git_branch() -> str | None:
    """Return the current git branch name (non-blocking, TTL cached)."""
    state = _git_branch_state
    now = time.monotonic()

    if state.proc is not None:
        returncode = state.proc.poll()
        if returncode is not None:
            try:
                stdout, _ = state.proc.communicate()
                new_branch = stdout.strip() or None
                if new_branch != state.branch:
                    if _git_status_state.proc is not None:
                        with contextlib.suppress(Exception):
                            _git_status_state.proc.terminate()
                        _git_status_state.proc = None
                    _git_status_state.timestamp = 0.0
                state.branch = new_branch
            except Exception:
                state.branch = None
            state.proc = None

    if state.timestamp + _GIT_BRANCH_TTL <= now and state.proc is None:
        state.timestamp = now
        try:
            state.proc = subprocess.Popen(
                ["git", "branch", "--show-current"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            state.branch = None

    return state.branch


def _get_git_status() -> tuple[bool, int, int]:
    """Return (dirty, ahead, behind) via non-blocking cached subprocess."""
    state = _git_status_state
    now = time.monotonic()

    if state.proc is not None:
        returncode = state.proc.poll()
        if returncode is not None:
            try:
                stdout, _ = state.proc.communicate()
                dirty = False
                ahead = 0
                behind = 0
                for line in stdout.splitlines():
                    if line.startswith("## "):
                        m = _GIT_STATUS_AB_RE.search(line)
                        if m:
                            ahead = int(m.group(1) or 0)
                            behind = int(m.group(2) or 0)
                    elif line.strip():
                        dirty = True
                state.dirty = dirty
                state.ahead = ahead
                state.behind = behind
            except Exception:
                pass
            state.proc = None
        elif now - state.timestamp > _GIT_STATUS_TTL:
            with contextlib.suppress(Exception):
                state.proc.terminate()
            state.proc = None
            state.timestamp = now

    if state.timestamp + _GIT_STATUS_TTL <= now and state.proc is None:
        state.timestamp = now
        with contextlib.suppress(Exception):
            state.proc = subprocess.Popen(
                ["git", "status", "--porcelain", "-b"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )

    return state.dirty, state.ahead, state.behind


def _format_git_badge(branch: str, dirty: bool, ahead: int, behind: int) -> str:
    """Format branch name with optional status badge: ``main [± ↑3↓1]``."""
    parts: list[str] = []
    if dirty:
        parts.append("\u00b1")
    sync = ""
    if ahead:
        sync += f"\u2191{ahead}"
    if behind:
        sync += f"\u2193{behind}"
    if sync:
        parts.append(sync)
    if not parts:
        return branch
    return f"{branch} [{' '.join(parts)}]"


# ---------------------------------------------------------------------------
# Width utilities（CJK aware）
# ---------------------------------------------------------------------------

def _display_width(text: str) -> int:
    """Return terminal column width, handling wide Unicode characters."""
    return sum(get_cwidth(c) for c in text)


def _truncate_left(text: str, max_cols: int) -> str:
    """Truncate from the left, prepending '…' if exceeds max_cols."""
    if max_cols <= 0:
        return ""
    if _display_width(text) <= max_cols:
        return text
    ellipsis = "\u2026"
    budget = max_cols - _display_width(ellipsis)
    chars: list[str] = []
    width = 0
    for ch in reversed(text):
        w = get_cwidth(ch)
        if width + w > budget:
            break
        chars.append(ch)
        width += w
    return ellipsis + "".join(reversed(chars))


def _truncate_right(text: str, max_cols: int) -> str:
    """Truncate from the right, appending '…' if exceeds max_cols."""
    if max_cols <= 0:
        return ""
    if _display_width(text) <= max_cols:
        return text
    ellipsis = "\u2026"
    budget = max_cols - _display_width(ellipsis)
    chars: list[str] = []
    width = 0
    for ch in text:
        w = get_cwidth(ch)
        if width + w > budget:
            break
        chars.append(ch)
        width += w
    return "".join(chars) + ellipsis


def _shorten_cwd(path: str) -> str:
    """Replace home directory prefix with ~."""
    home = str(os.path.expanduser("~"))
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


# ---------------------------------------------------------------------------
# Context usage
# ---------------------------------------------------------------------------

def _format_context_status(
    context_usage: float,
    context_tokens: int,
    max_context_tokens: int,
    queued_count: int = 0,
) -> str:
    """Format context usage with gauge bar for toolbar line 2."""
    pct = int(context_usage * 100)
    bar_width = 10
    filled = int(context_usage * bar_width)
    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)

    parts = [f"context: {bar} {pct}%"]
    if max_context_tokens > 0:
        parts.append(f"({context_tokens:,}/{max_context_tokens:,})")
    if queued_count > 0:
        parts.append(f"[+{queued_count}]")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Tips rotation
# ---------------------------------------------------------------------------

def _get_two_rotating_tips() -> str | None:
    """Return string with 2 tips from the rotation."""
    n = len(_TIPS)
    if n == 0:
        return None
    if n == 1:
        return _TIPS[0]
    global _tip_rotation_index
    offset = _tip_rotation_index % n
    tip1 = _TIPS[offset]
    tip2 = _TIPS[(offset + 1) % n]
    return f"{tip1}{_TIP_SEPARATOR}{tip2}"


def _get_one_rotating_tip() -> str | None:
    """Return single tip for current rotation."""
    if not _TIPS:
        return None
    return _TIPS[_tip_rotation_index % len(_TIPS)]


def rotate_tip() -> None:
    """Advance tip rotation (called on each user submission)."""
    global _tip_rotation_index
    _tip_rotation_index += 1


# ---------------------------------------------------------------------------
# Main toolbar renderer
# ---------------------------------------------------------------------------

_last_tip_rotate_time: float = time.monotonic()


def render_toolbar(
    status: StatusSnapshot,
    columns: int,
) -> FormattedText:
    """渲染底部工具栏。

    Line 0: └───...───┘（输入框底部边框）
    Line 1: agent (model ○) ~/cwd [branch ±] │ tip1 | tip2
    Line 2: toast message                    context: XX%
    """
    global _last_tip_rotate_time, _tip_rotation_index

    fragments: list[tuple[str, str]] = []

    # ── Input box bottom border ────────────────────────────────────────
    fragments.append(
        ("class:input.separator", "\u2514" + "\u2500" * max(0, columns - 2) + "\u2518")
    )
    fragments.append(("", "\n"))

    # ── Time-based tip rotation ────────────────────────────────────────
    now = time.monotonic()
    if now - _last_tip_rotate_time >= _TIP_ROTATE_INTERVAL:
        _tip_rotation_index += 1
        _last_tip_rotate_time = now

    remaining = columns

    # ── Mode + model + thinking dot ────────────────────────────────────
    thinking_dot = "\u25cf" if status.thinking else "\u25cb"
    dot_style = "class:toolbar.thinking" if status.thinking else "class:toolbar.idle"

    # Degrade gracefully on narrow terminals:
    #   full: "agent (model-name ○)"  → mid: "agent ○"  → bare: "agent"
    mode_full = f"agent ({status.model_name} {thinking_dot})"
    mode_mid = f"agent {thinking_dot}"
    mode_bare = "agent"

    if _display_width(mode_full) <= remaining - 2:
        model_text = f"agent ({status.model_name} "
        fragments.append(("", model_text))
        remaining -= _display_width(model_text)
        fragments.append((dot_style, thinking_dot))
        remaining -= 1
        fragments.append(("", ") "))
        remaining -= 3
    elif _display_width(mode_mid) <= remaining - 2:
        fragments.append(("", "agent "))
        remaining -= 6
        fragments.append((dot_style, thinking_dot))
        remaining -= 1
        fragments.append(("", " "))
        remaining -= 1
    else:
        fragments.append(("", mode_bare))
        remaining -= _display_width(mode_bare)

    # ── CWD + git badge ────────────────────────────────────────────────
    try:
        cwd = _truncate_left(_shorten_cwd(status.workspace), _MAX_CWD_COLS)
    except OSError:
        cwd = "?"

    branch = _get_git_branch()
    if branch:
        dirty, ahead, behind = _get_git_status()
        branch = _truncate_right(branch, _MAX_BRANCH_COLS)
        badge = _format_git_badge(branch, dirty, ahead, behind)
        cwd_text = f"{cwd}  {badge}"
    else:
        cwd_text = cwd

    cwd_w = _display_width(cwd_text)
    if cwd_w > remaining - 2:
        cwd_text = cwd  # drop badge
        cwd_w = _display_width(cwd_text)
    if cwd_w > remaining - 2:
        cwd_text = _truncate_right(cwd, max(0, remaining - 2))
        cwd_w = _display_width(cwd_text)
    if cwd_text and remaining >= cwd_w + 2:
        fragments.append(("class:toolbar.cwd", cwd_text))
        fragments.append(("", "  "))
        remaining -= cwd_w + 2

    # ── Tips (right-aligned, 2 tips or fallback to 1) ──────────────────
    tip_text = _get_two_rotating_tips()
    if tip_text and _display_width(tip_text) > remaining:
        tip_text = _get_one_rotating_tip()
    if tip_text and _display_width(tip_text) <= remaining:
        pad = max(0, remaining - _display_width(tip_text))
        fragments.append(("class:toolbar.tip", " " * pad))
        fragments.append(("class:toolbar.tip", tip_text))

    # ── Line 2: toast (left) + context (right) ─────────────────────────
    fragments.append(("", "\n"))

    right_text = _render_right_span(status)
    right_width = _display_width(right_text)

    left_toast = current_toast("left")
    if left_toast is not None:
        max_left = max(0, columns - right_width - 2)
        if max_left > 0:
            left_text = left_toast.message
            if _display_width(left_text) > max_left:
                left_text = _truncate_right(left_text, max_left)
            left_width = _display_width(left_text)
            fragments.append(("class:toolbar.toast", left_text))
        else:
            left_width = 0
    else:
        left_width = 0

    fragments.append(("", " " * max(0, columns - left_width - right_width)))
    if right_text:
        fragments.append(("class:toolbar.context", right_text))

    return FormattedText(fragments)


def _render_right_span(status: StatusSnapshot) -> str:
    """Render the right span of line 2: toast (right) or context usage."""
    right_toast = current_toast("right")
    if right_toast is not None:
        return right_toast.message
    return _format_context_status(
        status.context_usage,
        status.context_tokens,
        status.max_context_tokens,
        status.queued_count,
    )


# ============================================================================
# Rich 版本状态栏（供 LiveRenderer 使用）
# ============================================================================

def render_status_line(
    status: StatusSnapshot,
    columns: int,
) -> "Text":
    """Render a single-line status bar for use inside Rich Live.

    Simplified version of ``render_toolbar`` that outputs a
    :class:`rich.text.Text` instead of ``prompt_toolkit`` formatted text.
    """
    from rich.text import Text

    result = Text()
    remaining = columns

    # ── Model name + thinking dot ──────────────────────────────────────
    thinking_dot = "\u25cf" if status.thinking else "\u25cb"
    dot_style = "bold yellow" if status.thinking else "dim"
    leader = f"  {status.model_name} {thinking_dot}  "
    result.append(leader, style="bold")
    remaining -= len(leader)

    # ── CWD + git badge ────────────────────────────────────────────────
    cwd = _truncate_left(_shorten_cwd(status.workspace), _MAX_CWD_COLS)
    branch = _get_git_branch()
    if branch and remaining > len(cwd) + 5:
        dirty, ahead, behind = _get_git_status()
        branch = _truncate_right(branch, _MAX_BRANCH_COLS)
        badge = _format_git_badge(branch, dirty, ahead, behind)
        segment = f"{cwd} {badge}  "
    else:
        segment = f"{cwd}  "
    result.append(segment, style="dim")
    remaining -= len(segment)

    # ── Tips (right-aligned) ───────────────────────────────────────────
    tip = _get_one_rotating_tip()
    if tip and len(tip) <= remaining:
        pad = max(0, remaining - len(tip))
        result.append(" " * pad + tip, style="dim italic")
        remaining = 0

    # ── Session + context (right-aligned) ──────────────────────────────
    suffix_parts = [f"session: {status.session_id}"]
    if status.max_context_tokens > 0:
        pct = int(status.context_usage * 100)
        suffix_parts.append(f"ctx: {pct}%")
    suffix = "  \u2502  ".join(suffix_parts)
    if remaining >= len(suffix) + 2:
        result.append(" " * max(2, remaining - len(suffix)))
        result.append(suffix, style="dim")

    return result
