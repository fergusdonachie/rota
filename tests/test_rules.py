from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest


def reload_app_modules(tmp_path):
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    db_path = tmp_path / "test_rota.sqlite3"
    os.environ["ROTA_DATABASE_PATH"] = str(db_path)
    for module in ["app.config", "app.db", "app.views"]:
        if module in sys.modules:
            del sys.modules[module]
    import app.config  # noqa: F401
    import app.db
    import app.views

    importlib.reload(app.config)
    importlib.reload(app.db)
    importlib.reload(app.views)
    app.db.init_db()
    return app.db, app.views


@pytest.fixture()
def app_context(tmp_path):
    db, views = reload_app_modules(tmp_path)
    return db, views


def test_day_requirement_violation(app_context):
    db, views = app_context
    now = datetime.utcnow().isoformat()
    session_type_id = db.execute(
        "INSERT INTO session_types (name, created_at) VALUES (?, ?)",
        ("Morning", now),
    )
    clinician_id = db.execute(
        "INSERT INTO clinicians (full_name, role, created_at) VALUES (?, ?, ?)",
        ("Dr. A", "Doctor", now),
    )
    session_id = db.execute(
        "INSERT INTO rota_sessions (day_of_week, session_type_id, start_time, end_time, created_at) VALUES (?, ?, ?, ?, ?)",
        (0, session_type_id, "09:00", "12:00", now),
    )
    db.execute(
        "INSERT INTO session_assignments (session_id, clinician_id) VALUES (?, ?)",
        (session_id, clinician_id),
    )
    db.execute(
        "INSERT INTO day_requirements (day_of_week, role, min_count, created_at) VALUES (?, ?, ?, ?)",
        (0, "Doctor", 2, now),
    )
    messages = views.evaluate_rules()
    assert any("needs at least" in message for message in messages)


def test_clinician_requirement_satisfied(app_context):
    db, views = app_context
    now = datetime.utcnow().isoformat()
    session_type_id = db.execute(
        "INSERT INTO session_types (name, created_at) VALUES (?, ?)",
        ("Tutorial", now),
    )
    clinician_id = db.execute(
        "INSERT INTO clinicians (full_name, role, created_at) VALUES (?, ?, ?)",
        ("Dr. Tutor", "Doctor", now),
    )
    for idx in range(2):
        session_id = db.execute(
            "INSERT INTO rota_sessions (day_of_week, session_type_id, start_time, end_time, created_at) VALUES (?, ?, ?, ?, ?)",
            (idx, session_type_id, "09:00", "10:00", now),
        )
        db.execute(
            "INSERT INTO session_assignments (session_id, clinician_id) VALUES (?, ?)",
            (session_id, clinician_id),
        )
    db.execute(
        "INSERT INTO clinician_requirements (clinician_id, session_type_id, min_sessions, created_at) VALUES (?, ?, ?, ?)",
        (clinician_id, session_type_id, 2, now),
    )
    messages = views.evaluate_rules()
    assert not any("Clinician requirement unmet" in message for message in messages)
