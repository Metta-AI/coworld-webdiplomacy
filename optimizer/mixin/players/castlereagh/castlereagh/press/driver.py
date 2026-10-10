"""Press part (c), the press driver: one event-driven wake loop per movement phase.

This is the only part that knows phase timing. It replaces the lab's open / negotiate /
commit wakes, which left the bot deaf for the last ~75 s of every phase and for 2+ minutes
once it had used its wakes. Here every wake is the same kind of agent run, started by an
event:

- `phase_start`: the phase began (so the agent can open negotiations);
- `press`: new messages from other powers arrived.

After new press, the driver waits for `PRESS_DEBOUNCE_S` of quiet so a burst of messages
becomes one wake, but never longer than `PRESS_MAX_DEBOUNCE_S` after the first unread
message, and not at all when waiting would leave no room for a wake before the lock. Wakes
stop at `PRESS_MAX_WAKES`. The loop ends at the lock, `PRESS_FINAL_MARGIN_S` before the
deadline, when the caller saves the last committed orders with Ready.

The driver is pure scheduling: polling, phase-end detection and the wake itself are
callbacks, and the clock is injectable, so tests run it with a fake clock.
"""

import time

from castlereagh import config


class PressDriver:
    def __init__(self, poll, phase_over, wake, clock=time.time, sleep=time.sleep):
        """`poll()` -> number of new messages from other powers since the last poll;
        `phase_over()` -> True once the phase has ended early (every seat Ready);
        `wake(trigger, seconds)` runs one agent wake that must finish within `seconds`."""
        self.poll, self.phase_over, self.wake = poll, phase_over, wake
        self.clock, self.sleep = clock, sleep

    def run(self, deadline):
        """Drive one phase until the lock. Returns a summary dict for the decision log."""
        lock = deadline - config.PRESS_FINAL_MARGIN_S
        now = self.clock()
        # The phase start is an event that is already "quiet": it wakes at once.
        trigger, first_unread, last_arrival = "phase_start", now, now - config.PRESS_DEBOUNCE_S
        wakes = arrivals = 0
        unanswered = 0  # messages still unread when the lock came
        while True:
            now = self.clock()
            if now >= lock:
                end = "lock"
                break
            if self.phase_over():
                end = "phase_over"
                break
            fresh = self.poll()
            if fresh:
                arrivals += fresh
                unanswered += fresh
                if first_unread is None:
                    first_unread = now
                last_arrival = now
            if first_unread is not None and wakes < config.PRESS_MAX_WAKES:
                room = lock - now
                quiet = now - last_arrival >= config.PRESS_DEBOUNCE_S
                overdue = now - first_unread >= config.PRESS_MAX_DEBOUNCE_S
                last_chance = room - config.PRESS_DEBOUNCE_S < config.PRESS_MIN_WAKE_S
                seconds = min(config.PRESS_WAKE_SECONDS, room - 1.0)
                if (quiet or overdue or last_chance) and seconds >= config.PRESS_MIN_WAKE_S:
                    first_unread = last_arrival = None
                    unanswered = 0
                    wakes += 1
                    self.wake(trigger, seconds)
                    trigger = "press"
                    continue  # re-check at once: press may have arrived during the wake
            self.sleep(config.PRESS_POLL_S)
        return {"wakes": wakes, "press_arrivals": arrivals, "unanswered_at_lock": unanswered, "end": end}
