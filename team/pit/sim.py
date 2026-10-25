"""Open-pit haul-cycle simulation with two parallel worlds.

* world "dispatcher": trucks are assigned by a dispatch algorithm (the decision the twin supports);
* world "baseline": the same pit, fleet, random streams and scenarios, but every truck has a fixed
  shovel (assignment made at the shift start), i.e. work without a dispatch system.

Both worlds run under the same what-if scenarios, so the twin always shows what the dispatcher's
decisions are worth under the current conditions. No I/O here: the module is pure, deterministic
for a given seed, and is driven by simulator.py (MQTT) and tests.
"""
import heapq
import math
import random
from collections import deque

from . import geometry as geo

# ------------------------------------------------------------------ parameters
CAP_T = 100.0            # payload of a 100-t class rigid dump truck
BUCKET_T = 21.0          # bucket of a 12-15 m3 class shovel, tonnes of rock per pass
PASS_S = 37.0            # swing cycle of a rope shovel, ~35-40 s
SPOT_S = 55.0            # truck spotting at the shovel
DUMP_S = {"crusher": 100.0, "rom": 80.0, "waste": 70.0}
REFUEL_S = 420.0
REFUEL_BELOW = 22.0
CRUSHER_TPS = 0.70       # t/s (~2500 t/h)
BIN_CAP_T = 600.0
ROM_REHANDLE_TPS = 0.17  # loader feeding the crusher from the ROM pad when the bin is empty
TARGET_WASTE_SHARE = 0.30
TARGET_GRADE = 0.72      # % Cu in the crusher feed that the plant wants
FLEET = 11
TRUCK_ASSIGNMENT_BASELINE = {"shovel-01": 4, "shovel-02": 4, "shovel-03": 3}   # best fixed split found by exhaustive search

SCENARIOS = {
    "ramp_a_closed": "Закрыть основную рампу А",
    "rain": "Дождь: скользкие дороги",
    "shovel_down": "Отказ экскаватора Э-2 (забой F2)",
    "crusher_down": "Остановка дробилки",
    "blast_f1": "Взрыв на F1: забой закрыт",
    "truck_down": "Поломка самосвала БелАЗ-07",
}
SHOVEL_DOWN_ID = "shovel-02"
TRUCK_DOWN_ID = "truck-07"
BLAST_FACE = "f1"

IDLE_CATS = ("queue_shovel", "queue_dump", "blocked")


def seg_speed_kmh(seg, fwd, loaded):
    g = seg.grade_pct if fwd else -seg.grade_pct
    if loaded:
        v = 38.0 - 2.8 * g if g > 0 else (25.0 if g < -1 else 38.0)
    else:
        v = 46.0 - 1.5 * g if g > 0 else (35.0 if g < -1 else 45.0)
    return max(7.0, min(v, seg.vmax)) * seg.speed_factor


class Truck:
    def __init__(self, idx, rng):
        self.idx = idx
        self.id = f"truck-{idx:02d}"
        self.rng = rng
        self.state = "blocked"
        self.prev_state = None
        self.payload = 0.0
        self.grade = 0.0
        self.node = "JC"
        self.route = []
        self.seg = None
        self.fwd = True
        self.s = 0.0
        self.noise = 1.0
        self.pos = geo.NODES["JC"] + (0.0,)
        self.speed = 0.0
        self.fuel = rng.uniform(55, 95)
        self.trips = 0
        self.shovel = None          # assigned shovel (loading side)
        self.dest = None            # destination site id
        self.timer = 0.0
        self.t = {k: 0.0 for k in ("queue_shovel", "queue_dump", "blocked", "refuel", "repair", "moving", "service")}
        self.wait_at = 0.0
        self.cycle_start = 0.0
        self.cycle_sum = 0.0
        self.cycles = 0
        self.last_cycle_min = 0.0


