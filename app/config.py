import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_PATH = Path(os.environ.get("ROTA_DATABASE_PATH", DATA_DIR / "rota.sqlite3"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Secret key used for signing cookies. In a real deployment this should be
# supplied via environment variable.
SECRET_KEY = os.environ.get("ROTA_SECRET_KEY", "change-me-please")

SESSION_COOKIE_NAME = "rota_session"
SESSION_DURATION_SECONDS = 60 * 60 * 8  # 8 hours
