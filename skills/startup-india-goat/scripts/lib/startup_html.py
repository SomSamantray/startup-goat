"""HTML view for startup reports, sharing the generic renderer's sanitizer."""
from __future__ import annotations

import html
from typing import Any

from . import html_render
from .startup_render import render_markdown
from .startup_schema import GroupProfile, StartupProfile


def render_html(value: StartupProfile | GroupProfile, **kwargs: Any) -> str:
    markdown = render_markdown(value, **kwargs)
    # _markdown_to_html is the established implementation: it escapes text,
    # rejects unsafe URL schemes, and adds noopener noreferrer to links.
    body = html_render._markdown_to_html(markdown)
    title = value.identity.display_name if isinstance(value, StartupProfile) else "Startup India GOAT comparison"
    return "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>" + html.escape(title) + " · Startup India GOAT</title><style>" + html_render.CSS + "</style></head><body>" + body + "</body></html>"

render_startup_html = render_html

__all__ = ["render_html", "render_startup_html"]
