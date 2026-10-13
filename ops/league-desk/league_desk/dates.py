from datetime import datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def timestamp(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("API timestamp must include a timezone")
    return parsed.timestamp()


def when(value):
    return datetime.fromtimestamp(value, PACIFIC).strftime("%b %d, %I:%M %p %Z") if value is not None else "unknown"
