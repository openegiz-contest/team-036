#!/usr/bin/env python3
"""Unit tests of the digital pit model (stdlib only): python3 team/tests/test_sim.py"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pit import geometry as geo  # noqa: E402
from pit.sim import CAP_T, FLEET, Mine  # noqa: E402
from pit.twins import definitions, snapshot  # noqa: E402


def kpis(scn, seed=21, hours=3):
    m = Mine(seed)
    m.run(2 * 3600)
    if scn:
        m.scenario(scn, True)
    for w in m.worlds.values():
        w.hist.clear()
        w._last_snap = -1e9
    m.run(hours * 3600)
    return {k: w.kpi(hours * 3600) for k, w in m.worlds.items()}, m


class PitTests(unittest.TestCase):
    def test_roads_are_realistic(self):
        for s in geo.build_segments().values():
            self.assertLess(abs(s.grade_pct), 10.5, s.id)       # haul-road grades up to ~10 %
            self.assertGreater(s.length, 150)

    def test_deterministic(self):
        a, b = Mine(5), Mine(5)
        a.run(3600)
        b.run(3600)
        self.assertEqual(a.worlds["dispatcher"].crushed_t, b.worlds["dispatcher"].crushed_t)

    def test_payload_and_bin_limits(self):
        m = Mine(3)
        for _ in range(4 * 1800):
            m.step(2.0)
            for w in m.worlds.values():
                assert 0 <= w.bin_t <= 600.0 + 1e-6
                assert all(0 <= t.payload <= CAP_T * 1.04 for t in w.trucks)

    def test_dispatcher_beats_fixed_when_shovel_fails(self):
        k, _ = kpis("shovel_down")
        self.assertLess(k["dispatcher"]["idle_pct"], k["baseline"]["idle_pct"])
        self.assertGreater(k["dispatcher"]["ore_rate"], k["baseline"]["ore_rate"])

    def test_crusher_down_dispatcher_diverts_ore_to_rom(self):
        k, m = kpis("crusher_down")
        self.assertGreater(m.worlds["dispatcher"].rom_t, 1000)
        self.assertLess(k["dispatcher"]["idle_pct"], 0.5 * k["baseline"]["idle_pct"])

    def test_closed_ramp_gets_no_new_traffic(self):
        m = Mine(21)
        m.run(2 * 3600)
        m.scenario("ramp_a_closed", True)
        w = m.worlds["dispatcher"]
        m.run(900)                                    # trucks already on the ramp may finish it
        entered = 0
        for _ in range(1800):
            m.step(2.0)
            entered += sum(1 for t in w.trucks if t.seg is w.segs["UA"])
        self.assertEqual(entered, 0)
        self.assertGreater(sum(t.trips for t in w.trucks), 10)

    def test_scenario_is_reversible(self):
        m = Mine(2)
        m.run(3600)
        for name in ("rain", "ramp_a_closed", "shovel_down", "crusher_down", "blast_f1", "truck_down"):
            m.scenario(name, True)
            m.run(600)
            m.scenario(name, False)
        m.run(2 * 3600)
        w = m.worlds["dispatcher"]
        self.assertFalse(any(w.active.values()))
        self.assertGreater(w.kpi(3600)["ore_rate"], 1500)
        self.assertTrue(all(t.state != "repair" for t in w.trucks))

    def test_twins(self):
        d = definitions()
        self.assertEqual(len(d), 5 + FLEET + 3 + 3 + 12)
        json.dumps(d)
        snap = snapshot(Mine(1))
        self.assertEqual(set(snap), {k.split(":")[1] for k in d})


if __name__ == "__main__":
    unittest.main(verbosity=1)
