"""Conservative recording-local role estimates, never identity recognition.

Track numbers remain internal and expire after a short gap. Ambiguous geometric
matches reset evidence rather than transferring a role between crossing people.
"""
from collections import deque
from math import hypot


class RoleEstimator:
    def __init__(self):
        self.tracks = []

    def update(self, time, observations):
        self.tracks = [t for t in self.tracks if time - t["time"] <= 2.1]
        pairs = []
        for i, (box, _, _) in enumerate(observations):
            for j, track in enumerate(self.tracks):
                old = track["box"]
                scale = max(.05, box.y2 - box.y1, old.y2 - old.y1)
                distance = hypot((box.x1 + box.x2 - old.x1 - old.x2) / 2,
                                 (box.y1 + box.y2 - old.y1 - old.y2) / 2) / scale
                if distance < .45:
                    pairs.append((distance, i, j))
        used, assigned = set(), {}
        for distance, i, j in sorted(pairs):
            if i in assigned or j in used:
                continue
            # Do not inherit evidence when two people could be the same match.
            if any(k != i and l == j and abs(d - distance) < .12 for d, k, l in pairs):
                continue
            if any(k == i and l != j and abs(d - distance) < .12 for d, k, l in pairs):
                continue
            assigned[i] = j
            used.add(j)
        results = []
        for i, (box, seated, service) in enumerate(observations):
            if i in assigned:
                track = self.tracks[assigned[i]]
            else:
                track = {"history": deque(), "box": box, "time": time}
                self.tracks.append(track)
            history = track["history"]
            history.append((time, seated is True, service))
            while history and history[0][0] < time - 10:
                history.popleft()
            track.update(box=box, time=time)
            label, reason = "Person · role uncertain", "Insufficient or conflicting behavioral evidence"
            if len(history) >= 4 and time - history[0][0] >= 3:
                sitting = sum(row[1] for row in history)
                servicing = sum(row[2] for row in history)
                if servicing >= 3 and sitting == 0:
                    label, reason = "Possible waiter", "Repeated reaching over tables; role is unconfirmed"
                elif sitting / len(history) >= .75 and servicing == 0:
                    label, reason = "Likely guest", "Repeated seated pose; role is unconfirmed"
            results.append((label, reason))
        return results
