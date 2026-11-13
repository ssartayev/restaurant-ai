from app.table_activity import activity


def test_seated_count_and_timer_survive_a_short_detection_gap():
    table = {"x": .5, "y": .5, "box": [.4, .4, .6, .6]}
    party = [(.42, .5), (.58, .5)]
    timeline = activity([table], enumerate([party, party, party, [], party, [], [], []]))
    assert timeline[2][1][0] == {"state": "occupied", "people": 2, "since": 0}
    assert timeline[4][1][0] == timeline[2][1][0]
    assert timeline[7][1][0] == {"state": "vacant", "people": 0, "since": 7}


def test_person_crossing_near_a_table_does_not_count_as_seated():
    table = {"x": .5, "y": .5, "box": [.4, .4, .6, .6]}
    crossing = [[(.35, .5)], [(.43, .5)], [(.51, .5)], [(.59, .5)], [], [], []]
    timeline = activity([table], enumerate(crossing))
    assert all(reading[0]["state"] != "occupied" for _, reading in timeline)
