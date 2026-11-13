from types import SimpleNamespace
from app.roles import RoleEstimator


def box(x=.2):
    return SimpleNamespace(x1=x, x2=x+.15, y1=.2, y2=.7)


def test_walkers_remain_unknown_and_repeated_service_is_only_possible_waiter():
    estimator = RoleEstimator()
    for t in range(5):
        label, _ = estimator.update(t, [(box(), False, False)])[0]
        assert label == "Person · role uncertain"
    for t in range(5, 16):
        label, _ = estimator.update(t, [(box(), False, True)])[0]
    assert label == "Possible waiter"


def test_guest_requires_repeated_seated_evidence_and_expires_after_gap():
    estimator = RoleEstimator()
    assert estimator.update(0, [(box(), True, False)])[0][0] == "Person · role uncertain"
    for t in range(1, 5):
        label, _ = estimator.update(t, [(box(), True, False)])[0]
    assert label == "Likely guest"
    assert estimator.update(10, [(box(), False, False)])[0][0] == "Person · role uncertain"


def test_conflicting_service_and_seated_evidence_is_unknown():
    estimator = RoleEstimator()
    for t in range(6):
        label, _ = estimator.update(t, [(box(), t % 2 == 0, t % 2 == 1)])[0]
    assert label == "Person · role uncertain"
