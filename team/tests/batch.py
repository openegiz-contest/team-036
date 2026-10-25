#!/usr/bin/env python3
"""Offline validation: dispatcher vs the best fixed assignment, steady state and under what-if scenarios.

    python3 team/tests/batch.py            # table for SUBMISSION.md
"""
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pit.sim import Mine, SCENARIOS  # noqa: E402

SEEDS = (11, 12, 13, 14, 15)
WARM_S, PRE_S, EVENT_S, POST_S = 2 * 3600, 1 * 3600, 3 * 3600, 1 * 3600


def run(seed, scenario):
    m = Mine(seed)
    m.run(WARM_S)
    if scenario:
        m.run(PRE_S)
        m.scenario(scenario, True)
        for w in m.worlds.values():
            w.hist.clear()
            w._last_snap = -1e9
        m.run(EVENT_S)
    else:
        for w in m.worlds.values():
            w.hist.clear()
            w._last_snap = -1e9
        m.run(EVENT_S)
    return {n: w.kpi(EVENT_S) for n, w in m.worlds.items()}


def main():
    rows = []
    for sc in [None] + list(SCENARIOS):
        res = [run(s, sc) for s in SEEDS]
        def mean(world, key):
            return st.mean(r[world][key] for r in res)
        rows.append((sc or "steady", mean("dispatcher", "idle_pct"), mean("baseline", "idle_pct"),
                     mean("dispatcher", "ore_rate"), mean("baseline", "ore_rate"),
                     mean("dispatcher", "crusher_starved_pct"), mean("baseline", "crusher_starved_pct")))
    print(f"{'scenario':16s} {'idle% disp':>10s} {'idle% base':>10s} {'ore t/h disp':>12s} {'ore t/h base':>12s} "
          f"{'cr.starve% d':>12s} {'cr.starve% b':>12s}")
    for r in rows:
        print(f"{r[0]:16s} {r[1]:10.1f} {r[2]:10.1f} {r[3]:12.0f} {r[4]:12.0f} {r[5]:12.1f} {r[6]:12.1f}")


if __name__ == "__main__":
    main()
