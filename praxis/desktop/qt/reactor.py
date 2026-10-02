"""The engine behind the PRAXIS core, "The Reactor". Toolkit-free (pure math) so every behaviour is unit-testable.

The picture: an arc reactor in its housing, ringed by flat HUD gauge rings, in the manner of the armour's own display: gold and
gunmetal, a blue-white core. It is driven by REAL state, not decoration:

  coil spin / charge   how hard it is working: idle ticks over, working spins up and charges the coils, STOP spins it down fast
  core colour          the state: reactor blue, working bright blue, needs-you amber, verified gold-white, failed red
  PLAN / ACT / VERIFY  three flat HUD rings: planning, one arc per real step, one arc per real check (sealed when verified)
  flare / shockwave    every real event flares the core and sends a ring outward; a verified goal sends a bigger one
  embers               warm sparks drift up from the housing; more while it is working
"""
import math
import random

TAU = math.tau

# Geometry, in units of R (the housing's outer radius is 1.0 so everything else is a ratio of what you see).
CORE_R = 0.20
TRI_R = 0.34
PAL_R = (0.40, 0.45)             # the bright palladium ring
COIL_IN, COIL_OUT = 0.50, 0.80
HOUSING_IN, HOUSING_OUT = 0.84, 1.0
VOICE_IN, VOICE_OUT = 1.06, 1.24
RING_R = {"verify": 1.38, "act": 1.58, "plan": 1.78}
SCALE_R = (1.92, 2.02)           # the outer tick scale
EXTENT = SCALE_R[1]              # everything lives inside this radius
COILS = 10
COIL_GAP = math.radians(5.0)
GAP_DEG = 7.0                    # empty arc between segments of a HUD ring

LEVELS = [80, 52, 30, 14]        # ember counts; the quality governor steps down through these
FLOW_LEVELS = [44, 30, 18, 8]    # inward energy streaks
BOLT_MAX = [5, 4, 2, 1]          # simultaneous energy arcs
DECOR_R = (1.31, 1.48, 1.68, 1.86)   # the decorative HUD circles between and around the real rings
BAR_LEVELS = [96, 72, 48, 32]

# colours (r, g, b)
GOLD = (242, 180, 65)
GOLD_BRIGHT = (255, 214, 120)
STEEL = (120, 135, 152)
BLUE = (143, 227, 255)
WHITE = (255, 255, 255)
JARVIS = (110, 226, 255)           # the conversational mind: cool ice-blue, calm concentric rings
FRIDAY = (255, 138, 50)            # the executing mind: warm amber, angular and tactical

