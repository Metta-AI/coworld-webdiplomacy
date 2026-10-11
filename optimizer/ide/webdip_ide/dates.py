"""The one way the IDE writes a date: Pacific Time, `Oct 11, 2:42 AM`.

The year is added only when it is not this year (`Dec 30, 2025, 9:05 PM`). Every page uses
these two functions, as the Jinja filters `when` and `day` (registered in `server.py`) or
called from a route module, so a time reads the same on the home page, the replay browser,
the dashboard and the reports. The agent panel's script (`static/chat.js`) writes the same
format, and leaves the day out for a message sent today.

The zone is named in one way only: the abbreviation that is right for that date, `PDT` in
summer and `PST` in winter (`when(value, zone=True)` gives `Oct 11, 2:42 AM PDT`), never a bare
"PT". A column of times has no label on each row: its heading's tooltip says "Pacific Time" and
a row's tooltip gives the time with its abbreviation. A time that stands alone in a sentence
carries the abbreviation. `chat.js` (`window.ide.when`) and `hooks.clock` follow the same rule.

A value may be seconds since 1970, a `datetime`, or an ISO string as found in `episode.json`
and in a report's front matter. A string that is only a date (`2026-10-11`) has no time to
show and is written as a day. A string that cannot be read is shown as it was written.

Standard library only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def _read(value) -> datetime | date | None:
    """The moment (or the plain day) `value` names, or None when it cannot be read."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, timezone.utc)
    else:
        text = str(value).strip()
        try:
            if len(text) == 10:
                return date.fromisoformat(text)
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:  # a time written without a zone is already Pacific: the lab writes Pacific
        return moment.replace(tzinfo=PACIFIC)
    return moment.astimezone(PACIFIC)


def _day(moment: date, now: datetime | None) -> str:
    this_year = (now or datetime.now(PACIFIC)).astimezone(PACIFIC).year
    return f"{moment:%b} {moment.day}" + ("" if moment.year == this_year else f", {moment.year}")


def day(value, now: datetime | None = None) -> str:
    """`Oct 11`, or `Oct 11, 2025` in another year. Empty for nothing."""
    if value is None or value == "":
        return ""
    moment = _read(value)
    return str(value) if moment is None else _day(moment, now)


def when(value, now: datetime | None = None, zone: bool = False) -> str:
    """`Oct 11, 2:42 AM`, or `Oct 11, 2025, 2:42 AM` in another year. Empty for nothing.

    With `zone`, the abbreviation for that date follows: `Oct 11, 2:42 AM PDT`, `Jan 5, 1:42 AM PST`."""
    if value is None or value == "":
        return ""
    moment = _read(value)
    if moment is None:
        return str(value)
    if not isinstance(moment, datetime):
        return _day(moment, now)
    return f"{_day(moment, now)}, {moment.hour % 12 or 12}:{moment:%M %p}" + (f" {moment:%Z}" if zone else "")
