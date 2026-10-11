"""The one date format (`webdip_ide/dates.py`): Pacific, `Oct 11, 2:42 AM`, the year only when it differs."""

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from webdip_ide import dates

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=dates.PACIFIC)


class DateTests(unittest.TestCase):
    def test_when_is_pacific_whatever_the_input(self):
        moment = datetime(2026, 10, 11, 9, 42, tzinfo=timezone.utc)  # 2:42 AM PDT
        for value in (moment, moment.timestamp(), "2026-10-11T09:42:00Z", "2026-10-11T09:42:00+00:00"):
            self.assertEqual(dates.when(value, NOW), "Oct 11, 2:42 AM", value)
        self.assertEqual(dates.when("2026-10-11T19:05:00Z", NOW), "Oct 11, 12:05 PM")
        self.assertEqual(dates.when("2026-10-11T07:00:00Z", NOW), "Oct 11, 12:00 AM")
        # Winter: PST is eight hours behind UTC.
        self.assertEqual(dates.when("2026-01-05T09:42:00Z", NOW), "Jan 5, 1:42 AM")

    def test_the_zone_is_the_abbreviation_for_that_date(self):
        self.assertEqual(dates.when("2026-10-11T09:42:00Z", NOW, zone=True), "Oct 11, 2:42 AM PDT")
        self.assertEqual(dates.when("2026-01-05T09:42:00Z", NOW, zone=True), "Jan 5, 1:42 AM PST")
        self.assertEqual(dates.when("2026-10-11 02:44", NOW, zone=True), "Oct 11, 2:44 AM PDT")  # written in Pacific
        self.assertEqual(dates.when("2026-10-11", NOW, zone=True), "Oct 11")  # a plain day has no time, so no zone

    def test_no_page_or_script_writes_a_bare_pt(self):
        """One name for the zone: PDT or PST by date. "PT" beside a time is the mistake this guards."""
        package = Path(dates.__file__).parent
        for path in [*package.glob("templates/*.html"), *package.glob("static/*.js"), *package.glob("*.py")]:
            self.assertIsNone(re.search(r"\sPT\b", path.read_text()), path.name)

    def test_the_agent_is_told_the_time_with_the_same_abbreviation(self):
        from webdip_ide import hooks

        summer = datetime(2026, 10, 11, 11, 53, 20, tzinfo=timezone.utc).timestamp()
        self.assertEqual(hooks.clock(summer), "04:53:20 PDT")
        self.assertEqual(hooks.clock(datetime(2026, 1, 5, 9, 42, tzinfo=timezone.utc).timestamp()), "01:42:00 PST")

    def test_the_year_shows_only_when_it_is_not_this_year(self):
        self.assertEqual(dates.when("2025-12-31T05:05:00Z", NOW), "Dec 30, 2025, 9:05 PM")
        self.assertEqual(dates.day("2025-12-31T05:05:00Z", NOW), "Dec 30, 2025")
        self.assertEqual(dates.day("2026-10-11T09:42:00Z", NOW), "Oct 11")

    def test_a_time_without_a_zone_is_already_pacific(self):
        # The reports page's "file changed" value is written in Pacific without a zone.
        self.assertEqual(dates.when("2026-10-11 02:44", NOW), "Oct 11, 2:44 AM")

    def test_a_plain_day_has_no_time_to_show(self):
        self.assertEqual(dates.when("2026-10-11", NOW), "Oct 11")
        self.assertEqual(dates.day("2025-03-02", NOW), "Mar 2, 2025")

    def test_nothing_and_nonsense(self):
        for empty in (None, ""):
            self.assertEqual((dates.when(empty), dates.day(empty)), ("", ""))
        self.assertEqual(dates.when("last Tuesday", NOW), "last Tuesday")
        self.assertEqual(dates.day("last Tuesday", NOW), "last Tuesday")

    def test_templates_have_the_filters(self):
        from webdip_ide import server

        self.assertIs(server.templates.env.filters["when"], dates.when)
        self.assertIs(server.templates.env.filters["day"], dates.day)


if __name__ == "__main__":
    unittest.main()
