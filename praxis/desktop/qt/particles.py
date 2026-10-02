"""The particle engine behind the PRAXIS core. Toolkit-free (pure math) so every behaviour is unit-testable.

A few thousand points form a living sphere. Nothing here is decoration pretending to be data: the sphere's colour, speed,
size and motion are driven by PRAXIS's real state (`Dynamics.set_mode`), a stream of particles flows to the provider that is
being called right now (`courier`), a ring lights up with plan progress (`ring`), and real events send ripples through it.
"""
import math
import random

TAU = math.tau

# palette top -> bottom of the sphere (blue -> periwinkle -> violet -> orchid -> pink), like the reference
PALETTE = [(0x4f, 0x8c, 0xff), (0x6f, 0x86, 0xff), (0x8d, 0x7c, 0xff), (0xb0, 0x78, 0xff), (0xd2, 0x70, 0xe6),
           (0xf0, 0x6c, 0xc4), (0xff, 0x6b, 0xa0)]
SPARKLE = [(0xff, 0xd3, 0x6b), (0xff, 0xf2, 0xc4), (0xae, 0xf0, 0xff)]     # warm gold, white, ice
BUCKETS = 14                    # palette steps along the sphere's height
VARIANTS = 2                    # dim / bright points per bucket
LEVELS = [3000, 2000, 1200, 600]  # particle counts: quality drops one level when frames get slow
SPEED_CLASSES = 24

# what each state looks like. spin rad/s, scale of the sphere, breathing depth/rate, jitter, tint colour + how much of it
MODE = {
    "idle":     dict(spin=0.22, scale=1.00, amp=0.025, hz=0.22, jit=0.000, tint=(0x8d, 0x7c, 0xff), mix=0.00, bright=0.88),
    "starting": dict(spin=0.95, scale=1.00, amp=0.020, hz=0.50, jit=0.004, tint=(0x9f, 0xd8, 0xff), mix=0.35, bright=1.00),
    "working":  dict(spin=0.80, scale=1.04, amp=0.035, hz=0.90, jit=0.003, tint=(0x4f, 0xd8, 0xff), mix=0.50, bright=1.10),
    "waiting":  dict(spin=0.12, scale=0.93, amp=0.040, hz=0.45, jit=0.000, tint=(0xff, 0xb8, 0x4a), mix=0.62, bright=1.00),
    "ok":       dict(spin=0.30, scale=1.02, amp=0.020, hz=0.30, jit=0.000, tint=(0x3d, 0xe3, 0xa1), mix=0.60, bright=1.10),
    "bad":      dict(spin=0.10, scale=0.97, amp=0.010, hz=0.20, jit=0.012, tint=(0xff, 0x5d, 0x73), mix=0.70, bright=0.95),
    "stopping": dict(spin=1.80, scale=0.55, amp=0.010, hz=0.80, jit=0.006, tint=(0xff, 0xb8, 0x4a), mix=0.50, bright=1.00),
    "stopped":  dict(spin=0.16, scale=0.98, amp=0.020, hz=0.25, jit=0.000, tint=(0xff, 0xb8, 0x4a), mix=0.40, bright=0.90),
}
FAST_MODES = ("stopping",)       # these snap quickly: a kill switch must look like one


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def palette_at(u):
    """Colour at height u (0 = top ... 1 = bottom)."""
    u = clamp(u) * (len(PALETTE) - 1)
    i = min(int(u), len(PALETTE) - 2)
    return mix(PALETTE[i], PALETTE[i + 1], u - i)


def ease_out(x):
    x = clamp(x)
    return 1.0 - (1.0 - x) ** 3


class Dynamics:
    """Eased parameters. Switching state never snaps (except STOP): values glide toward the new mode's targets."""

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
        for key in ("spin", "scale", "amp", "hz", "jit", "mix", "bright"):
            self.v[key] += (tgt[key] - self.v[key]) * k
        self.tint = mix(self.tint, tgt["tint"], k)


