"""Data model. Every tenant-owned row carries restaurant_id; that column is the tenant boundary."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .util import new_id, utcnow

READY, OCCUPIED, NEEDS_CLEARING = "ready", "occupied", "needs_clearing"
STATES = (READY, OCCUPIED, NEEDS_CLEARING)
ROLES = ("staff", "host", "admin")  # ascending privilege


def _pk(prefix):
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


def _rid():
    return mapped_column(String(40), ForeignKey("restaurants.id", ondelete="CASCADE"), index=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = _pk("org")
    name: Mapped[str] = mapped_column(String(200))


class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[str] = _pk("rst")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _pk("usr")
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    restaurant_id: Mapped[str] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))


class AuthSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Table(Base):
    __tablename__ = "tables"
    id: Mapped[str] = _pk("tbl")
    restaurant_id: Mapped[str] = _rid()
    label: Mapped[str] = mapped_column(String(32))
    capacity: Mapped[int] = mapped_column(Integer)
    min_party: Mapped[int] = mapped_column(Integer, default=1)
    x: Mapped[float] = mapped_column(Float, default=0.0)  # floor-plan position, 0..1
    y: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String(20), default=READY)
    state_since: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency
    manual_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_hold_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_camera_observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    camera_presence_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    greeted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_party_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = _pk("cam")
    restaurant_id: Mapped[str] = _rid()
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="offline")  # online | offline
    health: Mapped[str] = mapped_column(String(16), default="ok")       # ok | degraded
    health_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)


class Zone(Base):
    """Seat zones of one table as seen by one camera. A table may have zones on several cameras."""
    __tablename__ = "zones"
    id: Mapped[str] = _pk("zon")
    restaurant_id: Mapped[str] = _rid()
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"))
    polygons: Mapped[list] = mapped_column(JSON, default=list)  # [[[x,y],...], ...] normalised 0..1
    __table_args__ = (Index("uq_zone_camera_table", "camera_id", "table_id", unique=True),)


class TableEvent(Base):
    """Append-only history. Ignored camera events are stored too, with applied=False and a reason."""
    __tablename__ = "table_events"
    id: Mapped[str] = _pk("tev")
    restaurant_id: Mapped[str] = _rid()
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(10))  # camera | staff | system
    type: Mapped[str] = mapped_column(String(40))
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    camera_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Idempotency: the same camera event can be stored only once per restaurant.
    __table_args__ = (Index("uq_event_camera_event", "restaurant_id", "camera_event_id", unique=True),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = _pk("alr")
    restaurant_id: Mapped[str] = _rid()
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))    # needs_clearing | greet_reminder
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | acknowledged | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    renotified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Duplicate suppression: at most one unresolved alert per table and type.
    __table_args__ = (
        Index("uq_alert_unresolved", "table_id", "type", unique=True,
              sqlite_where=text("status != 'resolved'"),
              postgresql_where=text("status != 'resolved'")),
    )


class WaitlistParty(Base):
    __tablename__ = "waitlist_parties"
    id: Mapped[str] = _pk("pty")
    restaurant_id: Mapped[str] = _rid()
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    party_size: Mapped[int] = mapped_column(Integer)
    arrived_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    # waiting | notified | seated | cancelled | no_show
    seated_table_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quoted_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # reserved for wait estimates
    quoted_max: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DemoRate(Base):
    __tablename__ = "demo_rate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrderTicket(Base):
    __tablename__ = "order_tickets"
    id: Mapped[str] = _pk("ord")
    restaurant_id: Mapped[str] = _rid()
    table_id: Mapped[str | None] = mapped_column(ForeignKey("tables.id", ondelete="SET NULL"))
    table_label: Mapped[str] = mapped_column(String(32))
    server_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    items: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="sent")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    preparing_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    served_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TableObservation(Base):
    """Latest table-level evidence from the edge. Frames stay on the camera device."""
    __tablename__ = "table_observations"
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"), primary_key=True)
    restaurant_id: Mapped[str] = _rid()
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    vacant_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tableware_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TableBill(Base):
    __tablename__ = "table_bills"
    id: Mapped[str] = _pk("bil")
    restaurant_id: Mapped[str] = _rid()
    table_id: Mapped[str] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"))
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (Index("uq_open_table_bill", "table_id", unique=True,
                            sqlite_where=text("paid_at IS NULL"), postgresql_where=text("paid_at IS NULL")),)


class ReportExchange(Base):
    __tablename__ = "report_exchanges"
    id: Mapped[str] = _pk("ask")
    restaurant_id: Mapped[str] = _rid()
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    question: Mapped[str] = mapped_column(String(2000))
    report: Mapped[dict] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(String, nullable=True)
