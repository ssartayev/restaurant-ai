"""Table state machine. Pure functions: no database, no clock, no I/O.

Contract: packages/contracts/transitions.yaml (tests verify every row).

Core rules
  1. The camera can only cause  ready -> occupied  and  occupied -> needs_clearing.
  2. Only a person can make a table ready.
  3. Manual hold: every staff action sets a hold on that table. While held, camera
     observations are recorded but never change state. The hold is released when the
     camera reports occupancy that AGREES with the current state, observed after the
     staff action. After release, the next camera change applies normally.
  4. Guards run first: automation off, camera offline, stale observation.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

READY, OCCUPIED, NEEDS_CLEARING = "ready", "occupied", "needs_clearing"

STAFF_TARGETS = {
    "mark_ready": READY,
    "mark_occupied": OCCUPIED,
    "mark_needs_clearing": NEEDS_CLEARING,
}
STAFF_COMMANDS = (*STAFF_TARGETS, "resume_camera", "mark_greeted")


@dataclass(frozen=True)
class TableSnapshot:
    state: str
    manual_hold: bool = False
    manual_hold_since: datetime | None = None
    last_camera_observed_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    result: str                 # applied | hold_released | ignored_* | no_change
    new_state: str              # equals the old state unless result == "applied"
    set_hold: bool = False
    release_hold: bool = False
    accepted: bool = False      # observation passed the guards (advance last_camera_observed_at)

    @property
    def changed(self) -> bool:
        return self.result == "applied"


def camera_agrees(state: str, occupied: bool) -> bool:
    """Does a camera observation agree with the table state?"""
    if state == OCCUPIED:
        return occupied
    return not occupied  # ready and needs_clearing both expect an empty table


def decide_camera(
    t: TableSnapshot,
    occupied: bool,
    observed_at: datetime,
    now: datetime,
    *,
    automation_enabled: bool = True,
    camera_online: bool = True,
    stale_after_s: int = 120,
) -> Decision:
    same = t.state
    # --- guards, in contract order ---
    if not automation_enabled:
        return Decision("ignored_automation_off", same)
    if not camera_online:
        return Decision("ignored_camera_offline", same)
    if now - observed_at > timedelta(seconds=stale_after_s):
        return Decision("ignored_stale", same)
    if t.last_camera_observed_at is not None and observed_at < t.last_camera_observed_at:
        return Decision("ignored_stale", same)
    if t.manual_hold and t.manual_hold_since is not None and observed_at <= t.manual_hold_since:
        return Decision("ignored_manual_hold", same)

    # --- manual hold: never change state; release only on agreement ---
    if t.manual_hold:
        if camera_agrees(t.state, occupied):
            return Decision("hold_released", same, release_hold=True, accepted=True)
        return Decision("ignored_manual_hold", same, accepted=True)

    # --- the only two transitions a camera may cause ---
    if t.state == READY and occupied:
        return Decision("applied", OCCUPIED, accepted=True)
    if t.state == OCCUPIED and not occupied:
        return Decision("applied", NEEDS_CLEARING, accepted=True)
    return Decision("ignored_state", same, accepted=True)


def decide_staff(t: TableSnapshot, command: str) -> Decision:
    if command not in STAFF_COMMANDS:
        raise ValueError(f"unknown command: {command}")
    if command == "resume_camera":
        return Decision("applied" if t.manual_hold else "no_change", t.state, release_hold=True)
    if command == "mark_greeted":
        return Decision("no_change", t.state)  # greeted is a flag, not a state; handled by the service
    target = STAFF_TARGETS[command]
    if target == t.state:
        return Decision("no_change", t.state)
    return Decision("applied", target, set_hold=True)