# what each state looks like. spin: coil ring rad/s. tick: outer scale rad/s. charge: how full the coils are. core: core brightness.
# hz/amp: pulse. jit: flicker. tint/mix: state colour and how much of it. bright: overall. embers: spark rate multiplier.
MODE = {
    "idle":     dict(persona=0.0, sweep=0.55, bolts=0.1, flow=10, spin=0.10, tick=0.030, charge=0.50, core=0.85, hz=0.25, amp=0.04, jit=0.00, tint=(110, 226, 255), mix=0.45, bright=1.00, embers=0.35),
    "starting": dict(persona=0.1, sweep=2.6, bolts=0.6, flow=24, spin=1.40, tick=0.200, charge=0.30, core=0.70, hz=0.60, amp=0.06, jit=0.01, tint=(205, 240, 255), mix=0.30, bright=1.00, embers=0.80),
    "working":  dict(persona=1.0, sweep=1.8, bolts=1.3, flow=44, spin=0.95, tick=0.090, charge=0.85, core=1.10, hz=1.00, amp=0.06, jit=0.01, tint=(255, 128, 48), mix=0.80, bright=1.10, embers=1.60),
    "waiting":  dict(persona=0.85, sweep=0.25, bolts=0.08, flow=6, spin=0.04, tick=0.010, charge=0.60, core=0.90, hz=0.50, amp=0.10, jit=0.00, tint=(255, 159, 67), mix=0.70, bright=1.00, embers=0.30),
    "ok":       dict(persona=0.25, sweep=1.2, bolts=0.8, flow=30, spin=0.45, tick=0.060, charge=1.00, core=1.30, hz=0.35, amp=0.05, jit=0.00, tint=(255, 214, 120), mix=0.65, bright=1.15, embers=1.20),
    "bad":      dict(persona=1.0, sweep=0.15, bolts=0.55, flow=4, spin=0.05, tick=0.005, charge=0.25, core=0.60, hz=0.30, amp=0.05, jit=0.06, tint=(255, 74, 61), mix=0.80, bright=0.95, embers=0.20),
    "stopping": dict(persona=1.0, sweep=0.0, bolts=0.3, flow=0, spin=0.00, tick=0.000, charge=0.10, core=0.50, hz=0.80, amp=0.08, jit=0.04, tint=(255, 120, 60), mix=0.70, bright=1.00, embers=0.10),
    "stopped":  dict(persona=0.35, sweep=0.2, bolts=0.05, flow=4, spin=0.06, tick=0.010, charge=0.35, core=0.65, hz=0.25, amp=0.03, jit=0.00, tint=(255, 159, 67), mix=0.45, bright=0.90, embers=0.15),
}
FAST_MODES = ("stopping",)       # these snap quickly: a kill switch must look like one


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def ease_out(x):
    x = clamp(x)
    return 1.0 - (1.0 - x) ** 3


class Dynamics:
    """Eased parameters. Switching state never snaps (except STOP): values glide toward the new mode's targets."""

    KEYS = ("persona", "spin", "tick", "charge", "core", "hz", "amp", "jit", "mix", "bright", "embers", "sweep", "bolts", "flow")

    def __init__(self, mode="idle"):
        self.mode = mode
        self.v = dict(MODE[mode])
        self.tint = tuple(float(c) for c in MODE[mode]["tint"])
        self.rate = 3.5

    def set_mode(self, mode):
        if mode in MODE and mode != self.mode:
            self.mode = mode
            self.rate = 12.0 if mode in FAST_MODES else 3.5

    def step(self, dt):
        k = 1.0 - math.exp(-dt * self.rate)
        tgt = MODE[self.mode]
        for key in self.KEYS:
            self.v[key] += (tgt[key] - self.v[key]) * k
        self.tint = mix(self.tint, tgt["tint"], k)


