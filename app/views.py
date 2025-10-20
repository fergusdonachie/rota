from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Dict, List, Tuple

from . import auth, db
from .config import SESSION_COOKIE_NAME
from .http import Request, Response, escape
from .templating import render_template


NAV_LINKS: Tuple[Tuple[str, str], ...] = (
    ("Dashboard", "/"),
    ("Clinicians", "/clinicians"),
    ("Session types", "/session-types"),
    ("Sessions", "/sessions"),
    ("Day requirements", "/rules/day"),
    ("Clinician requirements", "/rules/clinician"),
    ("Validate rota", "/validate"),
)


Message = Tuple[str, str]


def build_navigation(request: Request) -> str:
    if not request.user:
        return '<a href="/login">Log in</a>'
    links = [f'<a href="{escape(url)}">{escape(label)}</a>' for label, url in NAV_LINKS]
    links.append('<a href="/logout">Log out</a>')
    return " ".join(links)


def render_page(request: Request, title: str, content: str, messages: List[Message] | None = None) -> Response:
    user_info = ""
    if request.user:
        username = escape(request.user.get("username", ""))
        user_info = f"Signed in as <strong>{username}</strong>"
    else:
        user_info = '<a href="/login">Log in</a>'
    nav = build_navigation(request)
    message_html = ""
    for level, text in messages or []:
        message_html += f'<div class="alert {escape(level)}">{escape(text)}</div>'
    html = render_template(
        "base.html",
        title=escape(title),
        user_info=user_info,
        navigation=nav,
        messages=message_html,
        content=content,
        year=datetime.utcnow().year,
    )
    return Response.html(html)


def login_view(request: Request, _: Dict[str, str]) -> Response:
    if request.method == "POST":
        username = request.get("username", "").strip()
        password = request.get("password", "")
        user_rows = db.query("SELECT * FROM users WHERE username = ?", (username,))
        if not user_rows or not auth.verify_password(password, user_rows[0]["password_hash"]):
            form = _login_form(username, error="Invalid credentials. Please try again.")
            return render_page(request, "Sign in", form, messages=[("error", "Invalid username or password")])
        user = user_rows[0]
        cookie = auth.create_session(user["id"])
        response = Response.redirect("/")
        response.set_cookie(cookie["name"], cookie["value"], expires=cookie["expires"])
        return response
    if request.user:
        return Response.redirect("/")
    form = _login_form("")
    return render_page(request, "Sign in", form)


def _login_form(username: str, error: str | None = None) -> str:
    error_html = f'<div class="alert error">{escape(error)}</div>' if error else ""
    return f"""
    <div class=\"card\">
        <h2>Sign in</h2>
        {error_html}
        <form method=\"post\">
            <label for=\"username\">Username</label>
            <input id=\"username\" name=\"username\" type=\"text\" value=\"{escape(username)}\" required>
            <label for=\"password\">Password</label>
            <input id=\"password\" name=\"password\" type=\"password\" required>
            <button type=\"submit\">Sign in</button>
        </form>
    </div>
    """


def logout_view(request: Request, _: Dict[str, str]) -> Response:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_value:
        session_id = auth.unsign_session(cookie_value)  # type: ignore[attr-defined]
        if session_id:
            auth.destroy_session(session_id)
    response = Response.redirect("/login")
    response.set_cookie(SESSION_COOKIE_NAME, "", expires=datetime.utcnow() - timedelta(days=1))
    return response


