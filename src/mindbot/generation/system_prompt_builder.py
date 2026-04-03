"""Helpers for assembling runtime-aware system prompts."""

from __future__ import annotations

from collections.abc import Iterable


def build_system_prompt(
    *,
    base_prompt: str = "",
    tool_names: Iterable[str] = (),
) -> str:
    """Build a concise system prompt aligned with the current tool set."""
    visible_tools = sorted(set(tool_names))
    has_create_tool = "create_tool" in visible_tools

    sections = [
        base_prompt.strip() or "你是 MindBot，一个可调用工具并可逐步扩展能力的 AI 助手。",
        "## 当前可用能力",
    ]

    if visible_tools:
        sections.extend(f"- `{name}`" for name in visible_tools)
    else:
        sections.append("- 当前未挂载任何工具。")

    sections.extend(
        [
            "",
            "## 工具使用原则",
            "- 优先复用现有工具，只有在确实缺少能力时再考虑创建新工具。",
            "- 调用工具前先明确目标和参数，避免无意义重复调用。",
            "- 文件和命令类工具必须保持在允许的工作区范围内。",
        ]
    )

    if has_create_tool:
        sections.extend(
            [
                "",
                "## 动态工具创建",
                "- `create_tool` 用于把稳定、可复用的流程沉淀为新工具。",
                "- 新创建的工具会在刷新后进入下一轮对话可用范围。",
                "- 优先生成清晰的工具名、准确的描述和最小必要参数。",
            ]
        )

    return "\n".join(sections).strip()