class Field:
    def __init__(self, n=LEVELS[0], seed=11):
        self.seed = seed
        self.dyn = Dynamics()
        self.t = 0.0
        self.phi = [0.0] * SPEED_CLASSES      # rotation angle per speed class (differential rotation: latitude-dependent)
        self.asm = 0.0                        # 0 = scattered, 1 = fully assembled
        self.shock = None                     # seconds since a success shockwave started
        self.tilt = [0.0, 0.0]                # current (x, y) tilt, smoothed toward tilt_target (the cursor)
        self.tilt_target = [0.0, 0.0]
        self.build(n)

    # -- construction ------------------------------------------------------------------------------------
    def build(self, n):
        rnd = random.Random(self.seed)
        self.n = n
        self.x0, self.z0, self.y, self.cls, self.pal, self.rr = [], [], [], [], [], []
        self.delay, self.scat, self.spark, self.sph, self.srate, self.shue, self.lum = [], [], [], [], [], [], []
        for _ in range(n):
            shell = rnd.random() < 0.5
            r = 0.95 + 0.07 * rnd.random() if shell else rnd.random() ** (1.0 / 3.0) * 0.96
            c = rnd.uniform(-1.0, 1.0)                       # cos(colatitude): uniform on the sphere
            s = math.sqrt(1.0 - c * c)
            a = rnd.uniform(0.0, TAU)
            self.x0.append(r * s * math.cos(a)); self.z0.append(r * s * math.sin(a)); self.y.append(r * c)
            self.rr.append(r)
            self.lum.append(1 if (shell or rnd.random() < 0.25) else 0)
            # equator spins fastest, poles slowest; a little per-particle scatter spreads them over 24 speed classes
            speed = (0.55 + 0.45 * s) * (0.78 + 0.44 * rnd.random())
            self.cls.append(min(SPEED_CLASSES - 1, int((speed - 0.42) / 0.62 * SPEED_CLASSES)))
            self.pal.append(min(BUCKETS - 1, max(0, int(clamp(0.5 - 0.5 * c + rnd.gauss(0, 0.07)) * BUCKETS))))
            self.delay.append(rnd.random() * 0.4)
            self.scat.append(0.8 + 2.2 * rnd.random())
            sp = rnd.random() < 0.012
            self.spark.append(sp)
            self.sph.append(rnd.uniform(0, TAU)); self.srate.append(rnd.uniform(1.2, 3.6)); self.shue.append(rnd.randrange(3))
        self.speed_of_class = [0.42 + 0.62 * (k + 0.5) / SPEED_CLASSES for k in range(SPEED_CLASSES)]

    def resize(self, n):
        if n != self.n:
            self.build(n)

    # -- time ----------------------------------------------------------------------------------------------
    def restart_assembly(self):
        self.asm = 0.0

    def trigger_shock(self):
        self.shock = 0.0

    def advance(self, dt):
        dt = clamp(dt, 0.0, 0.25)       # a stalled frame must not make everything jump
        self.t += dt
        self.dyn.step(dt)
        spin = self.dyn.v["spin"]
        for k in range(SPEED_CLASSES):
            self.phi[k] = (self.phi[k] + spin * self.speed_of_class[k] * dt) % TAU
        if self.asm < 1.0:
            self.asm = min(1.0, self.asm + dt / 1.8)
        if self.shock is not None:
            self.shock += dt
            if self.shock > 1.4:
                self.shock = None
        for i in (0, 1):
            self.tilt[i] += (self.tilt_target[i] - self.tilt[i]) * (1.0 - math.exp(-dt * 5.0))

    # -- projection ------------------------------------------------------------------------------------------
    def tint_colour(self):
        return self.dyn.tint, self.dyn.v["mix"]

    def project(self, cx, cy, R, mk=lambda x, y: (x, y)):
        """-> (buckets, sparkles). buckets[(b*3 + depth)*VARIANTS + lum] is a list of points (mk(x, y)); depth 0 = back ... 2 = front.
        sparkles: [(x, y, depth01, i)] drawn individually with a glow."""
        n, d = self.n, self.dyn.v
        t = self.t
        sc = R * d["scale"] * (1.0 + d["amp"] * math.sin(t * d["hz"] * TAU))
        jit = d["jit"]
        ctx, stx = math.cos(self.tilt[0]), math.sin(self.tilt[0])
        ty = self.tilt[1]
        cs = [(math.cos(p + ty), math.sin(p + ty)) for p in self.phi]
        rad = self._radial() if (self.asm < 1.0 or self.shock is not None) else None
        x0, z0, Y, cls, pal, spark, lum = self.x0, self.z0, self.y, self.cls, self.pal, self.spark, self.lum
        buckets = [[] for _ in range(BUCKETS * 3 * VARIANTS)]
        sparks = []
        sin = math.sin
        for i in range(n):
            c, s = cs[cls[i]]
            xr, zr = x0[i], z0[i]
            x = xr * c - zr * s
            z = xr * s + zr * c
            y = Y[i]
            if jit:
                y += jit * sin(t * 9.0 + i)
            y2 = y * ctx - z * stx
            z2 = y * stx + z * ctx
            f = 1.0 + 0.25 * z2
            m = sc * f * (rad[i] if rad is not None else 1.0)
            sx, sy = cx + x * m, cy - y2 * m
            if spark[i]:
                sparks.append((sx, sy, 0.5 + 0.5 * z2, i))
            else:
                buckets[(pal[i] * 3 + (0 if z2 < -0.33 else 1 if z2 < 0.33 else 2)) * VARIANTS + lum[i]].append(mk(sx, sy))
        return buckets, sparks

    def _radial(self):
        """Per-particle radial multipliers while the sphere assembles (from scattered) or a shockwave passes."""
        out = []
        asm, shock = self.asm, self.shock
        w = None
        if shock is not None:
            w = ease_out(shock / 1.4) * 1.5        # the wavefront's radius
        for i in range(self.n):
            m = 1.0
            if asm < 1.0:
                m += (1.0 - ease_out((asm - self.delay[i]) / 0.55)) * self.scat[i]
            if w is not None:
                m += 0.16 * math.exp(-((self.rr[i] - w) / 0.16) ** 2) * (1.0 - shock / 1.4)
            out.append(m)
        return out

    def sparkle_alpha(self, i):
        return (0.5 + 0.5 * math.sin(self.t * self.srate[i] + self.sph[i])) ** 2


