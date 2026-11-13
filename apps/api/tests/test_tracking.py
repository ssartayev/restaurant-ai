"""Person tracking and table discovery for recording review (pure logic, no models)."""
from types import SimpleNamespace

from app.table_discovery import TableCandidates
from app.tracking import Tracker

RED = [1.0] + [0.0] * 127          # clothing histograms: all mass in one colour bin
BLUE = [0.0] * 127 + [1.0]
WHITE = [0.0] * 60 + [1.0] + [0.0] * 67


def person(cx, cy, w=0.06, h=0.2):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def run(tracker, frames):
    """frames: [(t, [(box, appearance), ...])] -> [[track ids]]"""
    return [tracker.update(t, [b for b, _ in dets], [a for _, a in dets]) for t, dets in frames]


def test_walking_person_keeps_one_track_past_seated_guests():
    # A waiter walks 0.7 of the frame width in 14 s (about one body height every 4 s is slow;
    # this is ~0.25 heights per 0.25 s step) past two seated guests in different clothes.
    frames = []
    for k in range(57):
        t = k * 0.25
        frames.append((t, [(person(0.15 + 0.0125 * k, 0.5), WHITE),
                           (person(0.40, 0.55), RED), (person(0.65, 0.45), BLUE)]))
    ids = run(Tracker(), frames)
    assert len({row[0] for row in ids}) == 1, "the walking person is one track for the whole clip"
    assert len({row[1] for row in ids}) == 1 and len({row[2] for row in ids}) == 1
    assert len({ids[0][0], ids[0][1], ids[0][2]}) == 3


def test_fast_walk_at_four_frames_per_second():
    # One full body height per second (brisk walk close to the camera).
    frames = [(k * 0.25, [(person(0.1 + 0.05 * k, 0.5), WHITE)]) for k in range(16)]
    assert len({row[0] for row in run(Tracker(), frames)}) == 1


def test_short_occlusion_is_bridged_by_clothing():
    frames = [(k * 0.25, [(person(0.2 + 0.01 * k, 0.5), WHITE), (person(0.8, 0.5), RED)]) for k in range(8)]
    # 3 s behind a pillar, then the same clothes reappear further along.
    frames += [(2.0 + k * 0.25, [(person(0.8, 0.5), RED)]) for k in range(12)]
    frames += [(5.0 + k * 0.25, [(person(0.42 + 0.01 * k, 0.5), WHITE), (person(0.8, 0.5), RED)]) for k in range(8)]
    ids = run(Tracker(), frames)
    assert ids[0][0] == ids[-1][0], "same person after the gap"
    assert ids[0][1] == ids[-1][1]


def test_different_clothes_never_inherit_a_lost_track():
    frames = [(k * 0.25, [(person(0.3, 0.5), WHITE)]) for k in range(8)]
    frames += [(4.0 + k * 0.25, [(person(0.32, 0.5), RED)]) for k in range(4)]
    ids = run(Tracker(), frames)
    assert ids[0][0] != ids[-1][0]


def test_long_gap_is_not_bridged():
    frames = [(k * 0.25, [(person(0.3, 0.5), WHITE)]) for k in range(8)]
    frames += [(20.0, [(person(0.3, 0.5), WHITE)])]
    ids = run(Tracker(), frames)
    assert ids[0][0] != ids[-1][0]


def test_two_people_in_the_same_uniform_do_not_swap_when_they_cross():
    # Identical clothing, paths cross in the middle. A track may pause, but a mark put on
    # person A at the start must never end up on person B.
    frames = []
    for k in range(41):
        t, x = k * 0.25, 0.2 + 0.015 * k
        frames.append((t, [(person(x, 0.50), WHITE), (person(1.0 - x, 0.52), WHITE)]))
    ids = run(Tracker(), frames)
    a = ids[0][0]
    assert all(row[1] != a for row in ids), "A's track number never appears on B"


def test_crossing_people_in_different_clothes_keep_their_tracks():
    frames = []
    for k in range(41):
        t, x = k * 0.25, 0.2 + 0.015 * k
        frames.append((t, [(person(x, 0.50), WHITE), (person(1.0 - x, 0.52), RED)]))
    ids = run(Tracker(), frames)
    assert ids[-1][0] == ids[0][0] and ids[-1][1] == ids[0][1]


def test_two_people_merging_into_one_box_get_their_own_tracks_back():
    mixed = [(a + b) / 2 for a, b in zip(WHITE, RED)]
    frames = [(k * 0.25, [(person(0.30 + 0.02 * k, 0.5), WHITE), (person(0.50, 0.5), RED)]) for k in range(8)]
    # For 1.5 s the detector returns ONE box covering both (walker passing in front).
    frames += [(2.0 + k * 0.25, [(person(0.49, 0.5, w=0.1), mixed)]) for k in range(6)]
    frames += [(3.5 + k * 0.25, [(person(0.56 + 0.02 * k, 0.5), WHITE), (person(0.50, 0.5), RED)]) for k in range(8)]
    ids = run(Tracker(), frames)
    walker, seated = ids[0]
    assert ids[-1] == [walker, seated], "after separating, each person has their original track"
    assert all(walker not in row or row.index(walker) == 0 for row in ids[14:]), "the mark never lands on the seated guest"


# ---------------------------------------------------------------- table discovery

def box(x1, y1, x2, y2, conf):
    return SimpleNamespace(x1=x1, y1=y1, x2=x2, y2=y2, conf=conf)


def test_original_rule_still_accepts_two_confident_sightings():
    c = TableCandidates()
    c.add_frame([box(.1, .1, .3, .3, .5)])
    c.add_frame([box(.11, .1, .3, .31, .4)])
    for _ in range(30):
        c.add_frame([])
    assert len(c.accepted()) == 1


def test_persistent_weak_table_is_accepted_and_a_flicker_is_not():
    c = TableCandidates()
    for k in range(20):
        frame = [box(.5, .5, .7, .7, .14)] if k % 2 == 0 else []     # weak, in half the frames
        if k in (3, 9):
            frame.append(box(.05, .6, .2, .8, .12))                   # weak, twice only
        c.add_frame(frame)
    tables = c.accepted()
    assert len(tables) == 1 and abs(tables[0].x1 - .5) < 1e-9


def test_one_confident_sighting_alone_is_not_a_table():
    c = TableCandidates()
    c.add_frame([box(.1, .1, .3, .3, .6)])
    for _ in range(15):
        c.add_frame([])
    assert c.accepted() == []


def test_duplicates_merge_and_giant_or_tiny_boxes_are_ignored():
    c = TableCandidates()
    for _ in range(8):
        c.add_frame([box(.4, .4, .6, .6, .3), box(.42, .41, .6, .6, .15),   # same table twice
                     box(0, 0, 1, 1, .3), box(.9, .9, .92, .92, .3)])       # whole frame, speck
    assert len(c.accepted()) == 1


def test_tables_are_numbered_top_to_bottom_then_left_to_right():
    c = TableCandidates()
    for _ in range(4):
        c.add_frame([box(.6, .6, .8, .8, .3), box(.1, .1, .3, .3, .3), box(.6, .1, .8, .3, .3)])
    assert [(round(t.x1, 1), round(t.y1, 1)) for t in c.accepted()] == [(.1, .1), (.6, .1), (.6, .6)]
