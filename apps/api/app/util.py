import secrets
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC. All timestamps in the database are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat(timespec="milliseconds") + "Z"


def new_id(prefix: str) -> str:
    """Globally unique prefixed ID, e.g. tbl_9f2c...  Safe across restaurants and locations."""
    return f"{prefix}_{secrets.token_hex(10)}"