def dashboard(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    clinician_count = db.query("SELECT COUNT(*) as count FROM clinicians")[0]["count"]
    session_count = db.query("SELECT COUNT(*) as count FROM rota_sessions")[0]["count"]
    pending_rules = evaluate_rules()
    rows = "".join(
        f"<li>{escape(result)}</li>" for result in pending_rules
    ) or "<li>All rules currently satisfied.</li>"
    content = f"""
    <div class=\"card\">
        <h2>Overview</h2>
        <p>Clinicians registered: <strong>{clinician_count}</strong></p>
        <p>Sessions configured: <strong>{session_count}</strong></p>
    </div>
    <div class=\"card\">
        <h2>Rule summary</h2>
        <ul>{rows}</ul>
        <p><a href=\"/validate\">Run full validation</a></p>
    </div>
    """
    return render_page(request, "Dashboard", content)


def list_clinicians(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    clinicians = db.query("SELECT * FROM clinicians ORDER BY full_name")
    rows = "".join(
        f"<tr><td>{escape(c['full_name'])}</td><td>{escape(c['role'])}</td><td>{escape(c.get('email','') or '')}</td>"
        f"<td class=\"actions\"><a href='/clinicians/{c['id']}/edit'>Edit</a></td></tr>"
        for c in clinicians
    ) or "<tr><td colspan='4'>No clinicians configured yet.</td></tr>"
    content = f"""
    <div class=\"card\">
        <div class=\"actions\"><a href=\"/clinicians/new\">Add clinician</a></div>
        <table>
            <thead><tr><th>Name</th><th>Role</th><th>Email</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """
    return render_page(request, "Clinicians", content)


def clinician_form(request: Request, params: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    clinician = {"full_name": "", "role": "", "email": "", "notes": ""}
    clinician_id = params.get("id")
    if clinician_id:
        existing = db.query("SELECT * FROM clinicians WHERE id = ?", (int(clinician_id),))
        if not existing:
            return Response.redirect("/clinicians")
        clinician = existing[0]
    if request.method == "POST":
        full_name = request.get("full_name", "").strip()
        role = request.get("role", "").strip()
        email = request.get("email", "").strip()
        notes = request.get("notes", "").strip()
        now = datetime.utcnow().isoformat()
        if not full_name or not role:
            return render_page(
                request,
                "Clinician",
                _clinician_form_html(clinician, error="Name and role are required."),
                messages=[("error", "Please provide both a name and role.")],
            )
        if clinician_id:
            db.execute(
                "UPDATE clinicians SET full_name = ?, role = ?, email = ?, notes = ?, updated_at = ? WHERE id = ?",
                (full_name, role, email, notes, now, int(clinician_id)),
            )
        else:
            db.execute(
                "INSERT INTO clinicians (full_name, role, email, notes, created_at) VALUES (?, ?, ?, ?, ?)",
                (full_name, role, email, notes, now),
            )
        return Response.redirect("/clinicians")
    return render_page(request, "Clinician", _clinician_form_html(clinician))


def _clinician_form_html(clinician: Dict[str, object], error: str | None = None) -> str:
    error_html = f'<div class="alert error">{escape(error)}</div>' if error else ""
    return f"""
    <div class=\"card\">
        <form method=\"post\">
            {error_html}
            <label for=\"full_name\">Full name</label>
            <input id=\"full_name\" name=\"full_name\" type=\"text\" value=\"{escape(clinician.get('full_name',''))}\" required>
            <label for=\"role\">Role</label>
            <input id=\"role\" name=\"role\" type=\"text\" value=\"{escape(clinician.get('role',''))}\" required>
            <label for=\"email\">Email</label>
            <input id=\"email\" name=\"email\" type=\"email\" value=\"{escape(clinician.get('email','') or '')}\">
            <label for=\"notes\">Notes</label>
            <textarea id=\"notes\" name=\"notes\">{escape(clinician.get('notes','') or '')}</textarea>
            <button type=\"submit\">Save</button>
            <a class=\"button secondary\" href=\"/clinicians\">Cancel</a>
        </form>
    </div>
    """


def list_session_types(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    session_types = db.query("SELECT * FROM session_types ORDER BY name")
    rows = "".join(
        f"<tr><td>{escape(t['name'])}</td><td>{escape(t.get('description','') or '')}</td>"
        f"<td class=\"actions\"><a href='/session-types/{t['id']}/edit'>Edit</a></td></tr>"
        for t in session_types
    ) or "<tr><td colspan='3'>No session types defined yet.</td></tr>"
    content = f"""
    <div class=\"card\">
        <div class=\"actions\"><a href=\"/session-types/new\">Add session type</a></div>
        <table>
            <thead><tr><th>Name</th><th>Description</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """
    return render_page(request, "Session types", content)


def session_type_form(request: Request, params: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    session_type = {"name": "", "description": "", "default_start": "", "default_end": ""}
    type_id = params.get("id")
    if type_id:
        existing = db.query("SELECT * FROM session_types WHERE id = ?", (int(type_id),))
        if not existing:
            return Response.redirect("/session-types")
        session_type = existing[0]
    if request.method == "POST":
        name = request.get("name", "").strip()
        description = request.get("description", "").strip()
        default_start = request.get("default_start", "").strip()
        default_end = request.get("default_end", "").strip()
        now = datetime.utcnow().isoformat()
        if not name:
            return render_page(
                request,
                "Session type",
                _session_type_form_html(session_type, error="Name is required."),
                messages=[("error", "Session type name cannot be empty.")],
            )
        if type_id:
            db.execute(
                "UPDATE session_types SET name = ?, description = ?, default_start = ?, default_end = ?, updated_at = ? WHERE id = ?",
                (name, description, default_start, default_end, now, int(type_id)),
            )
        else:
            db.execute(
                "INSERT INTO session_types (name, description, default_start, default_end, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, description, default_start, default_end, now),
            )
        return Response.redirect("/session-types")
    return render_page(request, "Session type", _session_type_form_html(session_type))


def _session_type_form_html(session_type: Dict[str, object], error: str | None = None) -> str:
    error_html = f'<div class="alert error">{escape(error)}</div>' if error else ""
    return f"""
    <div class=\"card\">
        <form method=\"post\">
            {error_html}
            <label for=\"name\">Name</label>
            <input id=\"name\" name=\"name\" type=\"text\" value=\"{escape(session_type.get('name',''))}\" required>
            <label for=\"description\">Description</label>
            <textarea id=\"description\" name=\"description\">{escape(session_type.get('description','') or '')}</textarea>
            <label for=\"default_start\">Default start time</label>
            <input id=\"default_start\" name=\"default_start\" type=\"text\" value=\"{escape(session_type.get('default_start','') or '')}\" placeholder=\"09:00\">
            <label for=\"default_end\">Default end time</label>
            <input id=\"default_end\" name=\"default_end\" type=\"text\" value=\"{escape(session_type.get('default_end','') or '')}\" placeholder=\"13:00\">
            <button type=\"submit\">Save</button>
            <a class=\"button secondary\" href=\"/session-types\">Cancel</a>
        </form>
    </div>
    """


def list_sessions(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    sessions = db.query(
        """
        SELECT rota_sessions.*, session_types.name AS session_type_name
        FROM rota_sessions
        JOIN session_types ON session_types.id = rota_sessions.session_type_id
        ORDER BY day_of_week, start_time
        """
    )
    assignments = db.query(
        """
        SELECT session_assignments.session_id, clinicians.full_name
        FROM session_assignments
        JOIN clinicians ON clinicians.id = session_assignments.clinician_id
        """
    )
    assigned_map: Dict[int, List[str]] = defaultdict(list)
    for row in assignments:
        assigned_map[row["session_id"]].append(row["full_name"])
    rows = "".join(
        f"<tr><td>{_day_label(s['day_of_week'])}</td><td>{escape(s['session_type_name'])}</td>"
        f"<td>{escape(s['start_time'])} - {escape(s['end_time'])}</td>"
        f"<td>{escape(', '.join(assigned_map.get(s['id'], [])) or 'Unassigned')}</td>"
        f"<td class=\"actions\"><a href='/sessions/{s['id']}/edit'>Edit</a></td></tr>"
        for s in sessions
    ) or "<tr><td colspan='5'>No sessions defined yet.</td></tr>"
    content = f"""
    <div class=\"card\">
        <div class=\"actions\"><a href=\"/sessions/new\">Add session</a></div>
        <table>
            <thead><tr><th>Day</th><th>Type</th><th>Time</th><th>Clinicians</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """
    return render_page(request, "Sessions", content)


def session_form(request: Request, params: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    session = {"day_of_week": 0, "session_type_id": "", "start_time": "", "end_time": "", "location": ""}
    session_id = params.get("id")
    if session_id:
        existing = db.query("SELECT * FROM rota_sessions WHERE id = ?", (int(session_id),))
        if not existing:
            return Response.redirect("/sessions")
        session = existing[0]
    session_types = db.query("SELECT id, name FROM session_types ORDER BY name")
    clinicians = db.query("SELECT id, full_name FROM clinicians ORDER BY full_name")
    selected_clinicians = set()
    if session_id:
        rows = db.query("SELECT clinician_id FROM session_assignments WHERE session_id = ?", (int(session_id),))
        selected_clinicians = {row["clinician_id"] for row in rows}
    if request.method == "POST":
        day_of_week = int(request.get("day_of_week", "0"))
        session_type_id = int(request.get("session_type_id", "0"))
        start_time = request.get("start_time", "").strip()
        end_time = request.get("end_time", "").strip()
        location = request.get("location", "").strip()
        clinician_ids = {int(cid) for cid in request.getlist("clinicians") if cid}
        now = datetime.utcnow().isoformat()
        if not start_time or not end_time:
            form_html = _session_form_html(session, session_types, clinicians, selected_clinicians, "Start and end times are required.")
            return render_page(request, "Session", form_html, messages=[("error", "Please provide session times.")])
        if session_id:
            db.execute(
                "UPDATE rota_sessions SET day_of_week = ?, session_type_id = ?, start_time = ?, end_time = ?, location = ?, updated_at = ? WHERE id = ?",
                (day_of_week, session_type_id, start_time, end_time, location, now, int(session_id)),
            )
            db.execute("DELETE FROM session_assignments WHERE session_id = ?", (int(session_id),))
            session_db_id = int(session_id)
        else:
            session_db_id = db.execute(
                "INSERT INTO rota_sessions (day_of_week, session_type_id, start_time, end_time, location, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (day_of_week, session_type_id, start_time, end_time, location, now),
            )
        for clinician_id in clinician_ids:
            db.execute(
                "INSERT OR IGNORE INTO session_assignments (session_id, clinician_id) VALUES (?, ?)",
                (session_db_id, clinician_id),
            )
        return Response.redirect("/sessions")
    form_html = _session_form_html(session, session_types, clinicians, selected_clinicians)
    return render_page(request, "Session", form_html)


def _session_form_html(session: Dict[str, object], session_types: List[Dict[str, object]], clinicians: List[Dict[str, object]], selected: set[int], error: str | None = None) -> str:
    error_html = f'<div class="alert error">{escape(error)}</div>' if error else ""
    options = "".join(
        f"<option value='{stype['id']}' {'selected' if session.get('session_type_id') == stype['id'] else ''}>{escape(stype['name'])}</option>"
        for stype in session_types
    ) or "<option value=''>Create a session type first</option>"
    clinician_options = "".join(
        f"<label><input type='checkbox' name='clinicians' value='{c['id']}' {'checked' if c['id'] in selected else ''}> {escape(c['full_name'])}</label><br>"
        for c in clinicians
    ) or "<p>Add clinicians before assigning sessions.</p>"
    day_options = "".join(
        f"<option value='{idx}' {'selected' if session.get('day_of_week') == idx else ''}>{escape(_day_label(idx))}</option>"
        for idx in range(7)
    )
    return f"""
    <div class=\"card\">
        <form method=\"post\">
            {error_html}
            <label for=\"day_of_week\">Day of week</label>
            <select id=\"day_of_week\" name=\"day_of_week\">{day_options}</select>
            <label for=\"session_type_id\">Session type</label>
            <select id=\"session_type_id\" name=\"session_type_id\">{options}</select>
            <label for=\"start_time\">Start time</label>
            <input id=\"start_time\" name=\"start_time\" type=\"text\" value=\"{escape(session.get('start_time','') or '')}\" placeholder=\"09:00\">
            <label for=\"end_time\">End time</label>
            <input id=\"end_time\" name=\"end_time\" type=\"text\" value=\"{escape(session.get('end_time','') or '')}\" placeholder=\"13:00\">
            <label for=\"location\">Location</label>
            <input id=\"location\" name=\"location\" type=\"text\" value=\"{escape(session.get('location','') or '')}\">
            <fieldset>
                <legend>Assigned clinicians</legend>
                {clinician_options}
            </fieldset>
            <button type=\"submit\">Save</button>
            <a class=\"button secondary\" href=\"/sessions\">Cancel</a>
        </form>
    </div>
    """


def list_day_requirements(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    rows = db.query(
        """
        SELECT day_requirements.*, session_types.name AS session_type_name
        FROM day_requirements
        LEFT JOIN session_types ON session_types.id = day_requirements.session_type_id
        ORDER BY day_of_week
        """
    )
    table_rows = "".join(
        f"<tr><td>{escape(_day_label(r['day_of_week']))}</td><td>{escape(r['session_type_name'] or 'Any')}</td>"
        f"<td>{escape(r['role'] or 'Any')}</td><td>{escape(r['min_count'])}</td>"
        f"<td>{escape(r['notes'] or '')}</td><td class=\"actions\"><a href='/rules/day/{r['id']}/edit'>Edit</a></td></tr>"
        for r in rows
    ) or "<tr><td colspan='6'>No day requirements defined yet.</td></tr>"
    content = f"""
    <div class=\"card\">
        <div class=\"actions\"><a href=\"/rules/day/new\">Add day requirement</a></div>
        <table>
            <thead><tr><th>Day</th><th>Session type</th><th>Role</th><th>Minimum</th><th>Notes</th><th></th></tr></thead>
            <tbody>{table_rows}</tbody>
        </table>
    </div>
    """
    return render_page(request, "Day requirements", content)


def day_requirement_form(request: Request, params: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    requirement = {"day_of_week": 0, "session_type_id": "", "role": "", "min_count": 1, "notes": ""}
    req_id = params.get("id")
    if req_id:
        existing = db.query("SELECT * FROM day_requirements WHERE id = ?", (int(req_id),))
        if not existing:
            return Response.redirect("/rules/day")
        requirement = existing[0]
    session_types = db.query("SELECT id, name FROM session_types ORDER BY name")
    if request.method == "POST":
        day_of_week = int(request.get("day_of_week", "0"))
        session_type_id_raw = request.get("session_type_id", "")
        session_type_id = int(session_type_id_raw) if session_type_id_raw else None
        role = request.get("role", "").strip() or None
        min_count = int(request.get("min_count", "1"))
        notes = request.get("notes", "").strip()
        now = datetime.utcnow().isoformat()
        if min_count < 1:
            form_html = _day_requirement_form_html(requirement, session_types, "Minimum must be at least 1.")
            return render_page(request, "Day requirement", form_html, messages=[("error", "Minimum must be at least 1")])
        if req_id:
            db.execute(
                "UPDATE day_requirements SET day_of_week = ?, session_type_id = ?, role = ?, min_count = ?, notes = ? WHERE id = ?",
                (day_of_week, session_type_id, role, min_count, notes, int(req_id)),
            )
        else:
            db.execute(
                "INSERT INTO day_requirements (day_of_week, session_type_id, role, min_count, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (day_of_week, session_type_id, role, min_count, notes, now),
            )
        return Response.redirect("/rules/day")
    form_html = _day_requirement_form_html(requirement, session_types)
    return render_page(request, "Day requirement", form_html)


def _day_requirement_form_html(requirement: Dict[str, object], session_types: List[Dict[str, object]], error: str | None = None) -> str:
    error_html = f'<div class="alert error">{escape(error)}</div>' if error else ""
    type_options = "<option value=''>Any</option>" + "".join(
        f"<option value='{stype['id']}' {'selected' if requirement.get('session_type_id') == stype['id'] else ''}>{escape(stype['name'])}</option>"
        for stype in session_types
    )
    day_options = "".join(
        f"<option value='{idx}' {'selected' if requirement.get('day_of_week') == idx else ''}>{escape(_day_label(idx))}</option>"
        for idx in range(7)
    )
    role_value = escape(requirement.get('role', '') or '')
    min_value = escape(requirement.get('min_count', 1))
    notes_value = escape(requirement.get('notes', '') or '')
    return f"""
    <div class=\"card\">
        <form method=\"post\">
            {error_html}
            <label for=\"day_of_week\">Day of week</label>
            <select id=\"day_of_week\" name=\"day_of_week\">{day_options}</select>
            <label for=\"session_type_id\">Session type</label>
            <select id=\"session_type_id\" name=\"session_type_id\">{type_options}</select>
            <label for=\"role\">Role</label>
            <input id=\"role\" name=\"role\" type=\"text\" value=\"{role_value}\" placeholder=\"Any\">
            <label for=\"min_count\">Minimum clinicians</label>
            <input id=\"min_count\" name=\"min_count\" type=\"number\" min=\"1\" value=\"{min_value}\">
            <label for=\"notes\">Notes</label>
            <textarea id=\"notes\" name=\"notes\">{notes_value}</textarea>
            <button type=\"submit\">Save</button>
            <a class=\"button secondary\" href=\"/rules/day\">Cancel</a>
        </form>
    </div>
    """


def list_clinician_requirements(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    rows = db.query(
        """
        SELECT clinician_requirements.*, clinicians.full_name, session_types.name AS session_type_name
        FROM clinician_requirements
        JOIN clinicians ON clinicians.id = clinician_requirements.clinician_id
        LEFT JOIN session_types ON session_types.id = clinician_requirements.session_type_id
        ORDER BY clinicians.full_name
        """
    )
    table_rows = "".join(
        f"<tr><td>{escape(r['full_name'])}</td><td>{escape(r['session_type_name'] or 'Any')}</td>"
        f"<td>{escape(r['min_sessions'])}</td><td>{escape(r['notes'] or '')}</td>"
        f"<td class=\"actions\"><a href='/rules/clinician/{r['id']}/edit'>Edit</a></td></tr>"
        for r in rows
    ) or "<tr><td colspan='5'>No clinician requirements defined yet.</td></tr>"
    content = f"""
    <div class=\"card\">
        <div class=\"actions\"><a href=\"/rules/clinician/new\">Add clinician requirement</a></div>
        <table>
            <thead><tr><th>Clinician</th><th>Session type</th><th>Minimum</th><th>Notes</th><th></th></tr></thead>
            <tbody>{table_rows}</tbody>
        </table>
    </div>
    """
    return render_page(request, "Clinician requirements", content)


def clinician_requirement_form(request: Request, params: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    requirement = {"clinician_id": "", "session_type_id": "", "min_sessions": 1, "notes": ""}
    req_id = params.get("id")
    if req_id:
        existing = db.query("SELECT * FROM clinician_requirements WHERE id = ?", (int(req_id),))
        if not existing:
            return Response.redirect("/rules/clinician")
        requirement = existing[0]
    clinicians = db.query("SELECT id, full_name FROM clinicians ORDER BY full_name")
    session_types = db.query("SELECT id, name FROM session_types ORDER BY name")
    if request.method == "POST":
        clinician_id = int(request.get("clinician_id", "0"))
        session_type_raw = request.get("session_type_id", "")
        session_type_id = int(session_type_raw) if session_type_raw else None
        min_sessions = int(request.get("min_sessions", "1"))
        notes = request.get("notes", "").strip()
        now = datetime.utcnow().isoformat()
        if min_sessions < 1:
            form_html = _clinician_requirement_form_html(requirement, clinicians, session_types, "Minimum must be at least 1.")
            return render_page(request, "Clinician requirement", form_html, messages=[("error", "Minimum must be at least 1")])
        if req_id:
            db.execute(
                "UPDATE clinician_requirements SET clinician_id = ?, session_type_id = ?, min_sessions = ?, notes = ? WHERE id = ?",
                (clinician_id, session_type_id, min_sessions, notes, int(req_id)),
            )
        else:
            db.execute(
                "INSERT INTO clinician_requirements (clinician_id, session_type_id, min_sessions, notes, created_at) VALUES (?, ?, ?, ?, ?)",
                (clinician_id, session_type_id, min_sessions, notes, now),
            )
        return Response.redirect("/rules/clinician")
    form_html = _clinician_requirement_form_html(requirement, clinicians, session_types)
    return render_page(request, "Clinician requirement", form_html)


def _clinician_requirement_form_html(requirement: Dict[str, object], clinicians: List[Dict[str, object]], session_types: List[Dict[str, object]], error: str | None = None) -> str:
    error_html = f'<div class="alert error">{escape(error)}</div>' if error else ""
    clinician_options = "".join(
        f"<option value='{c['id']}' {'selected' if requirement.get('clinician_id') == c['id'] else ''}>{escape(c['full_name'])}</option>"
        for c in clinicians
    ) or "<option value=''>Create clinicians first</option>"
    type_options = "<option value=''>Any</option>" + "".join(
        f"<option value='{stype['id']}' {'selected' if requirement.get('session_type_id') == stype['id'] else ''}>{escape(stype['name'])}</option>"
        for stype in session_types
    )
    min_value = escape(requirement.get('min_sessions', 1))
    notes_value = escape(requirement.get('notes', '') or '')
    return f"""
    <div class=\"card\">
        <form method=\"post\">
            {error_html}
            <label for=\"clinician_id\">Clinician</label>
            <select id=\"clinician_id\" name=\"clinician_id\">{clinician_options}</select>
            <label for=\"session_type_id\">Session type</label>
            <select id=\"session_type_id\" name=\"session_type_id\">{type_options}</select>
            <label for=\"min_sessions\">Minimum sessions per week</label>
            <input id=\"min_sessions\" name=\"min_sessions\" type=\"number\" min=\"1\" value=\"{min_value}\">
            <label for=\"notes\">Notes</label>
            <textarea id=\"notes\" name=\"notes\">{notes_value}</textarea>
            <button type=\"submit\">Save</button>
            <a class=\"button secondary\" href=\"/rules/clinician\">Cancel</a>
        </form>
    </div>
    """


def validate_view(request: Request, _: Dict[str, str]) -> Response:
    user = auth.get_user_from_request(request)
    if user is None:
        return Response.redirect("/login")
    request.user = user
    results = evaluate_rules()
    items = "".join(f"<li>{escape(item)}</li>" for item in results) or "<li>All rules satisfied.</li>"
    content = f"""
    <div class=\"card\">
        <h2>Validation results</h2>
        <ul>{items}</ul>
    </div>
    """
    return render_page(request, "Validation", content)


def evaluate_rules() -> List[str]:
    messages: List[str] = []
    sessions = db.query(
        """
        SELECT rota_sessions.id, rota_sessions.day_of_week, rota_sessions.session_type_id
        FROM rota_sessions
        """
    )
    assignments = db.query(
        "SELECT session_id, clinician_id FROM session_assignments"
    )
    session_type_names = {row["id"]: row["name"] for row in db.query("SELECT id, name FROM session_types")}
    clinician_names = {row["id"]: row["full_name"] for row in db.query("SELECT id, full_name FROM clinicians")}
    assignment_map: Dict[int, List[int]] = defaultdict(list)
    for row in assignments:
        assignment_map[row["session_id"]].append(row["clinician_id"])

    # Evaluate day requirements
    for requirement in db.query("SELECT * FROM day_requirements"):
        day = requirement["day_of_week"]
        role = requirement.get("role")
        session_type_id = requirement.get("session_type_id")
        min_count = requirement["min_count"]
        matching_sessions = [s for s in sessions if s["day_of_week"] == day and (session_type_id is None or s["session_type_id"] == session_type_id)]
        total = 0
        for session in matching_sessions:
            clinician_ids = assignment_map.get(session["id"], [])
            if role:
                role_matches = db.query(
                    "SELECT COUNT(*) as count FROM clinicians WHERE id IN (%s) AND role = ?" % ",".join("?" * len(clinician_ids)),
                    (*clinician_ids, role),
                ) if clinician_ids else [{"count": 0}]
                total += role_matches[0]["count"]
            else:
                total += len(clinician_ids)
        if total < min_count:
            type_label = session_type_names.get(session_type_id, "any session") if session_type_id else "any session"
            role_label = role or "any role"
            messages.append(
                f"Day requirement unmet: {_day_label(day)} needs at least {min_count} clinicians (role: {role_label}, session: {type_label}), currently {total}."
            )

    # Evaluate clinician requirements
    session_type_counts: Dict[Tuple[int, int | None], int] = defaultdict(int)
    for session in sessions:
        clinician_ids = assignment_map.get(session["id"], [])
        for clinician_id in clinician_ids:
            session_type_counts[(clinician_id, session["session_type_id"])] += 1
            session_type_counts[(clinician_id, None)] += 1
    for requirement in db.query("SELECT * FROM clinician_requirements"):
        clinician_id = requirement["clinician_id"]
        session_type_id = requirement.get("session_type_id")
        min_sessions = requirement["min_sessions"]
        actual = session_type_counts[(clinician_id, session_type_id)]
        clinician_name = clinician_names.get(clinician_id, f"Clinician {clinician_id}")
        session_label = session_type_names.get(session_type_id, "any session") if session_type_id else "any session"
        if actual < min_sessions:
            messages.append(
                f"Clinician requirement unmet: {clinician_name} needs {min_sessions} x {session_label}, currently {actual}."
            )
    return messages


def _day_label(idx: int) -> str:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][idx % 7]
