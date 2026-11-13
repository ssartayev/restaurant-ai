"""Analytics computed from the append-only table_events history."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import NEEDS_CLEARING, OCCUPIED, READY, OrderTicket, Table, TableEvent


def _transitions(db: Session, rid: str, start: datetime, end: datetime):
    return list(db.execute(
        select(TableEvent.table_id, TableEvent.to_state, TableEvent.observed_at)
        .where(TableEvent.restaurant_id == rid, TableEvent.applied.is_(True),
               TableEvent.to_state.is_not(None),
               TableEvent.observed_at >= start, TableEvent.observed_at < end)
        .order_by(TableEvent.table_id, TableEvent.observed_at)))


def summary(db: Session, rid: str, start: datetime, end: datetime, now: datetime) -> dict:
    """Occupancy, turnover and clearing time for [start, end).

    turn            = one occupied interval (enter occupied -> leave occupied)
    clearing time   = needs_clearing -> ready
    occupancy %     = occupied table-seconds / (tables x elapsed seconds)
    Intervals still open at the end of the range are counted up to min(end, now).
    """
    horizon = min(end, now)
    n_tables = len(list(db.scalars(select(Table.id).where(Table.restaurant_id == rid))))
    by_table = defaultdict(list)
    # Include the last transition before the period for each table, so an
    # occupied interval spanning midnight is counted inside the selected range.
    previous = select(
        TableEvent.table_id, TableEvent.to_state, TableEvent.observed_at,
        func.row_number().over(partition_by=TableEvent.table_id,
                               order_by=(TableEvent.observed_at.desc(), TableEvent.received_at.desc(),
                                         TableEvent.id.desc())).label("rank"),
    ).where(TableEvent.restaurant_id == rid, TableEvent.applied.is_(True),
            TableEvent.to_state.is_not(None), TableEvent.observed_at < start).subquery()
    for table_id, state, at in db.execute(select(
            previous.c.table_id, previous.c.to_state, previous.c.observed_at).where(previous.c.rank == 1)):
        by_table[table_id].append((state, at))
    for table_id, to_state, at in _transitions(db, rid, start, horizon):
        by_table[table_id].append((to_state, at))

    turn_durations, clear_durations, occupied_s = [], [], 0.0
    for events in by_table.values():
        occ_start = clear_start = None
        for to_state, at in events:
            if to_state == OCCUPIED:
                occ_start, clear_start = at, None
            else:
                if occ_start is not None:
                    if at >= start:
                        turn_durations.append((at - occ_start).total_seconds())
                    occupied_s += max(0, (at - max(occ_start, start)).total_seconds())
                    occ_start = None
                if to_state == NEEDS_CLEARING:
                    clear_start = at
                elif to_state == READY and clear_start is not None:
                    if at >= start:
                        clear_durations.append((at - clear_start).total_seconds())
                    clear_start = None
        if occ_start is not None and horizon > occ_start:
            occupied_s += max(0, (horizon - max(occ_start, start)).total_seconds())

    elapsed = max((horizon - start).total_seconds(), 1.0)
    return {
        "from": start.isoformat() + "Z", "to": end.isoformat() + "Z",
        "tables": n_tables,
        "turns": len(turn_durations),
        "turns_per_table": round(len(turn_durations) / n_tables, 2) if n_tables else 0,
        "avg_turn_minutes": round(mean(turn_durations) / 60, 1) if turn_durations else None,
        "median_departure_to_ready_minutes":
            round(median(clear_durations) / 60, 1) if clear_durations else None,
        "cleared_count": len(clear_durations),
        "occupancy_pct": round(100 * occupied_s / (elapsed * n_tables), 1) if n_tables else 0,
    }


def shift_of(hour: int) -> str:
    if 6 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 16:
        return "lunch"
    if 16 <= hour < 23:
        return "dinner"
    return "late"


def peak_hours(db: Session, rid: str, tz: str, start: datetime, end: datetime) -> dict:
    """Party arrivals (table became occupied) by weekday x hour and by weekday x shift, local time."""
    zone = ZoneInfo(tz)
    utc = ZoneInfo("UTC")
    by_hour, by_shift = defaultdict(int), defaultdict(int)
    for _table_id, to_state, at in _transitions(db, rid, start, end):
        if to_state != OCCUPIED:
            continue
        local = at.replace(tzinfo=utc).astimezone(zone)
        by_hour[(local.weekday(), local.hour)] += 1
        by_shift[(local.weekday(), shift_of(local.hour))] += 1
    weeks = max((end - start) / timedelta(days=7), 1e-9)
    return {
        "timezone": tz,
        "by_hour": [{"weekday": d, "hour": h, "arrivals": n, "per_week": round(n / weeks, 1)}
                    for (d, h), n in sorted(by_hour.items())],
        "by_shift": [{"weekday": d, "shift": s, "arrivals": n, "per_week": round(n / weeks, 1)}
                     for (d, s), n in sorted(by_shift.items())],
    }


def calendar_start(now: datetime, tz: str, period: str) -> datetime:
    local = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start = midnight - timedelta(days=midnight.weekday())
    elif period == "month":
        start = midnight.replace(day=1)
    else:
        start = midnight.replace(month=1, day=1)
    return start.astimezone(timezone.utc).replace(tzinfo=None)

def order_summary(db: Session, rid: str, start: datetime, end: datetime) -> dict:
    tickets = list(db.scalars(select(OrderTicket).where(
        OrderTicket.restaurant_id == rid, OrderTicket.sent_at >= start, OrderTicket.sent_at < end)))
    kitchen = [(t.ready_at - t.sent_at).total_seconds() / 60 for t in tickets if t.ready_at and t.ready_at < end]
    pickup = [(t.served_at - t.ready_at).total_seconds() / 60 for t in tickets
              if t.ready_at and t.served_at and t.served_at < end]
    return {"tickets_sent": len(tickets),
            "median_kitchen_minutes": round(median(kitchen), 1) if kitchen else None,
            "median_ready_to_served_minutes": round(median(pickup), 1) if pickup else None}
