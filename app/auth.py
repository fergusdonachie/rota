from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from . import db
from .config import SECRET_KEY, SESSION_COOKIE_NAME, SESSION_DURATION_SECONDS


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    check = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(check, digest)


def _sign_session(session_id: str) -> str:
    signature = hmac.new(SECRET_KEY.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{session_id}|{signature}"


def _unsign_session(cookie_value: str) -> Optional[str]:
    try:
        session_id, signature = cookie_value.split("|", 1)
    except ValueError:
        return None
    expected = hmac.new(SECRET_KEY.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(signature, expected):
        return session_id
    return None


def create_session(user_id: int) -> Dict[str, str]:
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(seconds=SESSION_DURATION_SECONDS)
    db.execute(
        "INSERT INTO user_sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
        (session_id, user_id, expires_at.isoformat()),
    )
    cookie_value = _sign_session(session_id)
    return {
        "name": SESSION_COOKIE_NAME,
        "value": cookie_value,
        "expires": expires_at,
    }


def destroy_session(session_id: str) -> None:
    db.execute("DELETE FROM user_sessions WHERE id = ?", (session_id,))

def unsign_session(cookie_value: str) -> Optional[str]:
    return _unsign_session(cookie_value)


def get_user_from_request(request: "Request") -> Optional[Dict[str, object]]:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        return None
    session_id = _unsign_session(cookie_value)
    if not session_id:
        return None
    now = datetime.utcnow()
    records = db.query(
        "SELECT user_sessions.id as session_id, user_sessions.expires_at, users.* FROM user_sessions JOIN users ON users.id = user_sessions.user_id WHERE user_sessions.id = ?",
        (session_id,),
    )
    if not records:
        return None
    record = records[0]
    try:
        expires_at = datetime.fromisoformat(record["expires_at"])
    except KeyError:
        expires_at = now
    if expires_at < now:
        destroy_session(session_id)
        return None
    request.session_id = session_id
    return record


class AuthenticationError(Exception):
    pass


def require_login(request: "Request") -> Dict[str, object]:
    user = get_user_from_request(request)
    if user is None:
        raise AuthenticationError("Authentication required")
    return user
