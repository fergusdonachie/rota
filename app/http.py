from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs
from datetime import datetime


@dataclass
class Request:
    environ: Dict[str, Any]
    method: str = field(init=False)
    path: str = field(init=False)
    query_params: Dict[str, List[str]] = field(init=False)
    form_data: Dict[str, List[str]] = field(init=False)
    cookies: Dict[str, str] = field(init=False)
    user: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.method = self.environ.get("REQUEST_METHOD", "GET").upper()
        raw_path = self.environ.get("PATH_INFO", "/")
        self.path = raw_path.rstrip("/") or "/"
        self.query_params = parse_qs(self.environ.get("QUERY_STRING", ""))
        self.form_data = {}
        if self.method in {"POST", "PUT", "PATCH"}:
            length = int(self.environ.get("CONTENT_LENGTH") or 0)
            body = self.environ.get("wsgi.input").read(length) if length > 0 else b""
            content_type = self.environ.get("CONTENT_TYPE", "")
            if "application/json" in content_type:
                try:
                    data = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    data = {}
                self.form_data = {k: [v] if not isinstance(v, list) else v for k, v in data.items()}
            else:
                self.form_data = parse_qs(body.decode("utf-8"))
        self.cookies = {}
        raw_cookie = self.environ.get("HTTP_COOKIE", "")
        for fragment in raw_cookie.split(";"):
            if "=" in fragment:
                key, value = fragment.strip().split("=", 1)
                self.cookies[key] = value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        values = self.query_params.get(key) or self.form_data.get(key)
        if not values:
            return default
        return values[0]

    def getlist(self, key: str) -> List[str]:
        if key in self.form_data:
            return self.form_data[key]
        if key in self.query_params:
            return self.query_params[key]
        return []



@dataclass
class Response:
    body: bytes
    status: HTTPStatus = HTTPStatus.OK
    headers: List[Tuple[str, str]] = field(default_factory=list)

    def add_header(self, name: str, value: str) -> "Response":
        self.headers.append((name, value))
        return self

    def set_cookie(
        self,
        name: str,
        value: str,
        expires: Optional[datetime] = None,
        path: str = "/",
        http_only: bool = True,
    ) -> "Response":
        parts = [f"{name}={value}"]
        if expires is not None:
            parts.append("Expires=" + expires.strftime("%a, %d %b %Y %H:%M:%S GMT"))
        if path:
            parts.append(f"Path={path}")
        if http_only:
            parts.append("HttpOnly")
        self.headers.append(("Set-Cookie", "; ".join(parts)))
        return self

    @classmethod
    def html(
        cls,
        content: str,
        status: HTTPStatus = HTTPStatus.OK,
        headers: Optional[Iterable[Tuple[str, str]]] = None,
    ) -> "Response":
        merged_headers = [("Content-Type", "text/html; charset=utf-8")]
        if headers:
            merged_headers.extend(headers)
        return cls(content.encode("utf-8"), status=status, headers=list(merged_headers))

    @classmethod
    def redirect(
        cls,
        location: str,
        headers: Optional[Iterable[Tuple[str, str]]] = None,
    ) -> "Response":
        header_list = [("Location", location)]
        if headers:
            header_list.extend(headers)
        return cls(b"", status=HTTPStatus.FOUND, headers=header_list)


def escape(value: Any) -> str:
    return html.escape(str(value))
