"""Every row of packages/contracts/transitions.yaml is checked against the code."""
from datetime import datetime, timedelta

import pytest
import yaml

from app import config
from app.state_machine import STAFF_COMMANDS, TableSnapshot, camera_agrees, decide_camera, decide_staff

CONTRACT = yaml.safe_load((config.CONTRACTS_DIR / "transitions.yaml").read_text())
NOW = datetime(2026, 11, 13, 19, 0, 0)


@pytest.mark.parametrize("row", CONTRACT["camera"])
def test_camera_rows(row):
    d = decide_camera(TableSnapshot(row["state"]), row["occupied"], NOW, NOW)
    assert (d.new_state, d.result) == (row["to"], row["result"])
    assert d.changed == (row["to"] != row["state"])


@pytest.mark.parametrize("row", CONTRACT["camera_held"])
def test_camera_held_rows(row):
    snap = TableSnapshot(row["state"], True, NOW - timedelta(seconds=30))
    d = decide_camera(snap, row["occupied"], NOW, NOW)
    assert d.new_state == row["state"], "a held table never changes state from a camera"
    assert d.result == row["result"]
    assert d.release_hold == row["releases_hold"]


@pytest.mark.parametrize("row", CONTRACT["staff"])
def test_staff_rows(row):
    for state in CONTRACT["states"]:
        d = decide_staff(TableSnapshot(state, manual_hold=True), row["command"])
        if row["to"] == "same":
            assert d.new_state == state and not d.set_hold
            assert d.release_hold == bool(row.get("clears_hold"))
        elif row["to"] == state:
            assert d.result == "no_change" and not d.set_hold
        else:
            assert (d.result, d.new_state, d.set_hold) == ("applied", row["to"], True)


def test_contract_and_code_list_the_same_commands():
    assert {r["command"] for r in CONTRACT["staff"]} == set(STAFF_COMMANDS)


def test_camera_can_never_produce_ready():
    for state in CONTRACT["states"]:
        for occupied in (True, False):
            for hold in (True, False):
                d = decide_camera(TableSnapshot(state, hold), occupied, NOW, NOW)
                if state != "ready":
                    assert d.new_state != "ready"


def test_guards_in_order():
    snap = TableSnapshot("ready")
    assert decide_camera(snap, True, NOW, NOW, automation_enabled=False).result == "ignored_automation_off"
    assert decide_camera(snap, True, NOW, NOW, camera_online=False).result == "ignored_camera_offline"
    old = NOW - timedelta(seconds=121)
    assert decide_camera(snap, True, old, NOW).result == "ignored_stale"
    snap = TableSnapshot("ready", last_camera_observed_at=NOW)
    assert decide_camera(snap, True, NOW - timedelta(seconds=1), NOW).result == "ignored_stale"
    assert decide_camera(snap, True, NOW, NOW).result == "applied"


def test_observation_from_before_the_staff_action_is_discarded():
    snap = TableSnapshot("occupied", True, manual_hold_since=NOW)
    # It "agrees", but it was observed before the correction, so it proves nothing.
    assert decide_camera(snap, True, NOW - timedelta(seconds=5), NOW).result == "ignored_manual_hold"
    assert decide_camera(snap, True, NOW + timedelta(seconds=5), NOW + timedelta(seconds=5)).result == "hold_released"


def test_worked_example_missed_party():
    # Camera missed a party; staff mark the table occupied.
    t = TableSnapshot("occupied", True, manual_hold_since=NOW)
    later = lambda s: NOW + timedelta(seconds=s)  # noqa: E731
    assert decide_camera(t, False, later(10), later(10)).result == "ignored_manual_hold"
    d = decide_camera(t, True, later(120), later(120))
    assert d.result == "hold_released"
    t = TableSnapshot("occupied", False, None, later(120))
    assert decide_camera(t, False, later(3600), later(3600)).new_state == "needs_clearing"


def test_agreement():
    assert camera_agrees("occupied", True) and not camera_agrees("occupied", False)
    assert camera_agrees("ready", False) and camera_agrees("needs_clearing", False)
