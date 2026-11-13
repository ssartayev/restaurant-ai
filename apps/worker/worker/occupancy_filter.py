"""Temporal filter: turns noisy per-frame presence into stable occupied / vacant decisions.

Per table, keep a sliding window of (time, present) samples and apply hysteresis:

  vacant   -> occupied  when, over the last ENTER_WINDOW_S seconds, someone was present
                        in at least ENTER_RATIO of the samples            (default 20 s, 70%)
  occupied -> vacant    when, over the last EXIT_WINDOW_S seconds, someone was present
                        in at most EXIT_RATIO of the samples              (default 75 s, 10%)

Why this shape
  * A person walking through a zone is present for a few samples: far below 70% of 20 s.
  * A guest who stands up briefly, a missed detection or a short occlusion leaves a gap
    shorter than 75 s, so the table stays occupied.
  * The exit rule tolerates up to 10% stray positives, so one passer-by does not restart
    the vacancy clock (a pure "nobody seen for 75 s" rule would).
  * The two thresholds differ on purpose (hysteresis): a table cannot flicker.

Cost of the exit window: a departure is reported about EXIT_WINDOW_S after it happens.
A shorter window means faster alerts and more false "needs clearing" alerts.
"""
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class FilterConfig:
    enter_window_s: float = 20.0
    enter_ratio: float = 0.7
    exit_window_s: float = 75.0
    exit_ratio: float = 0.1
    coverage: float = 0.9  # the window must be at least this full before a decision is made

    @classmethod
    def from_dict(cls, d: dict | None) -> "FilterConfig":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


class TableOccupancyFilter:
    def __init__(self, cfg: FilterConfig | None = None, occupied: bool = False):
        self.cfg = cfg or FilterConfig()
        self.occupied = occupied
        self.since: float | None = None
        self._samples: deque[tuple[float, bool]] = deque()

    def _ratio(self, now: float, window: float) -> float | None:
        """Share of samples with presence in (now - window, now]; None if the window is not full."""
        recent = [(t, p) for t, p in self._samples if t > now - window]
        if not recent or now - self._samples[0][0] < window * self.cfg.coverage:
            return None
        return sum(1 for _, p in recent if p) / len(recent)

    def update(self, t: float, present: bool) -> bool | None:
        """Feed one sample. Returns True/False when the table CHANGES state, else None."""
        self._samples.append((t, present))
        horizon = t - max(self.cfg.enter_window_s, self.cfg.exit_window_s) - 1
        while self._samples and self._samples[0][0] < horizon:
            self._samples.popleft()

        if not self.occupied:
            r = self._ratio(t, self.cfg.enter_window_s)
            if r is not None and r >= self.cfg.enter_ratio:
                self.occupied, self.since = True, t
                return True
        else:
            r = self._ratio(t, self.cfg.exit_window_s)
            if r is not None and r <= self.cfg.exit_ratio:
                self.occupied, self.since = False, t
                return False
        return None
