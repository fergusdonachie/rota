from __future__ import annotations

from http import HTTPStatus
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Pattern, Tuple

from .config import BASE_DIR
from .http import Request, Response


Handler = Callable[[Request, Dict[str, str]], Response]


@dataclass
class Route:
    pattern: Pattern[str]
    methods: Tuple[str, ...]
    handler: Handler


class Router:
    def __init__(self) -> None:
        self.routes: List[Route] = []
        self.static_root = BASE_DIR / "app" / "static"

    def add_route(self, path: str, handler: Handler, methods: Iterable[str] = ("GET",)) -> None:
        regex_path = self._build_regex(path)
        route = Route(pattern=re.compile(regex_path), methods=tuple(m.upper() for m in methods), handler=handler)
        self.routes.append(route)


    def _build_regex(self, path: str) -> str:
        pattern = path.rstrip("/") or "/"
        if pattern == "/":
            return r"^/$"

        segments = [segment for segment in pattern.strip("/").split("/") if segment]
        regex_parts: List[str] = []
        for segment in segments:
            if segment.startswith("<") and segment.endswith(">"):
                inner = segment[1:-1]
                if ":" in inner:
                    type_name, name = inner.split(":", 1)
                else:
                    type_name, name = "str", inner
                if type_name == "int":
                    regex_parts.append(f"(?P<{name}>\d+)")
                else:
                    regex_parts.append(f"(?P<{name}>[^/]+)")
            else:
                regex_parts.append(re.escape(segment))
        regex = "/".join(regex_parts)
        if path.startswith("/"):
            regex = "/" + regex
        return f"^{regex}$"

    def dispatch(self, request: Request) -> Response:
        if request.path.startswith("/static/"):
            return self.serve_static(request.path)
        for route in self.routes:
            match = route.pattern.match(request.path)
            if match and request.method in route.methods:
                return route.handler(request, match.groupdict())
        return Response.html("<h1>404 Not Found</h1>", status=HTTPStatus.NOT_FOUND)

    def serve_static(self, path: str) -> Response:
        relative = path[len("/static/") :]
        file_path = self.static_root / relative
        if not file_path.is_file():
            return Response.html("<h1>404 Not Found</h1>", status=HTTPStatus.NOT_FOUND)
        content = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(file_path))
        headers = [("Content-Type", content_type or "application/octet-stream")]
        return Response(content, headers=headers)


def not_found(_: Request, __: Dict[str, str]) -> Response:
    return Response.html("<h1>404 Not Found</h1>", status=HTTPStatus.NOT_FOUND)
