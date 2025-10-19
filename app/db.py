import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .config import DATABASE_PATH

_CONNECTION: Optional[sqlite3.Connection] = None


def _dict_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_connection() -> sqlite3.Connection:
    global _CONNECTION
    if _CONNECTION is None:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = _dict_factory
        conn.execute("PRAGMA foreign_keys = ON")
        _CONNECTION = conn
    return _CONNECTION


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def query(sql: str, params: Iterable[Any] | None = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(sql, tuple(params or []))
    return list(cur.fetchall())


def execute(sql: str, params: Iterable[Any] | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(sql, tuple(params or []))
    conn.commit()
    return cur.lastrowid


def init_db() -> None:
    conn = get_connection()
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    with schema_path.open("r", encoding="utf-8") as schema_file:
        conn.executescript(schema_file.read())
    conn.commit()


def ensure_default_admin() -> None:
    from . import auth

    existing = query("SELECT id FROM users WHERE username = ?", ("admin",))
    if existing:
        return
    password = "admin123"
    password_hash = auth.hash_password(password)
    execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
        ("admin", password_hash, datetime.utcnow().isoformat()),
    )
    print("Created default admin user 'admin' with password 'admin123'. Please change this after first login.")
