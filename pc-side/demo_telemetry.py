"""
demo_telemetry.py  (hub)

Pseudo-telemetry for demos, standing in for NASA's Telemetry Stream Server (TSS).

Values change over time like a real EVA: oxygen and battery drain, heart rate
rises and falls, and every so often a heart-rate spike triggers a warning, so
students can watch the caution and warning system react.

DEMO_SPEED in .env sets how fast simulated time runs (default 10 = one real
minute is ten EVA minutes), so changes are visible during a class period.
Everything restarts when the hub restarts.

Values are whole numbers (or one decimal) so the hub's guardrail can match
spoken numbers against them exactly.
"""

import math
import os
import random
import time

DEMO_SPEED = float(os.getenv("DEMO_SPEED", "10"))
_START = time.monotonic()


def get_demo_telemetry():
    m = (time.monotonic() - _START) / 60 * DEMO_SPEED  # simulated EVA minutes

    o2_primary = max(0, round(100 - 0.25 * m))
    battery = max(0, round(100 - 0.15 * m))

    heart_rate = 88 + 10 * math.sin(m / 4) + random.uniform(-2, 2)
    spike = int(m) % 30 in (20, 21, 22)          # a 3-minute spike every 30 EVA minutes
    if spike:
        heart_rate += 45
    heart_rate = round(heart_rate)

    telemetry = {
        "eva_time_min": round(m),
        "o2_primary_pct": o2_primary,
        "o2_secondary_pct": 100,
        "o2_primary_pressure_psi": round(3000 * o2_primary / 100),
        "suit_pressure_psi": 4.3,
        "co2_scrubber": "A",
        "heart_rate_bpm": heart_rate,
        "battery_pct": battery,
        "suit_temp_f": round(70 + 3 * math.sin(m / 9)),
        "distance_to_lander_m": round(180 * abs(math.sin(m / 25))),
        "heading_deg": round(m * 7) % 360,
    }

    warnings = []
    if heart_rate > 120:
        warnings.append("HIGH HEART RATE")
    if o2_primary < 25:
        warnings.append("LOW PRIMARY O2")
    if battery < 20:
        warnings.append("LOW BATTERY")
    telemetry["warnings"] = warnings
    return telemetry


if __name__ == "__main__":
    # Quick look: python demo_telemetry.py
    import json
    print(json.dumps(get_demo_telemetry(), indent=2))