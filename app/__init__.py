"""Top level package for the GP rota planner web application.

The project intentionally avoids a heavyweight framework, so exposing the
WSGI entry point from ``app.main`` via ``__init__`` makes it easier for tools
and readers to discover how to launch the service.  Keeping this wiring in a
single place also mirrors how frameworks such as Flask surface their
``create_app`` helpers.
"""

from __future__ import annotations

from typing import Callable

from .main import application as wsgi_application
from .main import ensure_initialized, main

__all__ = [
    "create_app",
    "ensure_initialized",
    "main",
    "wsgi_application",
]


def create_app() -> Callable:
    """Return the fully initialised WSGI application.

    When embedding the rota planner inside another service (for example a
    larger practice intranet), callers can import ``app.create_app`` to obtain
    the WSGI callable.  The helper ensures the database schema exists before
    handing the application back to the caller so that the behaviour matches
    the ``python -m app.main`` entry point.
    """

    ensure_initialized()
    return wsgi_application
