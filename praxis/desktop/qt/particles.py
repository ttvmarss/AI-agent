"""The particle engine behind the PRAXIS core ("The Loom"). Toolkit-free (pure math) so every behaviour is unit-testable.

The picture: a galaxy of particles streaming along spiral arms around a bright seed, crossed by three gimbal rings.
It is driven by REAL state, not decoration:

  arm flow       INWARD while PRAXIS is thinking (it is taking your goal in), still when it needs you,
                 OUTWARD when a result is verified (it is giving something back)
  colour, spin   the state (`Dynamics.set_mode`); STOP collapses it fast
  PLAN ring      the planning stage; ACT ring: one arc per real step; VERIFY ring: one arc per real check
  seed flare     every real event pulses it
  comet tails    particles that leave a trail along their arm
"""
import math
import random

TAU = math.tau

# palette top -> bottom of the picture (blue -> periwinkle -> violet -> orchid -> pink), as in the reference
PALETTE = [(0x4f, 0x8c, 0xff), (0x6f, 0x86, 0xff), (0x8d, 0x7c, 0xff), (0xb0, 0x78, 0xff), (0xd2, 0x70, 0xe6),
           (0xf0, 0x6c, 0xc4), (0xff, 0x6b, 0xa0)]
SEED_WHITE = (0xff, 0xf4, 0xe0)
SPARKLE = [(0xff, 0xd3, 0x6b), (0xff, 0xf2, 0xc4), (0xae, 0xf0, 0xff)]     # warm gold, white, ice
BUCKETS = 14                    # palette steps from the top of the picture to the bottom; bucket BUCKETS is the white core
NB = BUCKETS + 1
VARIANTS = 3                    # faded / ordinary / on-the-arm-centre
LEVELS = [2500, 1700, 1100, 600]
ARMS = 3
ASP = 1.45                      # widescreen stretch: the hero is far wider than tall
GAL = 1.18                      # overall size of the galaxy and rings relative to the widget's radius unit
PITCH = 1.7                    # how tightly the arms wind
RMIN = 0.05
TS = 512                        # radial lookup resolution (a table instead of pow()/log() for every particle)
HALO_SHARE = 0.18
COMETS = 34
TAIL = 8

# what each state looks like. flow: arm flow in arm-lengths/second (negative = inward). spin: rad/s of the whole galaxy.
# rspin: ring spin multiplier. scale: size. amp/hz: breathing. jit: angular shiver. tint/mix: state colour and how much of it.
MODE = {
    "idle":     dict(flow=0.035, spin=0.10, rspin=1.0, scale=1.00, amp=0.020, hz=0.22, jit=0.000, tint=(0x8d, 0x7c, 0xff), mix=0.00, bright=1.00),
    "starting": dict(flow=-0.25, spin=0.50, rspin=2.5, scale=1.00, amp=0.020, hz=0.50, jit=0.002, tint=(0x9f, 0xd8, 0xff), mix=0.35, bright=1.00),
    "working":  dict(flow=-0.17, spin=0.28, rspin=2.0, scale=1.04, amp=0.030, hz=0.90, jit=0.002, tint=(0x4f, 0xd8, 0xff), mix=0.50, bright=1.10),
    "waiting":  dict(flow=0.000, spin=0.03, rspin=0.12, scale=0.94, amp=0.035, hz=0.45, jit=0.000, tint=(0xff, 0xb8, 0x4a), mix=0.62, bright=1.00),
    "ok":       dict(flow=0.220, spin=0.20, rspin=1.2, scale=1.02, amp=0.020, hz=0.30, jit=0.000, tint=(0x3d, 0xe3, 0xa1), mix=0.60, bright=1.15),
    "bad":      dict(flow=-0.020, spin=0.05, rspin=0.3, scale=0.97, amp=0.010, hz=0.20, jit=0.020, tint=(0xff, 0x5d, 0x73), mix=0.70, bright=0.95),
    "stopping": dict(flow=-0.700, spin=1.20, rspin=5.0, scale=0.50, amp=0.010, hz=0.80, jit=0.008, tint=(0xff, 0xb8, 0x4a), mix=0.50, bright=1.00),
    "stopped":  dict(flow=0.020, spin=0.08, rspin=0.4, scale=0.98, amp=0.020, hz=0.25, jit=0.000, tint=(0xff, 0xb8, 0x4a), mix=0.40, bright=0.90),
}
FAST_MODES = ("stopping",)       # these snap quickly: a kill switch must look like one

