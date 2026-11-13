"""Read-only Gemini adapter. The caller supplies authorized aggregate figures."""
import json
import os
import re
import ssl
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


class ChatUnavailable(Exception):
    pass


def answer(question: str, report: dict) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL")
    if not key or not model:
        raise ChatUnavailable("Configure GEMINI_API_KEY and GEMINI_MODEL on the server.")
    payload = {
        "systemInstruction": {"parts": [{"text": (
            "You are Mise's assistant. Answer general questions normally. For restaurant-specific "
            "figures, use only the supplied report and period. Explain missing data and never invent figures. "
            "Mise includes a live operations board for tables and waitlists, Kitchen order tickets, "
            "Recordings with camera overlays and an editable floor plan, History reports, Assistant, "
            "and Cameras for configuring edge workers. Recorded video review is session-local. "
            "Live camera workers send table observations; the browser has no live video player."
        )}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps({
            "question": question, "report": report,
        })}]}],
    }
    context = ssl.create_default_context(cafile=certifi.where())
    failure = "empty response"
    fallback = "gemini-2.5-flash"
    for candidate in dict.fromkeys((model, "gemini-3.1-flash-lite", fallback)):
        config = {"maxOutputTokens": 2048}
        if candidate == fallback:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}:generateContent",
            data=json.dumps(payload | {"generationConfig": config}).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        try:
            with urlopen(request, timeout=20, context=context) as response:
                parts = json.load(response)["candidates"][0]["content"]["parts"]
            result = "\n".join(part["text"] for part in parts if "text" in part and not part.get("thought"))
            if result.strip():
                return result
            failure = "empty response"
        except HTTPError as exc:
            failure = f"HTTP {exc.code}"
            if exc.code in (400, 401, 403):
                raise ChatUnavailable(f"Gemini rejected the request (HTTP {exc.code}). Check the API key and project access.") from None
            if exc.code not in (404, 408, 429, 500, 502, 503, 504):
                raise ChatUnavailable(f"Gemini returned HTTP {exc.code}.") from None
        except (TimeoutError, URLError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            failure = "request timed out" if isinstance(reason, TimeoutError) else "connection failed"
        except (ValueError, KeyError, IndexError, TypeError):
            failure = "response contained no readable answer"
    raise ChatUnavailable(f"Gemini could not reply ({failure}). Please try again.")



def overview_answer(question: str) -> str | None:
    query = question.casefold().strip().rstrip("?!.")
    if not re.fullmatch(
        r"(?:what about is this (?:web ?site|web ?app|app)|what is (?:this (?:web ?site|web ?app|app)|mise)(?: about)?|"
        r"(?:describe|tell me about|give me (?:info|information) about) (?:this (?:web ?site|web ?app|app)|mise))",
        query,
    ):
        return None
    return (
        "Mise helps restaurant staff manage tables, waitlists, and kitchen orders. "
        "Recordings lets you review camera footage with detection boxes and an editable floor plan. "
        "History shows saved restaurant metrics, and Assistant answers questions about them. "
        "Cameras configures edge workers that send table observations to the Live board."
    )

def peak_answer(question: str, report: dict) -> str | None:
    """Answer straightforward peak-arrival questions from the selected report."""
    query = question.casefold()
    if not re.search(r"\b(busiest|peak)\s+(time|hour|day)", query):
        return None
    peaks = report["peaks"]
    hours, days = Counter(), Counter()
    for slot in peaks["by_hour"]:
        hours[slot["hour"]] += slot["arrivals"]
        days[slot["weekday"]] += slot["arrivals"]
    if not hours:
        return "No party arrivals were recorded in the selected period."

    def winners(counts, label):
        maximum = max(counts.values())
        return ", ".join(label(value) for value in sorted(counts) if counts[value] == maximum), maximum

    names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    hour, hour_count = winners(hours, lambda value: f"{value:02d}:00")
    day, day_count = winners(days, names.__getitem__)
    return (f"Busiest arrival hour: {hour} ({hour_count} arrivals per listed hour).\n"
            f"Busiest day of the week: {day} ({day_count} arrivals per listed weekday).\n"
            f"Based on recorded party arrivals in the selected period, using {peaks['timezone']}.")

def summarize(report: dict) -> str:
    """Render a reproducible answer for report shortcuts without a model call."""
    summary, orders, peaks = report["summary"], report["orders"], report["peaks"]
    label = {"week": "Weekly", "month": "Monthly", "year": "Yearly", "custom": "Custom"}[report["period"]]
    lines = [
        f"{label} summary",
        f"• Table occupancy: {summary['occupancy_pct']}%",
        f"• Completed table turns: {summary['turns']}",
        f"• Kitchen tickets sent: {orders['tickets_sent']}",
    ]
    for title, value in [
        ("Median kitchen prep", orders["median_kitchen_minutes"]),
        ("Median ready to served", orders["median_ready_to_served_minutes"]),
        ("Median departure to ready", summary["median_departure_to_ready_minutes"]),
    ]:
        lines.append(f"• {title}: {f'{value} min' if value is not None else 'No completed intervals'}")
    busiest = max(peaks["by_hour"], key=lambda slot: slot["arrivals"], default=None)
    if busiest:
        day = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[busiest["weekday"]]
        lines.append(f"• Busiest arrival hour: {day} {busiest['hour']:02d}:00 ({busiest['arrivals']} arrivals, {peaks['timezone']})")
    else:
        lines.append("• No arrivals recorded in this period.")
    return "\n".join(lines)
