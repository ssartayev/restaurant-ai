"""Read-only Gemini adapter. The caller supplies authorized aggregate figures."""
import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen


class ChatUnavailable(Exception):
    pass


def answer(question: str, report: dict) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL")
    if not key or not model:
        raise ChatUnavailable("Configure GEMINI_API_KEY and GEMINI_MODEL on the server.")
    payload = {
        "systemInstruction": {"parts": [{"text": (
            "You are a restaurant analytics assistant. Answer using only the report figures "
            "and period supplied. Distinguish missing data from zero. State when the report "
            "cannot answer the question. Never invent figures, orders, or staff activity."
        )}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps({
            "question": question, "report": report,
        })}]}],
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urlopen(request, timeout=20) as response:
            parts = json.load(response)["candidates"][0]["content"]["parts"]
            result = "\n".join(part["text"] for part in parts if "text" in part and not part.get("thought"))
    except (URLError, ValueError, KeyError, IndexError, TimeoutError):
        raise ChatUnavailable("The analytics assistant is temporarily unavailable.") from None
    if not result.strip():
        raise ChatUnavailable("The analytics assistant returned no answer.")
    return result


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