# the three gimbal rings: PLAN (outer), ACT (middle), VERIFY (inner). tilt/roll orient each ring; spin is its own turn rate
RINGS = [dict(name="plan", rad=1.30, tilt=1.05, roll=0.52, spin=0.30, n=150),
         dict(name="act", rad=1.12, tilt=-0.62, roll=-0.32, spin=-0.22, n=170),
         dict(name="verify", rad=0.94, tilt=0.30, roll=1.22, spin=0.16, n=140)]
CAM_TILT = 1.0                   # how far the galaxy is tipped away from face-on (0 = a full circle)
CAM_ROLL = -0.30
GAP = 0.20                       # fraction of each ring segment left empty so the segments read as separate arcs


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def palette_at(u):
    """Colour at height u (0 = top ... 1 = bottom)."""
    u = clamp(u) * (len(PALETTE) - 1)
    i = min(int(u), len(PALETTE) - 2)
    return mix(PALETTE[i], PALETTE[i + 1], u - i)


def bucket_colour(b):
    return SEED_WHITE if b >= BUCKETS else palette_at((b + 0.5) / BUCKETS)


def ease_out(x):
    x = clamp(x)
    return 1.0 - (1.0 - x) ** 3


def _lut():
    rt, sp = [], []
    for k in range(TS + 1):
        s = k / TS
        r = RMIN + (1.0 - RMIN) * s ** 1.15                         # denser near the core, but the outer arms stay populated
        rt.append(r)
        sp.append(math.log(r / RMIN))                              # logarithmic spiral phase at that radius
    return rt, sp


RT, SPT = _lut()


class Dynamics:
    """Eased parameters. Switching state never snaps (except STOP): values glide toward the new mode's targets."""

    KEYS = ("flow", "spin", "rspin", "scale", "amp", "hz", "jit", "mix", "bright")

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


