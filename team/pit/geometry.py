"""Pit geometry and haul-road network.

Everything is in metres. The pit is a terraced elliptical bowl, 165 m deep
(11 benches of 15 m). The haul roads are spirals cut into the pit wall; the
same polylines are stored in the road twins and drawn by the 3D stand.
"""
import math

A_RIM, B_RIM = 850.0, 650.0   # semi-axes of the pit rim at z = 0
DEPTH = 165.0
BENCH_H = 15.0
S_BOTTOM = 0.2                # ellipse scale at the pit floor


def pit_scale(z):
    return S_BOTTOM + (1.0 - S_BOTTOM) * (z + DEPTH) / DEPTH


def pit_point(theta_deg, z, inset=0.0):
    s = pit_scale(z) - inset
    th = math.radians(theta_deg)
    return (A_RIM * s * math.cos(th), B_RIM * s * math.sin(th), float(z))


def spiral(th0, th1, z0, z1, n=36, inset=0.035):
    return [pit_point(th0 + (th1 - th0) * i / n, z0 + (z1 - z0) * i / n, inset) for i in range(n + 1)]


def zigzag(p0, p1, n=8, amp=40.0):
    """Straight spur with a gentle lateral wave (switchbacks): longer, flatter."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln, dx / ln
    pts = []
    for i in range(n + 1):
        t = i / n
        w = amp * math.sin(t * math.pi * 3) * math.sin(t * math.pi)
        pts.append((p0[0] + dx * t + nx * w, p0[1] + dy * t + ny * w, p0[2] + (p1[2] - p0[2]) * t))
    return pts


def _add(p, v, k=1.0):
    return (p[0] + v[0] * k, p[1] + v[1] * k, p[2])


def _rot(v, deg):
    r = math.radians(deg)
    return (v[0] * math.cos(r) - v[1] * math.sin(r), v[0] * math.sin(r) + v[1] * math.cos(r))


# ---- node positions -------------------------------------------------------
HUB = pit_point(-60, -165, 0.05)
JM = pit_point(100, -100, 0.035)
RIM = pit_point(215, 0, 0.035)
RIMB = pit_point(250, 0, 0.035)
_out = (math.cos(math.radians(215)), math.sin(math.radians(215)))   # outward from the pit at RIM
JC = _add(RIM, _out, 380)                       # surface junction towards crusher / ROM pad
CRN = _add(JC, _rot(_out, 35), 230)             # crusher dump pocket
ROMN = _add(JC, _rot(_out, -40), 210)           # ROM pad (ore stockpile)
JD = _add(RIM, _rot(_out, 70), 300)             # surface junction towards the waste dump
DUMPN = (_add(JD, _rot(_out, 70), 420)[0], _add(JD, _rot(_out, 70), 420)[1], 20.0)
F1N = pit_point(-165, -165, 0.06)               # F1: high-grade ore on the pit floor
F2N = pit_point(135, -100, 0.02)                # F2: low-grade ore, mid bench
F3N = pit_point(238, -30, 0.02)                 # F3: waste (overburden) on an upper bench

NODES = {
    "HUB": HUB, "JM": JM, "RIM": RIM, "RIMB": RIMB, "JC": JC, "CRN": CRN, "ROMN": ROMN,
    "JD": JD, "DUMPN": DUMPN, "F1N": F1N, "F2N": F2N, "F3N": F3N,
}

# id: (a, b, polyline a->b, max km/h, label)
SEGMENTS = {
    "S1": ("HUB", "F1N", zigzag(HUB, F1N, 8, 25), 30, "Подъезд к забою F1"),
    "ML": ("HUB", "JM", spiral(-60, 100, -165, -100, 28), 35, "Нижняя рампа"),
    "S2": ("JM", "F2N", zigzag(JM, F2N, 8, 25), 30, "Подъезд к забою F2"),
    "UA": ("JM", "RIM", spiral(100, 215, -100, 0, 34), 35, "Верхняя рампа А (основная)"),
    "UB": ("JM", "RIMB", spiral(100, -110, -100, 0, 56), 25, "Верхняя рампа Б (резервная)"),
    "SB": ("RIMB", "RIM", zigzag(RIMB, RIM, 10, 30), 40, "Рампа Б: выезд на поверхность"),
    "S3": ("RIM", "F3N", zigzag(RIM, F3N, 10, 45), 30, "Подъезд к забою F3 (вскрыша)"),
    "SURF1": ("RIM", "JC", zigzag(RIM, JC, 6, 10), 50, "Поверхностная дорога к ДСК"),
    "CRACC": ("JC", "CRN", zigzag(JC, CRN, 4, 8), 30, "Заезд к дробилке"),
    "ROMACC": ("JC", "ROMN", zigzag(JC, ROMN, 4, 8), 30, "Заезд на ROM-площадку"),
    "SURF2": ("RIM", "JD", zigzag(RIM, JD, 6, 10), 50, "Поверхностная дорога к отвалу"),
    "DUMPACC": ("JD", "DUMPN", zigzag(JD, DUMPN, 8, 15), 30, "Подъезд к отвалу"),
}


class Segment:
    def __init__(self, sid, a, b, poly, vmax, label):
        self.id, self.a, self.b, self.label = sid, a, b, label
        self.poly = poly
        self.vmax = vmax
        self.cum = [0.0]
        for i in range(len(poly) - 1):
            self.cum.append(self.cum[-1] + math.dist(poly[i], poly[i + 1]))
        self.length = self.cum[-1]
        self.grade_pct = 100.0 * (poly[-1][2] - poly[0][2]) / self.length   # a -> b
        self.closed = False
        self.speed_factor = 1.0
        self.trucks = 0

    def sample(self, s, forward=True):
        """Position (x, y, z, heading) at distance s from the start in the travel direction."""
        s = max(0.0, min(self.length, s))
        d = s if forward else self.length - s
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid
        seg = (self.cum[hi] - self.cum[lo]) or 1.0
        t = (d - self.cum[lo]) / seg
        p, q = self.poly[lo], self.poly[hi]
        x, y, z = (p[k] + (q[k] - p[k]) * t for k in range(3))
        h = math.atan2(q[1] - p[1], q[0] - p[0])
        if not forward:
            h += math.pi
        return x, y, z, h


def build_segments():
    return {sid: Segment(sid, a, b, poly, v, lab) for sid, (a, b, poly, v, lab) in SEGMENTS.items()}


# ---- fixed objects ---------------------------------------------------------
FACES = {
    "f1": dict(node="F1N", rock="ore", grade=0.95, name="Забой F1 (богатая руда)", reserve_t=900000),
    "f2": dict(node="F2N", rock="ore", grade=0.52, name="Забой F2 (бедная руда)", reserve_t=1400000),
    "f3": dict(node="F3N", rock="waste", grade=0.0, name="Забой F3 (вскрыша)", reserve_t=2500000),
}
