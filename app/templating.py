from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from .config import BASE_DIR


TEMPLATES_DIR = BASE_DIR / "app" / "templates"


def render_template(name: str, **context: Any) -> str:
    template_path = TEMPLATES_DIR / name
    if not template_path.is_file():
        raise FileNotFoundError(f"Template '{name}' not found")
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.safe_substitute(**context)