class Nebula:
    def __init__(self, n=LEVELS[0], seed=11):
        self.seed = seed
        self.dyn = Dynamics()
        self.t = 0.0
        self.rot = 0.0                        # rotation of the whole galaxy
        self.sflow = 0.0                      # accumulated arm flow (the integral of dyn.flow)
        self.rphi = 0.0                       # accumulated ring spin
        self.asm = 0.0                        # 0 = scattered / rings closed, 1 = assembled
        self.shock = None                     # seconds since a success shockwave started
        self.flare = 0.0                      # seed flare, decays after each real event
        self.tilt = [0.0, 0.0]                # camera offsets from the cursor, smoothed toward tilt_target
        self.tilt_target = [0.0, 0.0]
        self.build(n)

    # -- construction -----------------------------------------------------------------------------------------
    def build(self, n):
        rnd = random.Random(self.seed)
        n_halo = int(n * HALO_SHARE)
        self.nd, self.nh, self.n = n - n_halo, n_halo, n
        self.S0, self.ARM, self.G, self.H = [], [], [], []
        self.spark, self.sph, self.srate, self.shue, self.scat_d = [], [], [], [], []
        for _ in range(self.nd):
            self.S0.append(rnd.random())
            self.ARM.append(TAU * rnd.randrange(ARMS) / ARMS)
            self.G.append(rnd.gauss(0.0, 0.55))
            self.H.append(rnd.gauss(0.0, 0.06))
            self.spark.append(rnd.random() < 0.013)
            self.sph.append(rnd.uniform(0, TAU)); self.srate.append(rnd.uniform(1.2, 3.6)); self.shue.append(rnd.randrange(3))
            self.scat_d.append((0.8 + 2.4 * rnd.random(), rnd.random() * 0.4))
        # a sparse spherical halo: depth and parallax around the disc
        self.HX, self.HY, self.HZ, self.HR, self.scat_h = [], [], [], [], []
        for _ in range(self.nh):
            c = rnd.uniform(-1, 1); sn = math.sqrt(1 - c * c); a = rnd.uniform(0, TAU)
            r = 0.55 + 0.6 * rnd.random() ** 0.8
            self.HX.append(sn * math.cos(a)); self.HY.append(c); self.HZ.append(sn * math.sin(a)); self.HR.append(r)
            self.scat_h.append((0.8 + 2.4 * rnd.random(), rnd.random() * 0.4))
        self.comet_ids = [i for i in range(self.nd) if not self.spark[i]][:COMETS]

    def resize(self, n):
        if n != self.n:
            self.build(n)

    # -- time -------------------------------------------------------------------------------------------------------
    def restart_assembly(self):
        self.asm = 0.0

    def trigger_shock(self):
        self.shock = 0.0

    def pulse(self, amount=1.0):
        """A real event: the seed flares."""
        self.flare = min(1.6, self.flare + amount)

    def advance(self, dt):
        dt = clamp(dt, 0.0, 0.25)       # a stalled frame must not make everything jump
        self.t += dt
        self.dyn.step(dt)
        v = self.dyn.v
        self.rot = (self.rot + v["spin"] * dt) % TAU
        self.sflow += v["flow"] * dt
        self.rphi = (self.rphi + v["rspin"] * dt) % (TAU * 64)
        if self.asm < 1.0:
            self.asm = min(1.0, self.asm + dt / 2.2)
        if self.shock is not None:
            self.shock += dt
            if self.shock > 1.4:
                self.shock = None
        self.flare = max(0.0, self.flare - dt * 1.4)
        for i in (0, 1):
            self.tilt[i] += (self.tilt_target[i] - self.tilt[i]) * (1.0 - math.exp(-dt * 5.0))

    # -- geometry ----------------------------------------------------------------------------------------------------
    def tint_colour(self):
        return self.dyn.tint, self.dyn.v["mix"]

    def _cam(self):
        tau = CAM_TILT + self.tilt[0]
        rho = CAM_ROLL + self.tilt[1] * 0.6
        return math.cos(tau), math.sin(tau), math.cos(rho), math.sin(rho)

    def _scale(self, R):
        d = self.dyn.v
        return R * GAL * d["scale"] * (1.0 + d["amp"] * math.sin(self.t * d["hz"] * TAU))

    def _radial_disc(self, i, r):
        m = 1.0
        if self.asm < 1.0:
            scat, dly = self.scat_d[i]
            m += (1.0 - ease_out((self.asm - dly) / 0.55)) * scat
        if self.shock is not None:
            m += 0.16 * math.exp(-((r - ease_out(self.shock / 1.4) * 1.5) / 0.16) ** 2) * (1.0 - self.shock / 1.4)
        return m

    def pos(self, i, s, cx, cy, R):
        """Screen position (x, y, z2) of disc particle i at arm phase s. Used for comet tails and by the tests."""
        ct, st, cr, sr = self._cam()
        sc = self._scale(R)
        k = int(clamp(s) * TS)
        r = RT[k]
        phi = self.ARM[i] + PITCH * SPT[k] + self.G[i] * (0.18 + 0.5 * r) + self.rot
        x, y, z = r * math.cos(phi), r * math.sin(phi), self.H[i] * (0.4 + r)
        y2, z2 = y * ct - z * st, y * st + z * ct
        X, Y = x * cr - y2 * sr, x * sr + y2 * cr
        m = sc * (1.0 + 0.2 * z2) * (self._radial_disc(i, r) if (self.asm < 1.0 or self.shock is not None) else 1.0)
        return cx + X * m * ASP, cy - Y * m, z2

    # -- projection -------------------------------------------------------------------------------------------------------
    def project(self, cx, cy, R, mk=lambda x, y: (x, y)):
        """-> (buckets, sparks). buckets[(b*3 + depth)*VARIANTS + variant] is a list of points (mk(x, y)); depth 0 = back
        ... 2 = front; b = BUCKETS is the white core. sparks: [(x, y, depth01, i)] drawn individually with a glow."""
        d = self.dyn.v
        sc = self._scale(R)
        ct, st, cr, sr = self._cam()
        t, flow, rot = self.t, self.sflow, self.rot
        shiver = d["jit"]
        buckets = [[] for _ in range(NB * 3 * VARIANTS)]
        sparks = []
        S0, ARM, G, H, spark = self.S0, self.ARM, self.G, self.H, self.spark
        rt, spt, pitch = RT, SPT, PITCH
        cos, sin = math.cos, math.sin
        inv = 1.0 / (0.95 * sc) if sc else 0.0
        slow = self.asm < 1.0 or self.shock is not None
        top = BUCKETS - 0.001
        for i in range(self.nd):
            s = (S0[i] + flow) % 1.0
            k = int(s * TS)
            r = rt[k]
            phi = ARM[i] + pitch * spt[k] + G[i] * (0.18 + 0.5 * r) + rot
            if shiver:
                phi += shiver * sin(t * 11.0 + i)
            x, y, z = r * cos(phi), r * sin(phi), H[i] * (0.4 + r)
            y2 = y * ct - z * st
            z2 = y * st + z * ct
            X, Y = x * cr - y2 * sr, x * sr + y2 * cr
            f = (1.0 + 0.2 * z2) * sc
            if slow:
                f *= self._radial_disc(i, r)
            px, py = cx + X * f * ASP, cy - Y * f
            if spark[i]:
                sparks.append((px, py, 0.5 + 0.5 * z2, i))
                continue
            u = (py - cy) * inv
            b = BUCKETS if r < 0.06 else int((0.5 + 0.5 * (-1.0 if u < -1.0 else 1.0 if u > 1.0 else u)) * top)
            fade = s * 7.0 if s * 7.0 < (1.0 - s) * 5.0 else (1.0 - s) * 5.0
            lm = 0 if fade < 0.55 else (2 if -0.45 < G[i] < 0.45 else 1)
            buckets[((b * 3) + (0 if z2 < -0.25 else 1 if z2 < 0.25 else 2)) * VARIANTS + lm].append(mk(px, py))
        hr = self.HR
        hc, hs = cos(rot * 0.6), sin(rot * 0.6)
        for j in range(self.nh):
            r = hr[j]
            x0, y0, z0 = self.HX[j], self.HY[j], self.HZ[j]
            x, z = x0 * hc - z0 * hs, x0 * hs + z0 * hc
            m = r
            if slow:
                scat, dly = self.scat_h[j]
                m = r * (1.0 + (1.0 - ease_out((self.asm - dly) / 0.55)) * scat)
            y2 = y0 * ct - z * st
            z2 = y0 * st + z * ct
            X, Y = x * cr - y2 * sr, x * sr + y2 * cr
            f = (1.0 + 0.2 * z2) * sc * m
            py = cy - Y * f
            u = (py - cy) * inv
            b = int((0.5 + 0.5 * (-1.0 if u < -1.0 else 1.0 if u > 1.0 else u)) * top)
            buckets[((b * 3) + (0 if z2 < -0.25 else 1 if z2 < 0.25 else 2)) * VARIANTS + 0].append(mk(cx + X * f * ASP, py))
        return buckets, sparks

    def sparkle_alpha(self, i):
        return (0.5 + 0.5 * math.sin(self.t * self.srate[i] + self.sph[i])) ** 2

    def comets(self, cx, cy, R):
        """Particles that leave a glowing trail along their arm. -> [[(x, y, alpha, size), ...]] head first."""
        out = []
        for i in self.comet_ids:
            s = (self.S0[i] + self.sflow) % 1.0
            d = 1.0 if self.dyn.v["flow"] >= 0 else -1.0          # the tail trails BEHIND the direction of flow
            tail = []
            for j in range(TAIL):
                sj = (s - d * j * 0.012) % 1.0
                x, y, z2 = self.pos(i, sj, cx, cy, R)
                fade = min(sj * 7.0, (1.0 - sj) * 5.0)
                tail.append((x, y, clamp(fade) * (1.0 - j / TAIL) ** 1.6, 2.2 * (1.0 - 0.6 * j / TAIL)))
            out.append(tail)
        return out

    # -- the gimbal rings -----------------------------------------------------------------------------------------------
    def ring(self, which, cx, cy, R, n=None):
        """Points of ring `which` (0 plan, 1 act, 2 verify) in screen coordinates: [(x, y, z, index)], index counts around the
        ring from its top. z > 0 means in front of the galaxy plane."""
        spec = RINGS[which]
        n = n or spec["n"]
        ct, st, cr, sr = self._cam()
        sc = self._scale(R) * ease_out(self.asm) * spec["rad"]
        tilt = spec["tilt"] + 0.08 * math.sin(self.t * 0.31 + which)
        ctl, stl = math.cos(tilt), math.sin(tilt)
        crl, srl = math.cos(spec["roll"]), math.sin(spec["roll"])
        spin = self.rphi * spec["spin"]
        out = []
        for i in range(n):
            a = TAU * i / n - math.pi / 2 + spin
            x, y = math.cos(a), math.sin(a)
            y, z = y * ctl, y * stl                       # the ring's own tilt
            x, y = x * crl - y * srl, x * srl + y * crl   # and roll
            y2 = y * ct - z * st                          # then the camera
            z2 = y * st + z * ct
            X, Y = x * cr - y2 * sr, x * sr + y2 * cr
            f = (1.0 + 0.2 * z2) * sc
            out.append((cx + X * f * ASP, cy - Y * f, z2, i))
        return out


