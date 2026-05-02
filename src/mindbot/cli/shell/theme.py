"""主题管理 — 参考 kimi-cli 风格。

配色克制专业，保留 MindBot 品牌色（cyan）作为主色调。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from prompt_toolkit.styles import Style

ThemeName = Literal["dark", "light"]


@dataclass
class ShellTheme:
    """颜色主题。"""

    # Prompt
    prompt_symbol: str = ">"
    separator: str = "─"
    separator_style: str = "#4d4d4d"

    # Toolbar
    toolbar_bg: str = ""
    model_color: str = "#56d4e6"          # MindBot cyan (brand)
    cwd_color: str = "#666666"
    tip_color: str = "#555555"
    status_label_style: str = "#56d4e6 bold"
    thinking_active: str = "#56d4e6"       # ●
    thinking_idle: str = "#666666"          # ○

    # Tool blocks
    tool_success: str = "#56d364"           # green
    tool_running: str = "#f2cc60"           # yellow
    tool_error: str = "#ff7b72"             # red

    # Content
    error_style: str = "#ff7b72"
    user_style: str = "#56d4e6"
    ai_style: str = "#d4d4d4"
    dim_style: str = "#7c8594"

    # Toolbar line 2
    context_usage_style: str = "#555555"
    toast_style: str = "#7c8594"

    # Slash completion menu
    completion_separator: str = "#4a5568"
    completion_marker: str = "#4a5568"
    completion_marker_current: str = "#56d4e6"
    completion_command: str = "#a6adba"
    completion_meta: str = "#7c8594"
    completion_command_current: str = "#56d4e6 bold"
    completion_meta_current: str = "#56a4ff"

    # Welcome banner
    banner_border: str = "#56d4e6"
    banner_title: str = "#56d4e6 bold"
    banner_label: str = "#7c8594"
    banner_value: str = "#d4d4d4"
    banner_tip: str = "#555555"

    @staticmethod
    def dark() -> ShellTheme:
        return ShellTheme()

    @staticmethod
    def light() -> ShellTheme:
        return ShellTheme(
            separator_style="#d1d5db",
            model_color="#0e7490",
            cwd_color="#6b7280",
            tip_color="#9ca3af",
            status_label_style="#0e7490 bold",
            thinking_active="#0e7490",
            thinking_idle="#9ca3af",
            tool_success="#166534",
            tool_running="#92400e",
            tool_error="#dc2626",
            error_style="#dc2626",
            user_style="#0e7490",
            ai_style="#374151",
            dim_style="#6b7280",
            context_usage_style="#6b7280",
            toast_style="#6b7280",
            completion_separator="#d1d5db",
            completion_marker="#9ca3af",
            completion_marker_current="#0e7490",
            completion_command="#4b5563",
            completion_meta="#6b7280",
            completion_command_current="#0e7490 bold",
            completion_meta_current="#2563eb",
            banner_border="#0e7490",
            banner_title="#0e7490 bold",
            banner_label="#6b7280",
            banner_value="#374151",
            banner_tip="#9ca3af",
        )


def get_prompt_style(theme: ShellTheme | None = None) -> Style:
    """从主题获取 PromptSession Style（非全屏模式）。"""
    if theme is None:
        theme = _active_theme
    return Style.from_dict({
        "separator": theme.separator_style,
        "toolbar": f"bg:{theme.toolbar_bg}" if theme.toolbar_bg else "",
        "toolbar.model": f"{theme.model_color} bold",
        "toolbar.cwd": theme.cwd_color,
        "toolbar.tip": theme.tip_color,
        "toolbar.status": theme.status_label_style,
        "toolbar.thinking": theme.thinking_active,
        "toolbar.idle": theme.thinking_idle,
        "toolbar.context": theme.context_usage_style,
        "toolbar.toast": theme.toast_style,
        "input": f"{theme.model_color} bold",
        "input.separator": theme.separator_style,
        "thinking": theme.dim_style,
        "error": f"{theme.error_style} bold",
        "tool.running": theme.tool_running,
        "tool.success": theme.tool_success,
        "tool.error": theme.tool_error,
        "user": theme.user_style,
        "ai": theme.ai_style,
        "dim": theme.dim_style,
        "bottom-toolbar": "noreverse",
        "slash-completion-menu": "",
        "slash-completion-menu.separator": theme.completion_separator,
        "slash-completion-menu.marker": theme.completion_marker,
        "slash-completion-menu.marker.current": theme.completion_marker_current,
        "slash-completion-menu.command": theme.completion_command,
        "slash-completion-menu.meta": theme.completion_meta,
        "slash-completion-menu.command.current": theme.completion_command_current,
        "slash-completion-menu.meta.current": theme.completion_meta_current,
        "banner.title": theme.banner_title,
        "banner.border": theme.banner_border,
        "banner.label": theme.banner_label,
        "banner.value": theme.banner_value,
        "banner.tip": theme.banner_tip,
    })



# --- 全局主题状态 ---

_active_theme: ShellTheme = ShellTheme.dark()


def set_active_theme(name: ThemeName) -> None:
    global _active_theme
    match name:
        case "light":
            _active_theme = ShellTheme.light()
        case _:
            _active_theme = ShellTheme.dark()


def get_active_theme() -> ShellTheme:
    return _active_theme
