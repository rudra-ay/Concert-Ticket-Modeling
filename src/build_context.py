"""Run every context feature build in dependency order. Rerunnable: all network calls hit the cache first.

    .venv/bin/python src/build_context.py            # real spine -> data/interim/
    CONTEXT_SPINE=... CONTEXT_OUT=... (dev spine)    # synthetic spine -> elsewhere

Order: CPI (independent) -> metro (writes venue_metro, used by tour_context and weather) -> calendar
-> tour_context -> weather (slow: >= 5 s per uncached Open-Meteo request).
"""
from __future__ import annotations

import sys

import build_cpi
import features_calendar
import features_metro
import features_tour_context
import features_weather

STEPS = {
    "cpi": build_cpi.main,
    "metro": features_metro.main,
    "calendar": features_calendar.main,
    "tour_context": features_tour_context.main,
    "weather": features_weather.main,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(STEPS)
    for name in wanted:
        print(f"== {name}")
        STEPS[name]()