class Shovel:
    def __init__(self, sid, face, rng):
        self.id = sid
        self.face = face
        self.node = geo.FACES[face]["node"]
        self.rock = geo.FACES[face]["rock"]
        self.rng = rng
        self.state = "waiting"
        self.queue = []
        self.current = None
        self.timer = 0.0
        self.delay_left = 0.0
        self.t_work = self.t_starved = self.t_down = 0.0
        self.tonnes = 0.0
        self.passes = 0
        self.down = False
        self.blast = False

    @property
    def available(self):
        return not (self.down or self.blast)


class Site:
    """Dump point: crusher pocket, ROM pad or waste dump."""

    def __init__(self, sid, kind, node, slots):
        self.id, self.kind, self.node, self.slots = sid, kind, node, slots
        self.queue = []
        self.dumping = []
        self.down = False
        self.tonnes = 0.0


class World:
    def __init__(self, mode, seed=7):
        self.mode = mode
        self.seed = seed
        self.now = 0.0
        self.segs = geo.build_segments()
        self.adj = {}
        for s in self.segs.values():
            self.adj.setdefault(s.a, []).append((s, True))
            self.adj.setdefault(s.b, []).append((s, False))
        self.shovels = {f"shovel-0{i + 1}": Shovel(f"shovel-0{i + 1}", f, random.Random(seed * 100 + i))
                        for i, f in enumerate(geo.FACES)}
        self.sites = {
            "crusher-01": Site("crusher-01", "crusher", "CRN", 1),
            "rompad-01": Site("rompad-01", "rom", "ROMN", 1),
            "wastedump-01": Site("wastedump-01", "waste", "DUMPN", 2),
        }
        self.trucks = [Truck(i + 1, random.Random(seed * 1000 + i)) for i in range(FLEET)]
        self.face_grade = {f: v["grade"] for f, v in geo.FACES.items()}
        self.face_mined = {f: 0.0 for f in geo.FACES}
        self.face_rng = random.Random(seed + 99)
        self.dispatch_rng = random.Random(seed + 5)
        # plant
        self.bin_t = 250.0
        self.bin_gt = 250.0 * 0.72
        self.rom_t = 0.0
        self.rom_gt = 0.0
        self.crushed_t = 0.0
        self.crushed_gt = 0.0
        self.feed_grade = 0.72
        self.crusher_starved_s = 0.0
        self.crusher_blocked_s = 0.0
        self.crusher_state = "crushing"
        self.waste_t = 0.0
        # scenarios
        self.active = {k: False for k in SCENARIOS}
        self.rain = False
        # dispatcher memory
        self.decisions = 0
        self.log = deque(maxlen=8)
        self.last_decision = "—"
        # statistics
        self.hist = deque(maxlen=200)
        self._last_snap = -1e9
        self.baseline_assign = {}
        k = 0
        for sid, n in TRUCK_ASSIGNMENT_BASELINE.items():
            for _ in range(n):
                if k < FLEET:
                    self.baseline_assign[self.trucks[k].id] = sid
                    k += 1
        for t in self.trucks[k:]:
            self.baseline_assign[t.id] = "shovel-02"
        # trucks start from the surface junction one after another
        for i, t in enumerate(self.trucks):
            t.timer = i * 45.0
            t.state = "blocked"

    # ----------------------------------------------------------- routing
    def route(self, src, dst, loaded):
        """Dijkstra over open roads; returns (edges, seconds) or (None, inf)."""
        if src == dst:
            return [], 0.0
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist.get(u, 1e18):
                continue
            for seg, fwd in self.adj.get(u, ()):
                if seg.closed:
                    continue
                v = seg.b if fwd else seg.a
                n = seg.trucks
                cong = 1.0 / (1.0 + 0.05 * max(0, n - 2))
                w = seg.length / (seg_speed_kmh(seg, fwd, loaded) * cong / 3.6)
                if d + w < dist.get(v, 1e18):
                    dist[v] = d + w
                    prev[v] = (u, seg, fwd)
                    heapq.heappush(pq, (d + w, v))
        if dst not in dist:
            return None, float("inf")
        edges = []
        node = dst
        while node != src:
            u, seg, fwd = prev[node]
            edges.append((seg, fwd))
            node = u
        edges.reverse()
        return edges, dist[dst]

    def _send(self, truck, dst_node, state):
        edges, eta = self.route(truck.node, dst_node, truck.payload > 0)
        if edges is None:
            return False
        truck.route = edges
        truck.state = state
        self._enter_next_edge(truck)
        return True

    def _enter_next_edge(self, truck):
        if truck.seg is not None:
            truck.seg.trucks = max(0, truck.seg.trucks - 1)
            truck.seg = None
        if not truck.route:
            return
        truck.seg, truck.fwd = truck.route.pop(0)
        truck.seg.trucks += 1
        truck.s = 0.0
        truck.noise = min(1.15, max(0.85, 1.0 + 0.06 * truck.rng.gauss(0, 1)))

    # ----------------------------------------------------------- dispatch
    def _load_time(self):
        return SPOT_S + (CAP_T / BUCKET_T) * PASS_S * (1.12 if self.rain else 1.0)

    def _shovel_free_and_queue(self, sh, exclude=None):
        """(time when the shovel finishes everything already committed, list of (eta, truck))."""
        free = self.now
        if sh.current is not None:
            left = max(0.0, (CAP_T - sh.current.payload) / BUCKET_T) * PASS_S
            free = self.now + left
        if sh.delay_left > 0:
            free += sh.delay_left
        if sh.down or sh.blast:
            free += 1800.0
        incoming = []
        for t in self.trucks:
            if t is exclude or t.shovel is not sh or t.state not in ("to_shovel", "queue_shovel"):
                continue
            if t.state == "queue_shovel":
                incoming.append((self.now, t))
            else:
                incoming.append((self.now + self._eta(t), t))
        return free, sorted(incoming, key=lambda x: x[0])

    def _eta(self, t):
        if t.seg is None:
            return 0.0
        rest = t.seg.length - t.s
        v = seg_speed_kmh(t.seg, t.fwd, t.payload > 0) / 3.6
        eta = rest / max(v, 1.0)
        for seg, fwd in t.route:
            eta += seg.length / (seg_speed_kmh(seg, fwd, t.payload > 0) / 3.6)
        return eta

    def choose_shovel(self, truck):
        """Dispatcher: minimise truck waiting + shovel starvation + plan deviation."""
        best = None
        total = self.waste_t + self.crushed_t + self.rom_t
        waste_share = self.waste_t / total if total > 500 else TARGET_WASTE_SHARE
        grade_err = self.feed_grade - TARGET_GRADE
        load_s = self._load_time()
        options = []
        for sh in self.shovels.values():
            if not sh.available:
                continue
            edges, travel = self.route(truck.node, sh.node, False)
            if edges is None:
                continue
            free, incoming = self._shovel_free_and_queue(sh, exclude=truck)
            ta = self.now + travel
            for eta, _ in incoming:
                if eta <= ta:
                    free = max(free, eta) + load_s
            wait = max(0.0, free - ta)
            starve = max(0.0, ta - free)
            cost = wait + 0.7 * starve + 0.12 * travel
            if sh.rock == "waste":
                cost += 900.0 * (waste_share - TARGET_WASTE_SHARE)
            else:
                cost -= 250.0 * (waste_share - TARGET_WASTE_SHARE)
                cost += 1500.0 * grade_err * (self.face_grade[sh.face] - TARGET_GRADE)
            options.append((cost, sh, wait, travel))
        if not options:
            return None, None
        options.sort(key=lambda o: o[0])
        return options[0], options

    def choose_site(self, truck, rock):
        """Where a loaded truck goes. Dispatcher re-routes ore to the ROM pad if the crusher is busy."""
        if rock == "waste":
            return self.sites["wastedump-01"]
        cr = self.sites["crusher-01"]
        if self.mode == "static":
            return cr
        rom = self.sites["rompad-01"]
        _, t_cr = self.route(truck.node, cr.node, True)
        _, t_rom = self.route(truck.node, rom.node, True)
        q = len(cr.queue) + len(cr.dumping)
        busy = q * DUMP_S["crusher"]
        if self.bin_t + q * CAP_T > BIN_CAP_T:
            busy += 600.0
        if cr.down:
            busy = 1e9
        if t_cr == float("inf"):
            return rom
        return rom if (t_cr + busy) > (t_rom + 80.0 + 240.0) else cr

    def _decide(self, truck):
        """Assign an empty truck to a shovel (dispatcher or fixed)."""
        if self.mode == "static":
            sh = self.shovels[self.baseline_assign[truck.id]]
            if not sh.available or self._blocked_long(truck):
                alt = [s for s in self.shovels.values() if s.available]
                if alt:
                    sh = min(alt, key=lambda s: self.route(truck.node, s.node, False)[1])
            truck.shovel = sh
            return self._send(truck, sh.node, "to_shovel") or self._block(truck)
        pick, options = self.choose_shovel(truck)
        if pick is None:
            return self._block(truck)
        cost, sh, wait, travel = pick
        truck.shovel = sh
        self.decisions += 1
        alt = options[1] if len(options) > 1 else None
        txt = (f"{self.clock()} Т-{truck.idx:02d} → {sh.id.replace('shovel-', 'Э-')}: "
               f"ожидание {wait / 60:.1f} мин, путь {travel / 60:.1f} мин")
        if alt:
            txt += f" (иначе {alt[1].id.replace('shovel-', 'Э-')}: ожидание {alt[2] / 60:.1f} мин)"
        self.last_decision = txt
        self.log.append(txt)
        return self._send(truck, sh.node, "to_shovel") or self._block(truck)

    def _reconsider(self, truck):
        """Dispatcher re-checks the assignment of an empty truck at every junction (hysteresis 90 s)."""
        pick, options = self.choose_shovel(truck)
        if pick is None or pick[1] is truck.shovel:
            return
        cur_cost = next((o[0] for o in options if o[1] is truck.shovel), None)
        if cur_cost is not None and cur_cost - pick[0] < 90.0:
            return
        edges, _ = self.route(truck.node, pick[1].node, False)
        if edges is None:
            return
        old = truck.shovel
        truck.shovel = pick[1]
        truck.route = edges
        self.decisions += 1
        txt = (f"{self.clock()} Т-{truck.idx:02d} перенаправлен {old.id.replace('shovel-', 'Э-')} → "
               f"{pick[1].id.replace('shovel-', 'Э-')}: ожидание {pick[2] / 60:.1f} мин")
        self.last_decision = txt
        self.log.append(txt)

    def _blocked_long(self, truck):
        return truck.shovel is not None and not truck.shovel.available and truck.wait_at > 900.0

    def _block(self, truck):
        truck.state = "blocked"
        truck.timer = 10.0
        return False

    def clock(self):
        m = int(self.now // 60)
        return f"{(6 + m // 60) % 24:02d}:{m % 60:02d}"

    # ----------------------------------------------------------- scenarios
    def set_scenario(self, name, on):
        if name not in SCENARIOS:
            return False
        self.active[name] = bool(on)
        if name == "ramp_a_closed":
            self.segs["UA"].closed = on
        elif name == "rain":
            self.rain = on
            for s in self.segs.values():
                s.speed_factor = (0.85 if s.id.startswith("SURF") else 0.72) if on else 1.0
        elif name == "shovel_down":
            self.shovels[SHOVEL_DOWN_ID].down = on
        elif name == "crusher_down":
            self.sites["crusher-01"].down = on
        elif name == "blast_f1":
            self.shovels["shovel-01"].blast = on
        elif name == "truck_down":
            t = self.trucks[int(TRUCK_DOWN_ID.split("-")[1]) - 1]
            self._truck_breakdown(t, on)
        return True

    def _truck_breakdown(self, t, on):
        if on and t.state != "repair":
            t.prev_state = t.state
            if t.state in ("queue_shovel", "loading"):
                sh = t.shovel
                if t in sh.queue:
                    sh.queue.remove(t)
                if sh.current is t:
                    sh.current = None
                t.payload = 0.0
            if t.state in ("queue_dump", "dumping"):
                for site in self.sites.values():
                    if t in site.queue:
                        site.queue.remove(t)
                    if t in site.dumping:
                        site.dumping.remove(t)
            t.state = "repair"
            t.speed = 0.0
        elif not on and t.state == "repair":
            prev = t.prev_state
            if prev in ("to_shovel", "to_dump"):
                t.state = prev
            else:
                t.state = "blocked"
                t.timer = 0.0
                if t.seg is not None:
                    t.seg.trucks = max(0, t.seg.trucks - 1)
                    t.seg = None
                    t.route = []

    # ----------------------------------------------------------- stepping
    def step(self, dt):
        self.now += dt
        for fid in self.face_grade:
            if geo.FACES[fid]["grade"] > 0:
                g = self.face_grade[fid] + self.face_rng.gauss(0, 0.0015 * math.sqrt(dt))
                base = geo.FACES[fid]["grade"]
                self.face_grade[fid] = min(base * 1.25, max(base * 0.75, g))
        for sh in self.shovels.values():
            self._step_shovel(sh, dt)
        for t in self.trucks:
            self._step_truck(t, dt)
        for site in self.sites.values():
            self._step_site(site, dt)
        self._step_crusher(dt)
        if self.now - self._last_snap >= 60.0:
            self._last_snap = self.now
            self.hist.append(self.counters())

    def _step_shovel(self, sh, dt):
        for t in list(sh.queue):
            t.wait_at += dt
        if sh.down or sh.blast:
            sh.state = "down" if sh.down else "blast"
            sh.t_down += dt
            if sh.state == "down" or sh.blast:
                # dispatcher turns trucks away; baseline keeps them waiting (see _blocked_long)
                if self.mode == "dynamic":
                    self._evict(sh)
                else:
                    for t in list(sh.queue):
                        if self._blocked_long(t) and sh.current is not t:
                            sh.queue.remove(t)
                            t.wait_at = 0.0
                            self._decide(t)
            return
        if sh.delay_left > 0:
            sh.delay_left -= dt
            sh.state = "delay"
            sh.t_starved += dt
            return
        if sh.rng.random() < dt / 7200.0:          # unplanned delay (boulders, cleaning): ~1 per 2 h
            sh.delay_left = sh.rng.uniform(240, 600)
        if sh.current is None:
            if sh.queue:
                sh.current = sh.queue.pop(0)
                sh.current.state = "loading"
                sh.current.wait_at = 0.0
                sh.timer = SPOT_S
                sh.state = "spotting"
            else:
                sh.state = "waiting"
                sh.t_starved += dt
            return
        t = sh.current
        sh.timer -= dt
        if sh.timer > 0:
            sh.t_work += dt
            return
        if sh.state == "spotting":
            sh.state = "loading"
        bucket = BUCKET_T * sh.rng.uniform(0.9, 1.1)
        bucket = min(bucket, CAP_T * 1.03 - t.payload)
        t.payload += bucket
        grade = self.face_grade[sh.face]
        t.grade = (t.grade * (t.payload - bucket) + grade * bucket) / t.payload
        sh.tonnes += bucket
        sh.passes += 1
        self.face_mined[sh.face] += bucket
        sh.t_work += dt
        sh.timer = PASS_S * sh.rng.lognormvariate(0, 0.16) * (1.12 if self.rain else 1.0)
        if t.payload >= CAP_T * 0.92:
            sh.current = None
            sh.state = "waiting"
            t.t["service"] += 0
            site = self.choose_site(t, sh.rock)
            t.dest = site
            t.cycle_start = t.cycle_start or self.now
            self._send(t, site.node, "to_dump")

    def _evict(self, sh):
        """Dispatcher: re-assign trucks queued at an unavailable shovel."""
        for t in list(sh.queue):
            sh.queue.remove(t)
            t.wait_at = 0.0
            self._decide(t)
        if sh.current is not None:
            pass

    def _step_truck(self, t, dt):
        st = t.state
        # fuel burn, %/h
        if st in ("to_shovel", "to_dump"):
            rate = 38.0 if (t.payload > 0 and t.seg is not None and
                            (t.seg.grade_pct if t.fwd else -t.seg.grade_pct) > 2) else (22.0 if t.payload > 0 else 18.0)
        else:
            rate = 6.0
        t.fuel = max(0.0, t.fuel - rate * dt / 3600.0)
        if st == "repair":
            t.t["repair"] += dt
            return
        if st == "blocked":
            t.t["blocked"] += dt if self.now > 600 else 0.0
            t.timer -= dt
            if t.timer <= 0:
                if t.payload > 0:
                    self._send(t, t.dest.node, "to_dump") or self._block(t)
                else:
                    self._decide(t)
            return
        if st in ("to_shovel", "to_dump"):
            t.t["moving"] += dt
            self._move(t, dt)
            return
        if st == "queue_shovel":
            t.t["queue_shovel"] += dt
            return
        if st == "loading":
            t.t["service"] += dt
            return
        if st == "queue_dump":
            t.t["queue_dump"] += dt
            return
        if st == "dumping":
            t.t["service"] += dt
            return
        if st == "refuel":
            t.t["refuel"] += dt
            t.timer -= dt
            if t.timer <= 0:
                t.fuel = 100.0
                self._decide(t)

    def _move(self, t, dt):
        seg = t.seg
        if seg is None:
            return self._arrive(t)
        cong = 1.0 / (1.0 + 0.05 * max(0, seg.trucks - 2))
        v = seg_speed_kmh(seg, t.fwd, t.payload > 0) * t.noise * cong / 3.6
        t.speed = v * 3.6
        t.s += v * dt
        if t.s >= seg.length:
            t.node = seg.b if t.fwd else seg.a
            t.pos = geo.NODES[t.node] + (0.0,)
            if t.route and t.state == "to_shovel" and self.mode == "dynamic":
                self._reconsider(t)
            if t.route:
                self._enter_next_edge(t)
            else:
                seg.trucks = max(0, seg.trucks - 1)
                t.seg = None
                t.speed = 0.0
                self._arrive(t)
            return
        x, y, z, h = seg.sample(t.s, t.fwd)
        t.pos = (x, y, z, h)

    def _arrive(self, t):
        if t.state == "to_shovel":
            sh = t.shovel
            if not sh.available and self.mode == "dynamic":
                return self._decide(t)
            t.state = "queue_shovel"
            t.wait_at = 0.0
            sh.queue.append(t)
        else:
            site = t.dest
            if site.down and self.mode == "dynamic" and site.kind == "crusher":
                site = self.sites["rompad-01"]
                t.dest = site
                return self._send(t, site.node, "to_dump") or self._block(t)
            t.state = "queue_dump"
            site.queue.append(t)

    def _step_site(self, site, dt):
        while site.queue and len(site.dumping) < site.slots:
            t = site.queue[0]
            if site.kind == "crusher" and (site.down or self.bin_t + t.payload > BIN_CAP_T):
                break
            site.queue.pop(0)
            t.state = "dumping"
            t.timer = DUMP_S[site.kind] * t.rng.uniform(0.9, 1.15)
            site.dumping.append(t)
        for t in list(site.dumping):
            t.timer -= dt
            if t.timer > 0:
                continue
            site.dumping.remove(t)
            site.tonnes += t.payload
            if site.kind == "crusher":
                self.bin_t += t.payload
                self.bin_gt += t.payload * t.grade
            elif site.kind == "rom":
                self.rom_t += t.payload
                self.rom_gt += t.payload * t.grade
            else:
                self.waste_t += t.payload
            t.payload = 0.0
            t.grade = 0.0
            t.trips += 1
            t.node = site.node
            t.pos = geo.NODES[site.node] + (0.0,)
            if t.cycle_start:
                t.last_cycle_min = (self.now - t.cycle_start) / 60.0
                t.cycle_sum += t.last_cycle_min
                t.cycles += 1
            t.cycle_start = self.now
            if t.fuel < REFUEL_BELOW:
                t.state = "refuel"
                t.timer = REFUEL_S
            else:
                self._decide(t)

    def _step_crusher(self, dt):
        cr = self.sites["crusher-01"]
        if cr.down:
            self.crusher_state = "down"
            return
        if self.bin_t < 30.0 and self.rom_t > 0:
            take = min(ROM_REHANDLE_TPS * dt, self.rom_t)
            g = self.rom_gt / self.rom_t
            self.rom_t -= take
            self.rom_gt -= take * g
            self.bin_t += take
            self.bin_gt += take * g
        if self.bin_t > 0.5:
            take = min(CRUSHER_TPS * dt, self.bin_t)
            g = self.bin_gt / self.bin_t
            self.bin_t -= take
            self.bin_gt -= take * g
            self.crushed_t += take
            self.crushed_gt += take * g
            self.feed_grade += (g - self.feed_grade) * min(1.0, take / 600.0)
            self.crusher_state = "crushing"
        else:
            self.crusher_state = "starved"
            self.crusher_starved_s += dt
        if self.bin_t > BIN_CAP_T - CAP_T and cr.queue:
            self.crusher_blocked_s += dt

    # ----------------------------------------------------------- statistics
    def counters(self):
        c = {k: sum(t.t[k] for t in self.trucks) for k in self.trucks[0].t}
        c.update(now=self.now, crushed_t=self.crushed_t, waste_t=self.waste_t, rom_t=self.rom_t,
                 ore_hauled=self.sites["crusher-01"].tonnes + self.sites["rompad-01"].tonnes,
                 starved=self.crusher_starved_s, shovel_starved=sum(s.t_starved for s in self.shovels.values()),
                 shovel_work=sum(s.t_work for s in self.shovels.values()),
                 trips=sum(t.trips for t in self.trucks))
        return c

    def kpi(self, window_s=3600.0):
        cur = self.counters()
        ref = self.hist[0] if self.hist else cur
        for h in self.hist:
            if self.now - h["now"] <= window_s:
                ref = h
                break
        dt = max(1.0, cur["now"] - ref["now"])
        d = {k: cur[k] - ref[k] for k in cur}
        fleet_time = max(1.0, dt * FLEET - d["repair"])
        idle = d["queue_shovel"] + d["queue_dump"] + d["blocked"]
        return {
            "ore_rate": d["ore_hauled"] * 3600.0 / dt,
            "crush_rate": d["crushed_t"] * 3600.0 / dt,
            "waste_rate": d["waste_t"] * 3600.0 / dt,
            "idle_pct": 100.0 * idle / fleet_time,
            "queue_shovel_pct": 100.0 * d["queue_shovel"] / fleet_time,
            "queue_dump_pct": 100.0 * d["queue_dump"] / fleet_time,
            "crusher_starved_pct": 100.0 * d["starved"] / dt,
            "shovel_starved_pct": 100.0 * d["shovel_starved"] / (dt * len(self.shovels)),
            "idle_h_total": (cur["queue_shovel"] + cur["queue_dump"] + cur["blocked"]) / 3600.0,
            "trips_h": d["trips"] * 3600.0 / dt,
        }


class Mine:
    """Both worlds, advanced together; `view` selects the one shown on the stand."""

    def __init__(self, seed=7):
        self.worlds = {"dispatcher": World("dynamic", seed), "baseline": World("static", seed)}
        self.view = "dispatcher"
        self.t0 = 0.0

    @property
    def shown(self):
        return self.worlds[self.view]

    def step(self, dt):
        for w in self.worlds.values():
            w.step(dt)

    def run(self, seconds, dt=2.0):
        n = int(seconds / dt)
        for _ in range(n):
            self.step(dt)

    def scenario(self, name, on):
        ok = False
        for w in self.worlds.values():
            ok = w.set_scenario(name, on) or ok
        return ok

    def set_view(self, view):
        if view in self.worlds:
            self.view = view
            return True
        return False
