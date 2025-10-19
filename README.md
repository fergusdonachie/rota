# GP Surgery Rota Planner

This project provides a lightweight web application for creating and validating duty rotas for GP surgeries. It allows an administrator to maintain a list of clinicians, define session templates, assign clinicians to specific sessions, and capture rota rules such as minimum staffing per day or per-clinician tutorial requirements.

The application ships without external dependencies beyond the Python standard library so it can run in restricted environments.

## Features

- Password-protected access with cookie-based sessions (a default `admin` user is created on first run).
- Clinician management including roles, contact details, and notes.
- Session type catalogue with default timings.
- Weekly session planner with clinician assignments.
- Day and clinician rule definitions, plus a validation report showing unmet constraints.
- SQLite storage that lives inside the `data/` directory by default.

## Getting started

1. **Create a virtual environment (optional):**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. **Run the application:**
   ```bash
   python -m app.main
   ```

   The server listens on `http://0.0.0.0:8000`. Navigate there and sign in using the default credentials `admin` / `admin123`. You should change this password immediately after your first login by editing the user directly in the SQLite database.

   If you are wiring the rota planner into a larger Python project, you can
   import `app.create_app()` to obtain the WSGI callable instead of launching
   the standalone server script.

3. **Run the unit tests:**
   ```bash
   pytest
   ```

## Configuration

The following environment variables customise the deployment:

- `ROTA_DATABASE_PATH`: path to the SQLite database file. Defaults to `./data/rota.sqlite3`.
- `ROTA_SECRET_KEY`: secret used to sign session cookies. In production this should be a long random string.

## Project layout

```
app/
  auth.py           # authentication helpers and cookie handling
  config.py         # configuration defaults
  db.py             # database utilities
  main.py           # WSGI application and entry point
  router.py         # minimal request router
  templating.py     # string.Template based rendering
  views.py          # page handlers and rule evaluation
  schema.sql        # database schema
  static/           # CSS assets
  templates/        # base HTML template
```

Sessions are stored in the `rota_sessions` table to avoid conflicts with authentication sessions. Rule evaluation is handled in `app.views.evaluate_rules` and can be extended to support additional constraint types.
