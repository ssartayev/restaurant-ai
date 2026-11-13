"""Evaluation: compare the worker's events with ground-truth labels.

Labels are EVENTS, not boxes: for each table, when the first guest sat down
(party_seated) and when the last guest left the zone (party_left).

Matching: a predicted event matches a label of the same table and kind if it falls
in [label - BEFORE_S, label + AFTER_S]. Each prediction and each label is used at most
once; labels are matched in time order to the earliest free prediction in their window.

Reported:
  missed departures          unmatched party_left labels / all party_left labels
  false clearing alerts      unmatched predicted vacancies / table-hours observed
  departure delay            predicted time - true time, median and 90th percentile
  ...and the same three for arrivals (missed arrivals, false occupancy, arrival delay).

When labels also say when staff reset each table ("table_ready"), predictions are first
replayed through the server's state machine (as_seen_by_staff), so the numbers describe
what staff would actually see on the dashboard.

Usage:  python -m worker.evaluate --manifest eval/manifest.json --split heldout --out eval/report.md
"""
import argparse
import json
from pathlib import Path

from .occupancy_filter import FilterConfig
from .pipeline import Pipeline
from .zones import Box, TableZone

BEFORE_S, AFTER_S = 10.0, 180.0


def run_trace(trace: dict, cfg: FilterConfig | None = None) -> list[dict]:
    """Run the pipeline over a trace. Returns [{"table_id", "occupied", "t"}]."""
    zones = [TableZone(z["table_id"], [[tuple(p) for p in poly] for poly in z["polygons"]],
                       z.get("label", "")) for z in trace["zones"]]
    pipe = Pipeline(zones, cfg)
    out = []
    for frame in trace["frames"]:
        for ev in pipe.step(frame["t"], [Box(*b) for b in frame["boxes"]]):
            out.append({"table_id": ev["table_id"], "occupied": ev["occupied"], "t": frame["t"]})
    return out


def match(labels: list[float], preds: list[float], before: float = BEFORE_S,
          after: float = AFTER_S) -> tuple[list[float], int, int]:
    """Returns (delays of matched pairs, missed labels, unmatched predictions)."""
    preds = sorted(preds)
    used = [False] * len(preds)
    delays, missed = [], 0
    for lt in sorted(labels):
        hit = next((i for i, pt in enumerate(preds)
                    if not used[i] and lt - before <= pt <= lt + after), None)
        if hit is None:
            missed += 1
        else:
            used[hit] = True
            delays.append(preds[hit] - lt)
    return delays, missed, used.count(False)


def as_seen_by_staff(preds: list[dict], labels: list[dict]) -> list[dict]:
    """Keep only the predictions that would change a table on the dashboard.

    Replays the server's state machine per table: the camera can only do
    ready -> occupied and occupied -> needs_clearing, and only staff make a table
    ready (the "table_ready" labels). A person seen at a table that still needs
    clearing (staff clearing it) is ignored by the server, so it must not be counted
    as a false arrival, and the vacancy that follows is not a second clearing alert.
    Without table_ready labels the predictions are returned unchanged.
    """
    if not any(x["type"] == "table_ready" for x in labels):
        return preds
    out = []
    for tid in {p["table_id"] for p in preds}:
        timeline = [(x["t"], 0, None) for x in labels if x["table_id"] == tid and x["type"] == "table_ready"]
        timeline += [(p["t"], 1, p) for p in preds if p["table_id"] == tid]
        state = "ready"
        for _, _, pred in sorted(timeline, key=lambda x: (x[0], x[1])):
            if pred is None:
                state = "ready"  # staff can mark a table ready from any state
            elif pred["occupied"] and state == "ready":
                state = "occupied"
                out.append(pred)
            elif not pred["occupied"] and state == "occupied":
                state = "needs_clearing"
                out.append(pred)
    return sorted(out, key=lambda p: p["t"])


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def score(labels: list[dict], preds: list[dict], table_hours: float) -> dict:
    preds = as_seen_by_staff(preds, labels)
    out = {"table_hours": table_hours}
    for kind, occupied, name in (("party_left", False, "departure"), ("party_seated", True, "arrival")):
        delays, missed, extra, total = [], 0, 0, 0
        tables = {x["table_id"] for x in labels} | {x["table_id"] for x in preds}
        for tid in tables:
            lt = [x["t"] for x in labels if x["table_id"] == tid and x["type"] == kind]
            pt = [x["t"] for x in preds if x["table_id"] == tid and x["occupied"] == occupied]
            d, m, e = match(lt, pt)
            delays += d
            missed += m
            extra += e
            total += len(lt)
        out[name] = {"labels": total, "missed": missed, "false": extra, "delays": delays}
    return out


def merge(scores: list[dict]) -> dict:
    out = {"table_hours": sum(s["table_hours"] for s in scores)}
    for name in ("departure", "arrival"):
        out[name] = {
            "labels": sum(s[name]["labels"] for s in scores),
            "missed": sum(s[name]["missed"] for s in scores),
            "false": sum(s[name]["false"] for s in scores),
            "delays": [d for s in scores for d in s[name]["delays"]],
        }
    return out


def summarise(s: dict) -> dict:
    th = max(s["table_hours"], 1e-9)
    out = {"table_hours": round(s["table_hours"], 2)}
    for name in ("departure", "arrival"):
        x = s[name]
        out[name] = {
            "labels": x["labels"], "missed": x["missed"],
            "missed_rate": round(x["missed"] / x["labels"], 4) if x["labels"] else None,
            "false": x["false"], "false_per_table_hour": round(x["false"] / th, 4),
            "delay_median_s": None if not x["delays"] else round(percentile(x["delays"], 0.5), 1),
            "delay_p90_s": None if not x["delays"] else round(percentile(x["delays"], 0.9), 1),
        }
    return out


