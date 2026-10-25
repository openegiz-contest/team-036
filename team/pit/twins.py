"""Twin definitions and telemetry snapshots for the digital pit (Eclipse Ditto things)."""
from . import geometry as geo
from .sim import FLEET, SCENARIOS, Mine

NS = "org.openegiz.pit"
PIT = f"{NS}:pit-01"

TRUCK_STATES_RU = {
    "to_shovel": "едет к экскаватору", "queue_shovel": "очередь у экскаватора", "loading": "погрузка",
    "to_dump": "гружёный едет на разгрузку", "queue_dump": "очередь на разгрузку", "dumping": "разгрузка",
    "refuel": "заправка", "repair": "поломка", "blocked": "ожидание решения",
}


def _f(value, unit=None):
    p = {"value": value}
    if unit:
        p["unit"] = unit
    return p


def _r(x, n=1):
    return round(float(x), n)


def snapshot(mine: Mine, extra=None, speedup=0):
    """name -> {feature: properties}; one entry per twin. Truck/shovel/site data come from the shown world,
    the KPI block compares both worlds."""
    extra = extra or {}
    w = mine.shown
    disp, base = mine.worlds["dispatcher"], mine.worlds["baseline"]
    kd, kb = disp.kpi(3600), base.kpi(3600)
    out = {}
    total_ore = w.sites["crusher-01"].tonnes + w.sites["rompad-01"].tonnes

    out["pit-01"] = {
        "clock": _f(w.clock()), "clock_min": _f(_r(w.now / 60), "min"),
        "view": _f(mine.view), "weather": _f("rain" if w.rain else "dry"),
        "ore_hauled_t": _f(_r(total_ore), "t"), "waste_t": _f(_r(w.waste_t), "t"),
        "feed_grade": _f(round(w.feed_grade, 3), "% Cu"), "speedup": _f(speedup, "x"),
    }
    dd = {
        "decisions_total": _f(disp.decisions),
        "last_decision": _f(disp.last_decision),
        "decision_log": _f("\n".join(disp.log)),
        "idle_pct_dispatch": _f(_r(kd["idle_pct"]), "%"), "idle_pct_baseline": _f(_r(kb["idle_pct"]), "%"),
        "ore_rate_dispatch": _f(_r(kd["ore_rate"], 0), "t/h"), "ore_rate_baseline": _f(_r(kb["ore_rate"], 0), "t/h"),
        "crusher_starved_dispatch": _f(_r(kd["crusher_starved_pct"]), "%"),
        "crusher_starved_baseline": _f(_r(kb["crusher_starved_pct"]), "%"),
        "queue_shovel_dispatch": _f(_r(kd["queue_shovel_pct"]), "%"),
        "queue_shovel_baseline": _f(_r(kb["queue_shovel_pct"]), "%"),
        "queue_dump_dispatch": _f(_r(kd["queue_dump_pct"]), "%"),
        "queue_dump_baseline": _f(_r(kb["queue_dump_pct"]), "%"),
        "idle_saved_h": _f(_r(kb["idle_h_total"] - kd["idle_h_total"], 2), "h"),
        "ore_gain_t": _f(_r(disp.sites["crusher-01"].tonnes + disp.sites["rompad-01"].tonnes
                            - base.sites["crusher-01"].tonnes - base.sites["rompad-01"].tonnes, 0), "t"),
        "scenario_log": _f(extra.get("scenario_log", "")),
    }
    for name in SCENARIOS:
        dd[f"sc_{name}"] = _f(1 if w.active[name] else 0)
    out["dispatcher-01"] = dd

    for t in w.trucks:
        x, y, z, h = (list(t.pos) + [0.0])[:4]
        out[t.id] = {
            "state": _f(t.state), "payload": _f(_r(t.payload), "t"), "speed": _f(_r(t.speed), "km/h"),
            "position": {"x": _r(x), "y": _r(y), "z": _r(z), "heading": round(h, 3)},
            "segment": _f(t.seg.id if t.seg else ""),
            "shovel": _f(t.shovel.id if t.shovel else ""),
            "destination": _f(t.dest.id if (t.dest and t.payload > 0) else ""),
            "fuel": _f(_r(t.fuel), "%"), "trips_total": _f(t.trips, "trips"),
            "queue_shovel_s": _f(_r(t.t["queue_shovel"], 0), "s"), "queue_dump_s": _f(_r(t.t["queue_dump"], 0), "s"),
            "idle_s": _f(_r(t.t["queue_shovel"] + t.t["queue_dump"] + t.t["blocked"], 0), "s"),
            "cycle_min": _f(_r(t.last_cycle_min), "min"),
            "grade": _f(round(t.grade, 3), "% Cu"),
        }
    for sh in w.shovels.values():
        tot = max(1.0, w.now)
        out[sh.id] = {
            "state": _f(sh.state), "queue_len": _f(len(sh.queue), "trucks"),
            "current_truck": _f(sh.current.id if sh.current else ""),
            "tonnes_total": _f(_r(sh.tonnes, 0), "t"), "passes_total": _f(sh.passes),
            "utilization_pct": _f(_r(100 * sh.t_work / tot), "%"), "starved_pct": _f(_r(100 * sh.t_starved / tot), "%"),
        }
    for fid, info in geo.FACES.items():
        sh = next(s for s in w.shovels.values() if s.face == fid)
        state = "blast_closed" if sh.blast else ("equipment_down" if sh.down else "open")
        out[f"face-{fid}"] = {
            "state": _f(state), "grade": _f(round(w.face_grade[fid], 3), "% Cu"),
            "mined_t": _f(_r(w.face_mined[fid], 0), "t"),
            "remaining_t": _f(_r(info["reserve_t"] - w.face_mined[fid], 0), "t"),
        }
    for sid, seg in w.segs.items():
        out[f"road-{sid.lower()}"] = {
            "status": _f("closed" if seg.closed else ("slow" if seg.speed_factor < 1 else "open")),
            "trucks_on": _f(seg.trucks, "trucks"), "speed_factor": _f(round(seg.speed_factor, 2)),
        }
    cr = w.sites["crusher-01"]
    out["crusher-01"] = {
        "state": _f("down" if cr.down else w.crusher_state), "bin_level_t": _f(_r(w.bin_t), "t"),
        "bin_pct": _f(_r(100 * w.bin_t / 600.0), "%"), "queue_len": _f(len(cr.queue) + len(cr.dumping), "trucks"),
        "throughput_tph": _f(_r((kd if mine.view == "dispatcher" else kb)["crush_rate"], 0), "t/h"),
        "feed_grade": _f(round(w.feed_grade, 3), "% Cu"), "tonnes_total": _f(_r(w.crushed_t, 0), "t"),
        "starved_pct": _f(_r(100 * w.crusher_starved_s / max(1.0, w.now)), "%"),
    }
    rom = w.sites["rompad-01"]
    out["rompad-01"] = {"stock_t": _f(_r(w.rom_t, 0), "t"), "queue_len": _f(len(rom.queue) + len(rom.dumping), "trucks"),
                        "tonnes_total": _f(_r(rom.tonnes, 0), "t")}
    wd = w.sites["wastedump-01"]
    out["wastedump-01"] = {"queue_len": _f(len(wd.queue) + len(wd.dumping), "trucks"), "tonnes_total": _f(_r(w.waste_t, 0), "t")}
    return out