class Reactor:
    """The animated state: rotations, flare, shockwave, power-up, and the embers."""

    def __init__(self, n_embers=LEVELS[0], seed=7):
        self.rng = random.Random(seed)
        self.dyn = Dynamics("starting")
        self.t = 0.0
        self.coil_rot = 0.0
        self.tri_rot = 0.0
        self.tick_rot = 0.0
        self.flare = 0.0
        self.shock = None                 # progress 0..1 of the big verified shockwave, or None
        self.power = 0.0                  # 0 -> 1 while it starts up; the reactor "lights" coil by coil
        self.n_embers = n_embers
        self.embers = []                  # [x, y, vx, vy, life, age]  in units of R, centred on the reactor
        self._ember_acc = 0.0
        self.boot = 0.0                   # 0 -> 1 over BOOT_S: the HUD draws itself in, ring by ring
        self.sweep_rot = 0.0              # the radar sweep
        self.flow_cap, self.bolt_cap = FLOW_LEVELS[0], BOLT_MAX[0]
        self.bolts = []                   # energy arcs: {"pts": [(x, y)...], "age": s, "life": s}  in units of R
        self.flow = []                    # energy streaks spiralling in (or out): [angle, radius, speed]
        self._bolt_acc = 0.0

    def restart_power_up(self):
        self.power = 0.0
        self.boot = 0.0

    def reveal(self, k, delay=0.10, span=0.35):
        """How far element k (0 = first) of the boot sequence has drawn in, 0..1: the elements arrive one after another."""
        return ease_out((self.boot - k * delay) / span)

    def set_level(self, level):
        """Detail level 0..3 (the quality governor): fewer sparks, streaks and arcs on a slow machine."""
        level = int(clamp(level, 0, len(LEVELS) - 1))
        self.flow_cap, self.bolt_cap = FLOW_LEVELS[level], BOLT_MAX[level]
        self.resize(LEVELS[level])
        del self.bolts[self.bolt_cap:]

    def trigger_shock(self):
        self.shock = 0.0

    def pulse(self, amount=1.0):
        self.flare = min(1.5, self.flare + 0.7 * amount)
        for _ in range(2 if amount >= 0.8 else 1):                      # an event crackles: energy arcs from the core to the coils
            self._spawn_bolt()

    def _spawn_bolt(self):
        if len(self.bolts) >= self.bolt_cap:
            return
        a = self.rng.uniform(0, TAU)
        self.bolts.append({"pts": bolt_points(self.rng, a, CORE_R * 1.05, COIL_OUT * 0.97), "age": 0.0, "life": self.rng.uniform(0.18, 0.36)})

    def resize(self, n):
        self.n_embers = max(0, int(n))
        del self.embers[self.n_embers:]

    def advance(self, dt):
        dt = clamp(dt, 0.0, 0.25)                           # a stalled frame must not make the simulation jump
        if dt <= 0.0:
            return
        self.t += dt
        self.dyn.step(dt)
        v = self.dyn.v
        self.power = min(1.0, self.power + dt / 2.2)
        self.boot = min(1.0, self.boot + dt / BOOT_S)
        self.sweep_rot = (self.sweep_rot + v["sweep"] * dt) % TAU
        # energy arcs flicker into existence at a rate that follows the state, then die quickly
        self._bolt_acc += dt * v["bolts"] * (1.0 + 2.0 * self.flare)
        while self._bolt_acc >= 1.0:
            self._bolt_acc -= 1.0
            self._spawn_bolt()
        self._bolt_acc = min(self._bolt_acc, 2.0)
        for b in self.bolts:
            b["age"] += dt
        self.bolts = [b for b in self.bolts if b["age"] < b["life"]]
        # energy streaks spiral inward while it works (it is taking the goal in), outward when a goal verifies (giving something back)
        want = int(v["flow"] * self.flow_cap / FLOW_LEVELS[0])
        outward = self.dyn.mode == "ok"
        while len(self.flow) < want:
            self.flow.append([self.rng.uniform(0, TAU), self.rng.uniform(0.3, 1.2) if not outward else self.rng.uniform(0.25, 0.7), self.rng.uniform(0.25, 0.6)])
        del self.flow[want:]
        for f in self.flow:
            f[0] = (f[0] + (0.6 + 0.8 * (1.3 - f[1])) * dt) % TAU
            f[1] += (f[2] if outward else -f[2]) * dt
            if f[1] < CORE_R * 1.1 or f[1] > VOICE_OUT:
                f[1] = (CORE_R * 1.2 if outward else VOICE_OUT)
                f[0] = self.rng.uniform(0, TAU)
        self.coil_rot = (self.coil_rot + v["spin"] * dt) % TAU
        self.tri_rot = (self.tri_rot - v["spin"] * 0.6 * dt - 0.05 * dt) % TAU
        self.tick_rot = (self.tick_rot + v["tick"] * dt) % TAU
        self.flare = max(0.0, self.flare - dt * 1.8)
        if self.shock is not None:
            self.shock += dt / 1.4
            if self.shock >= 1.0:
                self.shock = None
        # embers: warm sparks rising from the housing; the rate follows the state
        self._ember_acc += dt * v["embers"] * self.n_embers / 3.0
        while self._ember_acc >= 1.0 and len(self.embers) < self.n_embers:
            self._ember_acc -= 1.0
            a = self.rng.uniform(0, TAU)
            r = self.rng.uniform(0.82, 1.0)
            self.embers.append([math.cos(a) * r, math.sin(a) * r, self.rng.uniform(-0.04, 0.04), self.rng.uniform(-0.30, -0.10),
                                self.rng.uniform(1.4, 3.2), 0.0])
        self._ember_acc = min(self._ember_acc, 2.0)
        alive = []
        for e in self.embers:
            e[5] += dt
            if e[5] < e[4]:
                e[2] += self.rng.uniform(-0.05, 0.05) * dt
                e[0] += e[2] * dt
                e[1] += e[3] * dt
                alive.append(e)
        self.embers = alive

    # ---- values the painter needs ---------------------------------------------------------------------------------------------
    def core_level(self):
        """Core brightness 0..~1.6: the state's level, a slow pulse, and the flare from real events."""
        v = self.dyn.v
        base = v["core"] * (1.0 + v["amp"] * math.sin(self.t * TAU * v["hz"]))
        flick = 1.0 - v["jit"] * (0.5 + 0.5 * math.sin(self.t * 47.0) * math.sin(self.t * 13.0))
        return base * flick * (0.25 + 0.75 * ease_out(self.power)) + 0.45 * self.flare

    def coil_charge(self, i):
        """How lit coil i is, 0..1. Working: a bright run chases round the ring. Waiting: all pulse together. Else steady."""
        v = self.dyn.v
        lit = clamp(self.power * COILS - i + 0.5)             # power-up lights the coils one by one
        base = v["charge"]
        mode = self.dyn.mode
        if mode == "working":
            phase = ((self.t * 1.3) - i / COILS) % 1.0
            return lit * clamp(base * (0.55 + 0.45 * (1.0 - phase) ** 2) + 0.15)
        if mode == "waiting":
            return lit * clamp(base * (0.6 + 0.4 * math.sin(self.t * 3.2)))
        if mode == "stopping":
            return lit * clamp(base * (1.0 - (i / COILS)) * 0.6)
        return lit * clamp(base * (0.85 + 0.15 * math.sin(self.t * 1.1 + i * 0.7)))

    def accent(self):
        """The colour of the mind in charge right now: JARVIS ice-blue while it listens and talks, FRIDAY amber while it works."""
        return mix(JARVIS, FRIDAY, clamp(self.dyn.v["persona"]))

    def tint_colour(self):
        return self.dyn.tint, self.dyn.v["mix"]