TARGETS = {  # initial demo-stage targets from docs/PLAN.md section 6
    ("departure", "missed_rate"): 0.10, ("departure", "false_per_table_hour"): 0.2,
    ("departure", "delay_median_s"): 90, ("departure", "delay_p90_s"): 150,
    ("arrival", "missed_rate"): 0.05, ("arrival", "false_per_table_hour"): 0.1,
    ("arrival", "delay_median_s"): 30, ("arrival", "delay_p90_s"): 60,
}


def load_session(entry: dict, base: Path) -> dict:
    if entry["kind"] == "synthetic":
        from . import synth
        return synth.generate(entry["seed"], duration_s=entry.get("duration_s", 3600),
                              tags=tuple(entry.get("tags", ())))
    if entry["kind"] == "trace":  # boxes exported from a real clip + hand-made labels
        trace = json.loads((base / entry["trace"]).read_text())
        trace["labels"] = json.loads((base / entry["labels"]).read_text())
        trace.setdefault("tags", entry.get("tags", []))
        return trace
    raise ValueError(f"unknown session kind {entry['kind']}")


def evaluate_manifest(manifest_path: Path, split: str, cfg: FilterConfig | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text())
    sessions = [s for s in manifest["sessions"] if s["split"] == split]
    per_session, per_tag = [], {}
    for entry in sessions:
        trace = load_session(entry, manifest_path.parent)
        sc = score(trace["labels"], run_trace(trace, cfg), trace["table_hours"])
        per_session.append((entry["id"], sc))
        for tag in trace.get("tags") or ["plain"]:
            per_tag.setdefault(tag, []).append(sc)
    return {
        "split": split, "sessions": len(sessions),
        "data": sorted({s["kind"] for s in sessions}),
        "overall": summarise(merge([sc for _, sc in per_session])) if per_session else None,
        "by_tag": {tag: summarise(merge(v)) for tag, v in sorted(per_tag.items())},
        "by_session": {sid: summarise(sc) for sid, sc in per_session},
    }


def to_markdown(result: dict, cfg: FilterConfig) -> str:
    o = result["overall"]
    lines = [f"# CV evaluation report: split `{result['split']}`", ""]
    if result["data"] == ["synthetic"]:
        lines += ["> **Synthetic data only.** These numbers check the zone, filter and matching logic "
                  "against scripted traces. They are NOT evidence of accuracy on real footage. "
                  "Replace the manifest sessions with labelled recordings (AGENTS.md section 8).", ""]
    lines += [f"Sessions: {result['sessions']} · table-hours: {o['table_hours']} · filter: "
              f"enter {cfg.enter_window_s:g}s at {cfg.enter_ratio:.0%}, exit {cfg.exit_window_s:g}s at {cfg.exit_ratio:.0%}",
              "", "| Metric | Value | Count | Target | Met |", "|---|---|---|---|---|"]
    rows = [("departure", "missed_rate", "Missed departures", "missed", "labels"),
            ("departure", "false_per_table_hour", "False clearing alerts per table-hour", "false", None),
            ("departure", "delay_median_s", "Departure delay, median (s)", None, None),
            ("departure", "delay_p90_s", "Departure delay, p90 (s)", None, None),
            ("arrival", "missed_rate", "Missed arrivals", "missed", "labels"),
            ("arrival", "false_per_table_hour", "False occupancy per table-hour", "false", None),
            ("arrival", "delay_median_s", "Arrival delay, median (s)", None, None),
            ("arrival", "delay_p90_s", "Arrival delay, p90 (s)", None, None)]
    for group, key, title, num, den in rows:
        v, target = o[group][key], TARGETS[(group, key)]
        count = "" if num is None else (f"{o[group][num]} of {o[group][den]}" if den else str(o[group][num]))
        shown = "n/a" if v is None else (f"{v:.1%}" if key == "missed_rate" else f"{v}")
        tshown = f"≤ {target:.0%}" if key == "missed_rate" else f"≤ {target}"
        lines.append(f"| {title} | {shown} | {count} | {tshown} | {'n/a' if v is None else ('yes' if v <= target else 'NO')} |")
    lines += ["", "## By tag", "",
              "| Tag | Table-hours | Missed departures | False clearing / table-hour | Departure delay median (s) | False occupancy / table-hour |",
              "|---|---|---|---|---|---|"]
    for tag, s in result["by_tag"].items():
        d, a = s["departure"], s["arrival"]
        lines.append(f"| {tag} | {s['table_hours']} | {d['missed']} of {d['labels']} | "
                     f"{d['false_per_table_hour']} | {d['delay_median_s']} | {a['false_per_table_hour']} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="eval/manifest.json")
    ap.add_argument("--split", default="heldout", choices=["dev", "heldout"])
    ap.add_argument("--out")
    ap.add_argument("--json")
    ap.add_argument("--config", help='filter overrides as JSON, e.g. \'{"exit_window_s": 60}\'')
    args = ap.parse_args()
    cfg = FilterConfig.from_dict(json.loads(args.config) if args.config else None)
    result = evaluate_manifest(Path(args.manifest), args.split, cfg)
    md = to_markdown(result, cfg)
    print(md)
    if args.out:
        Path(args.out).write_text(md)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