def _attr(kind, name, **kw):
    a = {"_isType": False, "_parents": PIT, "kind": kind, "name": name}
    a.update(kw)
    return a


def definitions():
    """All twins of the digital pit, with static attributes (geometry included) and initial features."""
    mine = Mine(7)
    snap = snapshot(mine)
    w = mine.shown
    attrs = {
        "pit-01": {"_isType": False, "kind": "pit", "name": "Карьер «Алтын-Тау» (вымышленный)",
                   "a_rim": geo.A_RIM, "b_rim": geo.B_RIM, "depth": geo.DEPTH, "bench_h": geo.BENCH_H,
                   "s_bottom": geo.S_BOTTOM, "fleet": FLEET,
                   "scenarios": {k: v for k, v in SCENARIOS.items()}},
        "dispatcher-01": _attr("dispatcher", "Диспетчер карьера (цифровая диспетчерская)"),
        "crusher-01": _attr("crusher", "Дробилка первичного дробления ДК-1", rated_tph=2500, bin_cap_t=600,
                            x=_r(geo.NODES["CRN"][0]), y=_r(geo.NODES["CRN"][1]), z=0.0),
        "rompad-01": _attr("rom_pad", "ROM-площадка (склад руды)", x=_r(geo.NODES["ROMN"][0]),
                           y=_r(geo.NODES["ROMN"][1]), z=0.0),
        "wastedump-01": _attr("waste_dump", "Породный отвал", x=_r(geo.NODES["DUMPN"][0]),
                              y=_r(geo.NODES["DUMPN"][1]), z=_r(geo.NODES["DUMPN"][2])),
    }
    for i, t in enumerate(w.trucks):
        attrs[t.id] = _attr("haul-truck", f"БелАЗ-{t.idx:02d} (класс 100 т)", capacity_t=100)
    for sid, sh in w.shovels.items():
        n = geo.NODES[sh.node]
        attrs[sid] = _attr("excavator", f"Экскаватор Э-{sid[-1]} ({geo.FACES[sh.face]['name']})", bucket_t=21,
                           face=f"face-{sh.face}", x=_r(n[0]), y=_r(n[1]), z=_r(n[2]))
    for fid, info in geo.FACES.items():
        n = geo.NODES[info["node"]]
        attrs[f"face-{fid}"] = _attr("face", info["name"], rock=info["rock"], nominal_grade=info["grade"],
                                     reserve_t=info["reserve_t"], x=_r(n[0]), y=_r(n[1]), z=_r(n[2]))
    for sid, seg in w.segs.items():
        attrs[f"road-{sid.lower()}"] = _attr(
            "road", seg.label, segment=sid, node_a=seg.a, node_b=seg.b, length_m=_r(seg.length, 0),
            grade_pct=_r(seg.grade_pct, 1), max_kmh=seg.vmax,
            polyline=[[_r(p[0]), _r(p[1]), _r(p[2])] for p in seg.poly])
    things = {}
    order = ["pit-01"] + [k for k in attrs if k != "pit-01"]
    for name in order:
        feats = {f: {"properties": p if f == "position" else dict(p)} for f, p in snap[name].items()}
        things[f"{NS}:{name}"] = {"policyId": "default:basic_policy", "attributes": attrs[name], "features": feats}
    return things
