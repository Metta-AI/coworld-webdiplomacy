"""The press driver's wake scheduling, on a fake clock."""

import unittest

import _support
from castlereagh import config
from castlereagh.press.driver import PressDriver


class Harness:
    """Press arrives at scheduled times; each wake takes `wake_cost` seconds."""

    def __init__(self, arrivals, wake_cost=10.0, start=1000.0):
        self.clock = _support.FakeClock(start)
        self.arrivals = sorted(start + t for t in arrivals)
        self.wakes = []  # (start offset, trigger, seconds allowed)
        self.wake_cost = wake_cost
        self.start = start
        self.over_at = None

    def poll(self):
        due = [t for t in self.arrivals if t <= self.clock.now]
        self.arrivals = [t for t in self.arrivals if t > self.clock.now]
        return len(due)

    def phase_over(self):
        return self.over_at is not None and self.clock.now >= self.start + self.over_at

    def wake(self, trigger, seconds):
        self.wakes.append((round(self.clock.now - self.start, 1), trigger, round(seconds, 1)))
        self.clock.now += min(self.wake_cost, seconds)

    def run(self, phase_seconds=240):
        driver = PressDriver(self.poll, self.phase_over, self.wake, self.clock, self.clock.sleep)
        return driver.run(self.start + phase_seconds)


class DriverTest(unittest.TestCase):
    def test_phase_start_wakes_at_once(self):
        h = Harness([])
        summary = h.run()
        self.assertEqual(h.wakes[0][:2], (0.0, "phase_start"))
        self.assertEqual(summary["wakes"], 1)
        self.assertEqual(summary["end"], "lock")

    def test_burst_of_press_is_debounced_into_one_wake(self):
        h = Harness([30, 31, 32, 33])
        h.run()
        press = [w for w in h.wakes if w[1] == "press"]
        self.assertEqual(len(press), 1)
        # Woken after 5 s of quiet following the last message (33 s), not before.
        self.assertGreaterEqual(press[0][0], 33 + config.PRESS_DEBOUNCE_S)
        self.assertLess(press[0][0], 33 + config.PRESS_DEBOUNCE_S + 2 * config.PRESS_POLL_S)

    def test_steady_stream_cannot_starve_the_agent(self):
        h = Harness([30 + 2 * k for k in range(30)])  # a message every 2 s: never 5 s of quiet
        h.run()
        first = next(w for w in h.wakes if w[1] == "press")
        self.assertLessEqual(first[0], 30 + config.PRESS_MAX_DEBOUNCE_S + config.PRESS_POLL_S)

    def test_hears_press_near_the_deadline(self):
        lock = 240 - config.PRESS_FINAL_MARGIN_S
        h = Harness([lock - 12])  # arrives with too little room to wait for the full debounce
        summary = h.run()
        late = [w for w in h.wakes if w[1] == "press"]
        self.assertEqual(len(late), 1)
        start, _, allowed = late[0]
        self.assertLess(start, lock - 12 + config.PRESS_DEBOUNCE_S)  # did not wait out the debounce
        self.assertGreaterEqual(allowed, config.PRESS_MIN_WAKE_S)
        self.assertLessEqual(start + allowed, lock)  # the wake ends before the lock
        self.assertEqual(summary["unanswered_at_lock"], 0)

    def test_no_wake_too_short_to_be_useful(self):
        lock = 240 - config.PRESS_FINAL_MARGIN_S
        h = Harness([lock - 3])
        summary = h.run()
        self.assertEqual([w for w in h.wakes if w[1] == "press"], [])
        self.assertEqual(summary["unanswered_at_lock"], 1)

    def test_every_wake_ends_before_the_lock(self):
        lock = 240 - config.PRESS_FINAL_MARGIN_S
        h = Harness([20 * k for k in range(1, 12)], wake_cost=1e9)  # wakes use all their time
        h.run()
        for start, _, allowed in h.wakes:
            self.assertLessEqual(start + allowed, lock)

    def test_wake_cap(self):
        h = Harness([7 * k for k in range(1, 40)], wake_cost=1.0)
        summary = h.run()
        self.assertEqual(len(h.wakes), config.PRESS_MAX_WAKES)
        self.assertGreater(summary["unanswered_at_lock"], 0)

    def test_stops_when_the_phase_ends_early(self):
        h = Harness([])
        h.over_at = 50
        summary = h.run()
        self.assertEqual(summary["end"], "phase_over")
        self.assertLess(h.clock.now - h.start, 52)


if __name__ == "__main__":
    unittest.main()
