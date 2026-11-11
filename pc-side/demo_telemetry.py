"""
demo_telemetry.py  (hub)

Pseudo-telemetry for demos, standing in for NASA's Telemetry Stream Server (TSS).

Every run is different:
  - starting values and drain rates are randomized
  - readings wander naturally (heart rate, temperature, CO2, position)
  - random events happen during the EVA and trigger warnings:
      high heart rate (exertion), O2 leak, CO2 scrubber saturation,
      suit overheating, fast battery drain
  - the suit reacts: primary O2 hands over to secondary when low,
    and the CO2 scrubber switches from A to B when saturated

Settings (.env):
  DEMO_SPEED       simulated EVA minutes per real minute (default 10)
  DEMO_EVENT_RATE  chance of a new event each simulated minute (default 0.05,
                   about one every 20 EVA minutes); 0 turns events off
  DEMO_SEED        any number -> the same "random" EVA every time (handy for
                   rehearsing a demo); leave blank for a new EVA each run

Every reading changes continuously: consumables drain smoothly (two decimals,
so they tick down between any two questions), the EVA clock runs, position keeps
moving, and all sensors carry small jitter, with an identical repeat nudged by one
step. Asking the same question twice always gives a slightly different answer,
and oxygen and battery only ever go down.
The hub's guardrail accepts these values exactly or rounded to whole numbers.
Everything restarts when the hub restarts.
"""

import os
import random
import threading
import time

DEMO_SPEED = float(os.getenv("DEMO_SPEED", "10"))
DEMO_EVENT_RATE = float(os.getenv("DEMO_EVENT_RATE", "0.05"))
_seed = os.getenv("DEMO_SEED", "").strip()

EVENTS = {
    # name: (min minutes, max minutes)
    "exertion": (3, 6),
    "o2_leak": (4, 8),
    "co2_saturation": (5, 9),
    "overheat": (4, 7),
    "battery_drain": (5, 10),
}


def _quantize(x, step):
    """Round to the field's precision (1, 10, 0.1, 0.01); whole results become ints
    so they read naturally (100.0 -> 100)."""
    decimals = max(0, -int(round(__import__("math").log10(step)))) if step < 1 else 0
    r = round(round(x / step) * step, decimals)
    return int(r) if r == int(r) else r