def ring_extent():
    """(half-width, half-height) of the largest ring in units of the widget's radius R, over a full ring precession at the
    default camera. Nodes sit outside the width; the height decides how big R may be."""
    n = Nebula(60)
    n.asm = 1.0                                   # measured with the rings unfolded (a fresh Nebula starts closed)
    hw = hh = 0.0
    for step in range(12):
        n.t = step * 0.55                         # the ring tilt wobbles over time: take the worst case
        for k in range(3):
            for x, y, z, i in n.ring(k, 0.0, 0.0, 1.0, 120):
                hw, hh = max(hw, abs(x)), max(hh, abs(y))
    return hw, hh


def segment_of(i, n, segs):
    """Which segment point i of n belongs to, and where in it (0..1); None inside the gap between segments."""
    if segs <= 0:
        return None
    pos = i * segs / n
    seg = min(int(pos), segs - 1)
    frac = pos - seg
    return None if frac > 1.0 - GAP and segs > 1 else (seg, min(1.0, frac / (1.0 - GAP if segs > 1 else 1.0)))


def bezier(p0, p1, p2, u):
    a = (1 - u) ** 2
    b = 2 * (1 - u) * u
    c = u * u
    return (a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1])


def courier(t, p0, p1, p2, n=44, speed=0.85):
    """Particles streaming along a curve from p0 (the galaxy) to p2 (the provider being called). -> [(x, y, alpha, size, u)]"""
    out = []
    for i in range(n):
        u = (t * speed + i / n) % 1.0
        x, y = bezier(p0, p1, p2, u)
        out.append((x, y, math.sin(math.pi * u) ** 0.6, 1.2 + 1.8 * (1.0 - abs(2 * u - 1.0)), u))
    return out


class Quality:
    """Adaptive detail: if frames stay slow the particle count steps down a level (never back up, so it cannot flap)."""

    def __init__(self, level=0, limit_ms=40.0, patience=45):
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
