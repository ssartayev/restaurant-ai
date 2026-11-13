"""Runtime configuration. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR", REPO_ROOT / "fixtures"))
CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR", REPO_ROOT / "packages" / "contracts"))
WEB_DIST = Path(os.environ.get("WEB_DIST", REPO_ROOT / "apps" / "web" / "dist"))

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{REPO_ROOT / 'dev.db'}")
GIT_SHA = os.environ.get("GIT_SHA", "dev")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "72"))

# --- Domain thresholds (see AGENTS.md section 5) ---
HEARTBEAT_TIMEOUT_S = int(os.environ.get("HEARTBEAT_TIMEOUT_S", "45"))    # camera offline after this
STALE_EVENT_S = int(os.environ.get("STALE_EVENT_S", "120"))               # older events are history-only
BILL_CHECK_GRACE_S = int(os.environ.get("BILL_CHECK_GRACE_S", "300"))
GREET_REMINDER_S = int(os.environ.get("GREET_REMINDER_S", "180"))         # remind if not greeted
RENOTIFY_S = int(os.environ.get("RENOTIFY_S", "300"))                     # re-notify unacked clearing alert
PRESENCE_HINT_S = int(os.environ.get("PRESENCE_HINT_S", "180"))           # "Guests seated?" hint
WAITLIST_PII_HOURS = int(os.environ.get("WAITLIST_PII_HOURS", "24"))      # scrub name/phone after this
EVENT_RETENTION_DAYS = int(os.environ.get("EVENT_RETENTION_DAYS", "365"))
DEMO_TTL_HOURS = int(os.environ.get("DEMO_TTL_HOURS", "24"))
DEMO_MAX_PER_IP_PER_HOUR = int(os.environ.get("DEMO_MAX_PER_IP_PER_HOUR", "30"))
SWEEP_INTERVAL_S = float(os.environ.get("SWEEP_INTERVAL_S", "5"))