def ring(field_t, progress, n=150, tilt=1.12, roll=0.32):
    """A tilted ring of n points around the sphere. Returns [(x, y, z, lit, head)] in unit coordinates (ring radius 1).
    `lit` points are the plan's finished fraction; `head` marks the point leading the lit arc."""
    out = []
    ct, st = math.cos(tilt), math.sin(tilt)
    cr, sr = math.cos(roll), math.sin(roll)
    lit_n = int(round(clamp(progress) * n))
    spin = field_t * 0.35
    for i in range(n):
        a = TAU * i / n - math.pi / 2          # i = 0 at the top, increasing clockwise
        x, y = math.cos(a + spin * 0.0), math.sin(a)
        y, z = y * ct, y * st                  # tilt about the x axis
        x, y = x * cr - y * sr, x * sr + y * cr
        out.append((x, y, z, i < lit_n, i == lit_n - 1))
    return out


def bezier(p0, p1, p2, u):
    a = (1 - u) ** 2
    b = 2 * (1 - u) * u
    c = u * u
    return (a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1])


def courier(t, p0, p1, p2, n=44, speed=0.85):
    """Particles streaming along a curve from p0 (the sphere) to p2 (the provider being called). -> [(x, y, alpha, size, u)]"""
    out = []
    for i in range(n):
        u = (t * speed + i / n) % 1.0
        x, y = bezier(p0, p1, p2, u)
        out.append((x, y, math.sin(math.pi * u) ** 0.6, 1.2 + 1.8 * (1.0 - abs(2 * u - 1.0)), u))
    return out


class Quality:
    """Adaptive detail: if frames stay slow the particle count steps down a level (never back up, so it cannot flap)."""

    def __init__(self, level=0, limit_ms=34.0, patience=45):
        self.level, self.limit, self.patience = level, limit_ms, patience
        self.ema, self.since = 0.0, 0

    @property
    def n(self):
        return LEVELS[self.level]

    def record(self, ms):
        self.ema = ms if self.ema == 0.0 else self.ema * 0.9 + ms * 0.1
        self.since += 1
        if self.ema > self.limit and self.since >= self.patience and self.level < len(LEVELS) - 1:
            self.level += 1
            self.ema, self.since = 0.0, 0
            return True
        return False
