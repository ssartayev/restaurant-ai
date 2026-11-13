"""Assign seated-person estimates to tables and smooth brief detection gaps."""
from collections import deque
from math import hypot
from statistics import median_low


def activity(tables, samples):
    recent = [deque() for _ in tables]
    states = ["unknown"] * len(tables)
    since = [0.0] * len(tables)
    timeline = []
    previous = [[] for _ in tables]

    for time, people in samples:
        candidates = [[] for _ in tables]
        for x, y in people:
            distances = []
            for i, table in enumerate(tables):
                left, top, right, bottom = table["box"]
                width, height = right - left, bottom - top
                if width > 0 and height > 0:
                    distance = hypot((x - table["x"]) / width, (y - table["y"]) / height)
                    if distance <= 1.0:
                        distances.append((distance, i))
            if distances:
                candidates[min(distances)[1]].append((x, y))

        counts = []
        for i, (table, points) in enumerate(zip(tables, candidates)):
            left, top, right, bottom = table["box"]
            width, height = right - left, bottom - top
            # Match once per frame so a nearby second detection cannot inherit the same history.
            matches = sorted(
                (hypot((x - px) / width, (y - py) / height), current, prior)
                for current, (x, y) in enumerate(points)
                for prior, (px, py, _) in enumerate(previous[i])
            )
            used = set()
            ages = [1] * len(points)
            for distance, current, prior in matches:
                if distance > .25:
                    break
                if prior not in used and ages[current] == 1:
                    ages[current] = previous[i][prior][2] + 1
                    used.add(prior)
            previous[i] = [(x, y, age) for (x, y), age in zip(points, ages)]
            counts.append(sum(age >= 2 for age in ages))

        readings = []
        for i, count in enumerate(counts):
            history = recent[i]
            history.append((time, count))
            while history[0][0] < time - 4:
                history.popleft()
            stable_count = median_low([value for _, value in history])
            state = states[i]
            if time - history[0][0] >= 2:
                if stable_count:
                    state = "occupied"
                elif state != "occupied" or not any(value for _, value in history):
                    state = "vacant"
            if state != states[i]:
                since[i] = history[0][0] if states[i] == "unknown" else time
                states[i] = state
            readings.append({"state": state, "people": (stable_count or max(value for _, value in history)) if state == "occupied" else 0,
                             "since": since[i]})
        timeline.append([time, readings])
    return timeline