BOOT_S = 3.6                     # seconds for the HUD to draw itself in


# ---- pure geometry --------------------------------------------------------------------------------------------------------------
def bolt_points(rng, angle, r0, r1, segs=9, jitter=0.035):
    """A jagged energy arc from radius r0 to r1 along `angle`, in units of R: segs+1 points, each pushed sideways by up to `jitter`."""
    ca, sa = math.cos(angle), math.sin(angle)
    pts = []
    for i in range(segs + 1):
        r = r0 + (r1 - r0) * i / segs
        off = 0.0 if i in (0, segs) else rng.uniform(-jitter, jitter)
        pts.append((ca * r - sa * off, sa * r + ca * off))
    return pts


def hex_centers(w, h, s=34.0):
    """Centres of the armour-plate hexagon pattern behind the dial, for a w x h widget and edge length s (pointy-sided columns)."""
    dx, dy = s * 1.5, s * math.sqrt(3) / 2
    out = []
    for ci in range(int(w / dx) + 2):
        for ri in range(int(h / (2 * dy)) + 2):
            out.append((ci * dx, ri * dy * 2 + (dy if ci % 2 else 0)))
    return out


def hex_wave(cells, cx, cy, radius, width):
    """The cells a travelling ring of light at `radius` (pixels) lights up: [(index, strength 0..1)], brightest on the ring itself."""
    out = []
    for i, (x, y) in enumerate(cells):
        d = abs(math.hypot(x - cx, y - cy) - radius)
        if d < width:
            out.append((i, 1.0 - d / width))
    return out