class SuitSimulator:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        r = self.rng
        self.lock = threading.Lock()
        self.start = time.monotonic()
        self.minute = 0  # simulated minutes stepped so far

        # Randomized starting point and personality of this EVA
        self.o2_pri = r.uniform(96, 100)
        self.o2_sec = 100.0
        self.o2_rate = r.uniform(0.20, 0.35)          # % per minute
        self.battery = r.uniform(92, 100)
        self.battery_rate = r.uniform(0.10, 0.18)
        self.hr_base = r.uniform(78, 92)
        self.hr = self.hr_base
        self.temp = r.uniform(68, 72)
        self.co2 = r.uniform(500, 800)                # ppm
        self.pressure = 4.3
        self.scrubber = "A"
        self.distance = 0.0
        self.heading = r.uniform(0, 360)
        self.speed = 0.0                              # m per minute

        self.event = None
        self.event_left = 0
        self.o2_history = [self.o2_pri]
        self._last = {}  # previous live readings, so repeats can be nudged

    # ---------- one simulated minute ----------
    def _step(self):
        r = self.rng
        self.minute += 1

        # Maybe start a random event
        if self.event is None and r.random() < DEMO_EVENT_RATE:
            self.event = r.choice(list(EVENTS))
            lo, hi = EVENTS[self.event]
            self.event_left = r.randint(lo, hi)

        ev = self.event

        # Oxygen: primary drains, then secondary once primary is nearly empty
        drain = self.o2_rate * (4 if ev == "o2_leak" else 1) * r.uniform(0.8, 1.2)
        if self.o2_pri > 15:
            self.o2_pri = max(0, self.o2_pri - drain)
        else:
            self.o2_sec = max(0, self.o2_sec - drain)
        self.o2_history = (self.o2_history + [self.o2_pri + self.o2_sec])[-4:]

        # Suit pressure dips during a leak, recovers after
        target_p = 3.9 if ev == "o2_leak" else 4.3
        self.pressure += (target_p - self.pressure) * 0.5

        # Heart rate: wanders around its baseline, climbs during exertion
        target_hr = self.hr_base + (50 if ev == "exertion" else 0)
        self.hr += (target_hr - self.hr) * 0.4 + r.uniform(-4, 4)

        # Temperature: drifts near 70 F, climbs when overheating
        target_t = 85 if ev == "overheat" else 70
        self.temp += (target_t - self.temp) * 0.3 + r.uniform(-0.8, 0.8)

        # CO2: low with a working scrubber, rises while it's saturated
        if ev == "co2_saturation":
            self.co2 += r.uniform(400, 700)
        else:
            self.co2 += (650 - self.co2) * 0.4 + r.uniform(-60, 60)

        # Battery
        self.battery = max(0, self.battery - self.battery_rate
                           * (5 if ev == "battery_drain" else 1) * r.uniform(0.8, 1.2))

        # Movement: walk, pause, wander away from and back toward the lander
        if r.random() < 0.15:
            self.speed = r.choice([0, 0, 15, 25, 35])
        self.heading = (self.heading + r.uniform(-25, 25)) % 360
        direction = 1 if self.distance < 250 and r.random() < 0.6 else -1
        self.distance = max(0, self.distance + direction * self.speed * r.uniform(0.5, 1.0))

        # Event countdown; the suit "fixes" some problems when they end
        if ev:
            self.event_left -= 1
            if self.event_left <= 0:
                if ev == "co2_saturation":
                    self.scrubber = "B" if self.scrubber == "A" else "A"
                self.event = None

    # ---------- snapshot ----------
    def read(self):
        """Advance to the current simulated time and return a live snapshot."""
        with self.lock:
            sim_minutes = (time.monotonic() - self.start) / 60 * DEMO_SPEED
            target = int(sim_minutes)
            for _ in range(min(target - self.minute, 600)):  # catch up, but don't freeze
                self._step()
            return self.snapshot(frac=sim_minutes - target, live=True)

    def snapshot(self, frac=0.0, live=False):
        """frac: how far into the current simulated minute we are, so everything
        keeps moving smoothly between steps. live: add sensor jitter and make sure
        every reading differs from the previous one, like a real sensor feed."""
        ev = self.event
        jitter = random.uniform if live else (lambda a, b: 0.0)  # separate from the seeded sim

        # Consumables drain continuously, not in one-minute jumps
        drain = self.o2_rate * (4 if ev == "o2_leak" else 1) * frac
        on_secondary = self.o2_pri <= 15
        o2_pri_val = self.o2_pri if on_secondary else max(0, self.o2_pri - drain)
        o2_sec_val = max(0, self.o2_sec - drain) if on_secondary else self.o2_sec
        battery_val = max(0, self.battery - self.battery_rate
                          * (5 if ev == "battery_drain" else 1) * frac)

        # Position keeps moving between steps
        heading_val = (self.heading + jitter(-3, 3)) % 360
        distance_val = max(0, self.distance + self.speed * frac * 0.5 + jitter(-0.6, 0.6))

        # (field, raw value, precision, kind)
        #   clock / drain: move smoothly in one direction; precise enough that any
        #                  two readings a moment apart differ
        #   sensor:        jitters; a repeat of the previous reading is nudged one step
        o2_sec_raw = o2_sec_val if on_secondary else o2_sec_val + jitter(-0.15, 0.15)
        fields = [
            ("eva_time_min",            self.minute + frac,           0.01, "clock"),
            ("o2_primary_pct",          o2_pri_val,                   0.01, "drain"),
            ("o2_secondary_pct",        min(100, o2_sec_raw),         0.1 if not on_secondary else 0.01,
                                                                      "drain" if on_secondary else "sensor"),
            ("o2_primary_pressure_psi", 3000 * o2_pri_val / 100,      1,    "drain"),
            ("suit_pressure_psi",       self.pressure + jitter(-0.03, 0.03), 0.01, "sensor"),
            ("co2_ppm",                 self.co2 + jitter(-40, 40),   10,   "sensor"),
            ("heart_rate_bpm",          self.hr + jitter(-2.5, 2.5),  1,    "sensor"),
            ("battery_pct",             battery_val,                  0.01, "drain"),
            ("suit_temp_f",             self.temp + jitter(-0.4, 0.4), 0.1, "sensor"),
            ("distance_to_lander_m",    distance_val,                 1,    "sensor"),
            ("heading_deg",             heading_val,                  1,    "sensor"),
        ]
        out = {}
        for name, raw, step, kind in fields:
            value = _quantize(raw, step)
            last = self._last.get(name) if live else None
            if last is not None:
                if kind == "drain":
                    value = min(value, last)        # never creeps back up
                elif kind == "clock":
                    value = max(value, last)
                elif value == last:
                    # Nudge one step so a repeated question never gets an identical reading
                    limit = 100 if name.endswith("_pct") else float("inf")
                    for d in random.sample((-1, 1), 2):
                        nudged = _quantize(value + d * step, step)
                        if 0 <= nudged <= limit:
                            value = nudged
                            break
            if name == "heading_deg":
                value %= 360
            out[name] = value
        if live:
            self._last = dict(out)

        recent_drop = self.o2_history[0] - self.o2_history[-1]
        warnings = []
        if out["heart_rate_bpm"] > 120:
            warnings.append("HIGH HEART RATE")
        if on_secondary:
            warnings.append("PRIMARY O2 DEPLETED - ON SECONDARY")
        elif out["o2_primary_pct"] < 25:
            warnings.append("LOW PRIMARY O2")
        if len(self.o2_history) == 4 and recent_drop > self.o2_rate * 3 * 2.5:
            warnings.append("RAPID O2 LOSS")
        if out["suit_pressure_psi"] < 4.1:
            warnings.append("LOW SUIT PRESSURE")
        if out["co2_ppm"] > 2500:
            warnings.append("HIGH CO2")
        if out["suit_temp_f"] > 80:
            warnings.append("SUIT TEMPERATURE HIGH")
        if out["battery_pct"] < 20:
            warnings.append("LOW BATTERY")

        out["co2_scrubber"] = self.scrubber
        out["warnings"] = warnings
        return out


_sim = SuitSimulator(int(_seed) if _seed.lstrip("-").isdigit() else (_seed or None))


def get_demo_telemetry():
    return _sim.read()


if __name__ == "__main__":
    # Preview a whole simulated EVA instantly:  python demo_telemetry.py
    import json
    sim = SuitSimulator(int(_seed) if _seed.lstrip("-").isdigit() else None)
    for minute in range(0, 241, 10):
        while sim.minute < minute:
            sim._step()
        print(json.dumps(sim.snapshot()))