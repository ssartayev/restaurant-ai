"""Hosted demo: one private sandbox restaurant per viewer, plus a real-time scenario runner.

Isolation: "Start demo" creates a brand-new restaurant from the seed fixture. A sandbox
is an ordinary tenant, so the normal access checks keep viewers apart. "Reset" deletes
that one sandbox's rows and re-seeds it under the same ID. Sandboxes expire after
DEMO_TTL_HOURS (service.sweep deletes them).
"""
import asyncio
from datetime import timedelta

from sqlalchemy import delete, select

from . import bus, config, scenario, seed, service
from .db import SessionLocal
from .models import (Alert, Camera, Membership, Restaurant, Table, TableEvent, User, WaitlistParty,
                     Zone)
from .util import utcnow

_runners: dict[str, "Runner"] = {}


def create_sandbox(db) -> dict:
    return seed.create_restaurant(db, seed.load_seed(), is_demo=True, unique_emails=True)


def reset_sandbox(db, restaurant_id: str):
    """Restore the seeded state for ONE sandbox. Other sandboxes are untouched."""
    stop(restaurant_id)
    r = db.get(Restaurant, restaurant_id)
    for model in (TableEvent, Alert, WaitlistParty, Zone, Table, Camera):
        db.execute(delete(model).where(model.restaurant_id == restaurant_id))
    db.commit()
    data = seed.load_seed()
    fresh = seed.create_restaurant(db, data, is_demo=True, unique_emails=True)
    # Re-seeding made a second restaurant; move its rows under the original ID, then drop the shell.
    new_id = fresh["restaurant"].id
    for model in (TableEvent, Alert, WaitlistParty, Zone, Table, Camera):
        db.execute(model.__table__.update().where(model.restaurant_id == new_id)
                   .values(restaurant_id=restaurant_id))
    db.commit()
    service.delete_restaurant(db, new_id)
    r.automation_enabled = True
    r.expires_at = utcnow() + timedelta(hours=config.DEMO_TTL_HOURS)
    db.commit()
    bus.publish(restaurant_id, "demo.reset", {})


class Runner:
    """Replays a scenario into one sandbox in real time (divided by `speed`)."""

    def __init__(self, restaurant_id: str, name: str, speed: float):
        self.rid, self.name, self.speed = restaurant_id, name, max(0.25, min(speed, 20))
        self.steps = scenario.load(name)
        self.index, self.paused, self.done = 0, False, False
        self.note: str | None = None
        self.task: asyncio.Task | None = None

    def status(self) -> dict:
        return {"scenario": self.name, "speed": self.speed, "step": self.index,
                "steps": len(self.steps), "paused": self.paused, "done": self.done,
                "note": self.note}

    def _apply(self, step: dict):
        with SessionLocal() as db:
            if db.get(Restaurant, self.rid) is None:
                raise asyncio.CancelledError()
            ctx = scenario.Context(db, self.rid)
            if step["do"] != "expect":
                scenario.apply_step(ctx, step, utcnow())

    async def run(self):
        clock = 0.0
        try:
            while self.index < len(self.steps):
                step = self.steps[self.index]
                wait = max(0.0, (step.get("t", 0) - clock) / self.speed)
                while wait > 0 or self.paused:
                    await asyncio.sleep(0.1)
                    if not self.paused:
                        wait -= 0.1
                clock = step.get("t", 0)
                await asyncio.to_thread(self._apply, step)
                if step.get("note"):
                    self.note = step["note"]
                self.index += 1
                bus.publish(self.rid, "demo.progress", self.status())
            self.done = True
            bus.publish(self.rid, "demo.progress", self.status())
        except asyncio.CancelledError:
            pass


def start(restaurant_id: str, name: str, speed: float) -> dict:
    stop(restaurant_id)
    runner = Runner(restaurant_id, name, speed)
    runner.task = asyncio.get_running_loop().create_task(runner.run())
    _runners[restaurant_id] = runner
    return runner.status()


def pause(restaurant_id: str, paused: bool) -> dict | None:
    runner = _runners.get(restaurant_id)
    if runner:
        runner.paused = paused
        return runner.status()
    return None


def stop(restaurant_id: str):
    runner = _runners.pop(restaurant_id, None)
    if runner and runner.task:
        runner.task.cancel()


def status(restaurant_id: str) -> dict | None:
    runner = _runners.get(restaurant_id)
    return runner.status() if runner else None