def coil_polys(cx, cy, R, rot, n=COILS):
    """The reactor's coils: n trapezoids between COIL_IN and COIL_OUT, each as 4 points (inner-a, inner-b, outer-b, outer-a)."""
    span = TAU / n - COIL_GAP
    out = []
    for i in range(n):
        a0 = rot + i * TAU / n
        a1 = a0 + span
        pts = []
        for ang, rad in ((a0, COIL_IN), (a1, COIL_IN), (a1, COIL_OUT * 0.995), (a0, COIL_OUT * 0.995)):
            pts.append((cx + math.cos(ang) * rad * R, cy + math.sin(ang) * rad * R))
        out.append(pts)
    return out


def triangle(cx, cy, R, rot, radius=TRI_R):
    return [(cx + math.cos(rot + k * TAU / 3 - math.pi / 2) * radius * R, cy + math.sin(rot + k * TAU / 3 - math.pi / 2) * radius * R)
            for k in range(3)]


def ring_segments(n, gap_deg=GAP_DEG):
    """Arc layout for a HUD ring with n segments, clockwise from the top: [(start_degrees, span_degrees)]. One segment is a full circle."""
    if n <= 0:
        return []
    if n == 1:
        return [(0.0, 360.0)]
    span = 360.0 / n
    return [(i * span, span - gap_deg) for i in range(n)]


def ticks(rot, n=72):
    """The outer gauge scale: [(angle, kind)] kind 2 = every 90 degrees, 1 = every 10, 0 = minor."""
    out = []
    for i in range(n):
        deg = i * 360.0 / n
        kind = 2 if i % max(1, n // 4) == 0 else 1 if i % 2 == 0 else 0
        out.append((rot + math.radians(deg) - math.pi / 2, kind))
    return out


def bezier(p0, p1, p2, u):
    a = (1 - u) ** 2
    b = 2 * (1 - u) * u
    c = u * u
    return (a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1])


def courier(t, p0, p1, p2, n=44, speed=0.85):
    """Sparks streaming along a curve from p0 (the reactor) to p2 (the provider being called). -> [(x, y, alpha, size, u)]"""
    out = []
    for i in range(n):
        u = (t * speed + i / n) % 1.0
        x, y = bezier(p0, p1, p2, u)
        out.append((x, y, math.sin(math.pi * u) ** 0.6, 1.2 + 1.8 * (1.0 - abs(2 * u - 1.0)), u))
    return out


def polyline_point(pts, u):
    """The point a fraction u (0..1) of the way along a polyline [(x, y), ...], measured by length."""
    segs = [(pts[i], pts[i + 1], math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])) for i in range(len(pts) - 1)]
    total = sum(s[2] for s in segs) or 1.0
    d = clamp(u) * total
    for a, b, ln in segs:
        if d <= ln or (a, b, ln) == segs[-1]:
            f = d / ln if ln else 0.0
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        d -= ln
    return pts[-1]


def courier_poly(t, pts, n=44, speed=0.85):
    """Like `courier` but along a HUD-style polyline. -> [(x, y, alpha, size, u)]"""
    out = []
    for i in range(n):
        u = (t * speed + i / n) % 1.0
        x, y = polyline_point(pts, u)
        out.append((x, y, math.sin(math.pi * u) ** 0.6, 1.2 + 1.8 * (1.0 - abs(2 * u - 1.0)), u))
    return out


class Quality:
    """Adaptive detail: if frames stay slow the ember/bar counts step down a level (never back up, so it cannot flap)."""

    def __init__(self, level=0, limit_ms=40.0, patience=45):
        self.level, self.limit, self.patience = level, limit_ms, patience
        self.ema, self.since = 0.0, 0

    @property
    def n(self):
        return LEVELS[self.level]

    @property
    def bars(self):
        return BAR_LEVELS[self.level]

    def record(self, ms):
        self.ema = ms if self.ema == 0.0 else self.ema * 0.9 + ms * 0.1
        self.since += 1
        if self.ema > self.limit and self.since >= self.patience and self.level < len(LEVELS) - 1:
            self.level += 1
            self.ema, self.since = 0.0, 0
            return True
        return False
