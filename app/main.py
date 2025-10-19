from __future__ import annotations

from wsgiref.simple_server import make_server
from . import db
from . import auth, views
from .http import Request
from .router import Router


router = Router()

_initialized = False


def ensure_initialized() -> None:
    global _initialized
    if not _initialized:
        db.init_db()
        db.ensure_default_admin()
        _initialized = True


router.add_route("/", views.dashboard, methods=("GET",))
router.add_route("/login", views.login_view, methods=("GET", "POST"))
router.add_route("/logout", views.logout_view, methods=("GET",))
router.add_route("/clinicians", views.list_clinicians, methods=("GET",))
router.add_route("/clinicians/new", views.clinician_form, methods=("GET", "POST"))
router.add_route("/clinicians/<int:id>/edit", views.clinician_form, methods=("GET", "POST"))
router.add_route("/session-types", views.list_session_types, methods=("GET",))
router.add_route("/session-types/new", views.session_type_form, methods=("GET", "POST"))
router.add_route("/session-types/<int:id>/edit", views.session_type_form, methods=("GET", "POST"))
router.add_route("/sessions", views.list_sessions, methods=("GET",))
router.add_route("/sessions/new", views.session_form, methods=("GET", "POST"))
router.add_route("/sessions/<int:id>/edit", views.session_form, methods=("GET", "POST"))
router.add_route("/rules/day", views.list_day_requirements, methods=("GET",))
router.add_route("/rules/day/new", views.day_requirement_form, methods=("GET", "POST"))
router.add_route("/rules/day/<int:id>/edit", views.day_requirement_form, methods=("GET", "POST"))
router.add_route("/rules/clinician", views.list_clinician_requirements, methods=("GET",))
router.add_route("/rules/clinician/new", views.clinician_requirement_form, methods=("GET", "POST"))
router.add_route("/rules/clinician/<int:id>/edit", views.clinician_requirement_form, methods=("GET", "POST"))
router.add_route("/validate", views.validate_view, methods=("GET",))


def application(environ, start_response):
    ensure_initialized()
    request = Request(environ)
    user = auth.get_user_from_request(request)
    if user:
        request.user = user
    response = router.dispatch(request)
    status_line = f"{response.status.value} {response.status.phrase}"
    start_response(status_line, response.headers)
    return [response.body]


def main() -> None:
    ensure_initialized()
    with make_server("0.0.0.0", 8000, application) as httpd:
        print("Serving on http://0.0.0.0:8000 ...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Shutting down server")


if __name__ == "__main__":
    main()
