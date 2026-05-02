"""自定义键绑定。"""

from __future__ import annotations

import subprocess
import tempfile
import os

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


def create_key_bindings() -> KeyBindings:
    """创建 MindBot shell 的键绑定。

    键绑定列表：
        Alt+Enter / Ctrl+J  多行输入换行
        Ctrl+O              打开外部编辑器
        Ctrl+V              粘贴剪贴板
    """
    kb = KeyBindings()

    @kb.add("escape", "enter", eager=True)
    @kb.add("c-j", eager=True)
    def _insert_newline(event):
        """Alt+Enter / Ctrl+J: 多行输入换行。"""
        event.current_buffer.insert_text("\n")

    @kb.add("c-o", eager=True)
    def _open_editor(event):
        """Ctrl+O: 打开外部编辑器。"""
        editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
        buffer = event.current_buffer

        # 将当前内容写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(buffer.text)
            tmp_path = f.name

        try:
            # 暂停 prompt_toolkit 的 raw 模式，运行编辑器
            event.app.suspend()
            try:
                subprocess.run([editor, tmp_path], check=False)
            finally:
                event.app.resume()

            # 读回编辑后的内容
            with open(tmp_path, encoding="utf-8") as f:
                new_text = f.read()
            buffer.text = new_text
            buffer.cursor_position = len(new_text)
        finally:
            os.unlink(tmp_path)

    @kb.add("c-v", eager=True)
    def _paste_clipboard(event):
        """Ctrl+V: 粘贴剪贴板内容。"""
        try:
            import subprocess as sp

            # macOS: pbpaste, Linux: xclip
            if os.path.exists("/usr/bin/pbpaste"):
                result = sp.run(["pbpaste"], capture_output=True, text=True, check=False)
            elif os.path.exists("/usr/bin/xclip"):
                result = sp.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    capture_output=True, text=True, check=False,
                )
            else:
                return
            if result.stdout:
                event.current_buffer.insert_text(result.stdout)
        except Exception:
            pass

    return kb
