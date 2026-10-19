"""迁移窗口用的旧模板渲染器（不引入 Jinja2 依赖）。

旧 `templates/index.html` 只用到少量 Jinja 能力：flash 消息、`{% if username %}`、
变量替换与 `asset_v()`。新后端只需要在窗口期把旧页面原样吐出来，因此这里实现
一个**明确受限**的替换器：不执行任意模板代码，未识别的变量一律替换为空串。
Phase 5 删除旧页面时整块移除。
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Callable

_WITH_MESSAGES = re.compile(r"\{%\s*with messages.*?\{%\s*endwith\s*%\}", re.S)
_IF_USERNAME = re.compile(
    r"\{%\s*if username\s*%\}(.*?)\{%\s*else\s*%\}(.*?)\{%\s*endif\s*%\}", re.S
)
_IF_MESSAGES = re.compile(r"\{%\s*if messages\s*%\}.*?\{%\s*endif\s*%\}", re.S)
_VARIABLE = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.S)
_TAG = re.compile(r"\{%.*?%\}", re.S)
_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_ASSET_CALL = re.compile(r"asset_v\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _render_flash_toast(messages: list[tuple[str, str]]) -> str:
    if not messages:
        return ""
    items = "".join(
        f'<div class="flash-item flash-{html.escape(category)}">'
        f"{html.escape(message)}</div>"
        for category, message in messages
    )
    return f'<div id="flash-toast" class="flash-toast" role="alert">{items}</div>'


def render_legacy_index(
    template_path: str | Path,
    *,
    username: str | None = None,
    asset_v: Callable[[str], str] | None = None,
    arena_mode: str = "v2",
    arena_screen_list: str = "",
    messages: list[tuple[str, str]] | None = None,
) -> str:
    template = Path(template_path).read_text(encoding="utf-8")
    text = _COMMENT.sub("", template)
    # Flask's flash block is replaced by a server-rendered toast so the legacy
    # frontend's extractFlashMessages() sees the same #flash-toast/.flash-item
    # markup it has always parsed.
    text = _WITH_MESSAGES.sub(lambda match: _render_flash_toast(messages or []), text)
    text = _IF_MESSAGES.sub("", text)
    text = _IF_USERNAME.sub(lambda m: m.group(1) if username else m.group(2), text)

    def replace_variable(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        asset_match = _ASSET_CALL.fullmatch(expression)
        if asset_match:
            name = asset_match.group(1)
            return str(asset_v(name)) if asset_v else "0"
        if expression == "arena_screens.mode":
            return html.escape(arena_mode)
        if expression == "arena_screens.list":
            return html.escape(arena_screen_list)
        if expression.startswith("username|tojson"):
            return json.dumps(username)
        if expression.startswith("username|default"):
            return html.escape(username or "")
        if expression == "username":
            return html.escape(username or "")
        return ""

    text = _VARIABLE.sub(replace_variable, text)
    text = _TAG.sub("", text)
    return text
