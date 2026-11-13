"""Replay every non-demo scenario fixture with assertions (requirements R1-R5, R7, R8)."""
import pytest

from app import scenario

from .conftest import T0

NAMES = [n for n in scenario.available() if not n.startswith("demo_")]


@pytest.mark.parametrize("name", NAMES)
def test_scenario(db, world, name):
    failures = scenario.run_sync(db, world["restaurant"].id, scenario.load(name), T0)
    assert failures == []


def test_there_are_scenarios():
    assert "dinner_basic" in NAMES and len(NAMES) >= 6


def test_demo_scenarios_run_without_error(db, world):
    for name in scenario.available():
        if name.startswith("demo_"):
            assert scenario.run_sync(db, world["restaurant"].id, scenario.load(name), T0) == []
