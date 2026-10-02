"""The animation state behind the HUD. Toolkit-free (pure math), so every behaviour is unit-testable.

State changes never snap: every number in the spec's `modes` table glides toward the new state's value (STOP is the exception: a kill switch
must look like one). Real events flare the core, send ripples and light hexagon waves; a verified goal sends a shockwave. All of it is driven
by real state, never by decoration alone."""
import math
import random

TAU = math.tau
LEVELS = [80, 52, 30, 14]          # ember counts per quality level (the governor steps down through these)
FLOW_LEVELS = [44, 30, 18, 8]      # inward energy streaks
BOLT_MAX = [5, 4, 2, 1]            # simultaneous energy arcs
BAR_LEVELS = [96, 72, 48, 32]      # voice bars
FAST_MODES = ("stopping",)
BOOT_S = 3.6


def clamp(x, lo=0.0, hi=1.0):
    if x != x:                                  # NaN compares false with everything, so it would sail through: it becomes the lower bound
        return lo
    return lo if x < lo else hi if x > hi else x


def ease_out(x):
    x = clamp(x)
    return 1.0 - (1.0 - x) ** 3


class Quality:
    """Watches frame times and lowers the detail level when the machine cannot keep up (and raises it again when it can)."""

    def __init__(self, budget_ms=34.0, window=45):
        self.level, self.budget, self.window, self.samples, self.good = 0, budget_ms, window, [], 0

    def record(self, ms):
        self.samples.append(ms)
        if len(self.samples) < self.window:
            return False
        avg = sum(self.samples) / len(self.samples)
        self.samples = []
        if avg > self.budget and self.level < 3:
            self.level += 1; self.good = 0
            return True
        if avg < self.budget * 0.55:
            self.good += 1
            if self.good >= 4 and self.level > 0:
                self.level -= 1; self.good = 0
                return True
        else:
            self.good = 0
        return False


class Motion:
    def __init__(self, modes, persona_rate=1.4, seed=7, mode="starting", boot=None):
        self.rng = random.Random(seed)
        self.modes = modes
        self.keys = [k for k, v in modes["idle"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        self.persona_rate = persona_rate
        b = boot or {}
        self.boot_s = float(b.get("seconds", BOOT_S))              # how long the HUD takes to draw itself in
        self.boot_delay, self.boot_span = float(b.get("delay", 0.055)), float(b.get("span", 0.32))
        self.mode = mode if mode in modes else "idle"
        self.rate = 3.5
        self.v = {k: float(modes[self.mode].get(k, 0.0)) for k in self.keys}
        self.t = 0.0
        self.rot_a = self.rot_b = self.rot_c = self.sweep = 0.0       # degrees
        self.flare, self.shock, self.power, self.boot = 0.0, None, 0.0, 0.0
        self.level = 0
        self.embers, self.bolts, self.flow, self.ripples, self.waves = [], [], [], [], []
        self.flow_cap, self.bolt_cap, self.n_embers = FLOW_LEVELS[0], BOLT_MAX[0], LEVELS[0]
        self._ember_acc = self._bolt_acc = 0.0
        self._ambient = 4.0

    # ---- control ------------------------------------------------------------------------------------------------
    def set_mode(self, mode):
        if mode in self.modes and mode != self.mode:
            self.mode = mode
            self.rate = 12.0 if mode in FAST_MODES else 3.5

    def restart_power_up(self):
        self.power = self.boot = 0.0

    def set_level(self, level):
        level = int(clamp(level, 0, 3))
        self.level = level
        self.flow_cap, self.bolt_cap, self.n_embers = FLOW_LEVELS[level], BOLT_MAX[level], LEVELS[level]
        del self.bolts[self.bolt_cap:]
        del self.embers[self.n_embers:]

    def trigger_shock(self):
        self.shock = 0.0
        self.waves.append(self.t)

    def pulse(self, amount=1.0):
        self.flare = min(1.5, self.flare + 0.7 * amount)
        for _ in range(2 if amount >= 0.8 else 1):
            self._spawn_bolt()
        self.waves = (self.waves + [self.t])[-4:]

    def ripple(self, colour_key="accent", force=False, min_gap=0.14):
        if not force and self.ripples and self.t - self.ripples[-1][0] < min_gap:
            return
        self.ripples = (self.ripples + [(self.t, colour_key)])[-6:]

    def reveal(self, k, delay=None, span=None):
        """How far element k of the start-up sequence has drawn in, 0..1 (elements arrive one after another)."""
        d = self.boot_delay if delay is None else delay
        s = self.boot_span if span is None else span
        return ease_out((self.boot - min(k * d, max(0.0, 1.0 - s))) / s)      # an index past the end of the sequence arrives with the last one, never never

    def _spawn_bolt(self):
        if len(self.bolts) >= self.bolt_cap:
            return
        a = self.rng.uniform(0, TAU)
        pts = []
        n = 9
        for i in range(n + 1):
            off = 0.0 if i in (0, n) else self.rng.uniform(-0.05, 0.05)
            pts.append((i / n, off))                                   # (distance along 0..1, sideways offset in units of the radius)
        self.bolts.append({"a": a, "pts": pts, "age": 0.0, "life": self.rng.uniform(0.18, 0.36)})

    # ---- time ---------------------------------------------------------------------------------------------------
    def advance(self, dt):
        if not math.isfinite(dt):                      # NaN or infinity: ignore the step entirely (the old widget did too)
            return
        dt = clamp(dt, 0.0, 0.25)
        if dt <= 0.0:
            return
        self.t += dt
        tgt = self.modes[self.mode]
        k = 1.0 - math.exp(-dt * self.rate)
        for key in self.keys:
            if key == "persona":
                continue
            self.v[key] += (float(tgt.get(key, self.v[key])) - self.v[key]) * k
        kp = 1.0 - math.exp(-dt * (self.persona_rate if self.mode not in FAST_MODES else 12.0))
        self.v["persona"] += (float(tgt.get("persona", self.v["persona"])) - self.v["persona"]) * kp
        v = self.v
        self.power = min(1.0, self.power + dt / 2.2)
        self.boot = min(1.0, self.boot + dt / max(0.2, self.boot_s))
        self.sweep = (self.sweep + math.degrees(v["sweep"]) * dt) % 360.0
        self.rot_a = (self.rot_a + math.degrees(v["spin"]) * dt) % 360.0
        self.rot_b = (self.rot_b + math.degrees(v["tick"]) * dt) % 360.0
        self.rot_c = (self.rot_c - math.degrees(v["spin"]) * 0.6 * dt - 3.0 * dt) % 360.0
        self.flare = max(0.0, self.flare - dt * 1.8)
        if self.shock is not None:
            self.shock += dt / 1.4
            if self.shock >= 1.0:
                self.shock = None
        self._ambient -= dt
        if self._ambient <= 0:                                           # a faint pulse through the grid every few seconds, like a heartbeat
            self._ambient = 8.0
            self.waves = (self.waves + [self.t])[-4:]
        self.waves = [w for w in self.waves if self.t - w < 3.0]
        self.ripples = [r for r in self.ripples if self.t - r[0] < 1.6]
        # energy arcs
        self._bolt_acc += dt * v["bolts"] * (1.0 + 2.0 * self.flare)
        while self._bolt_acc >= 1.0:
            self._bolt_acc -= 1.0
            self._spawn_bolt()
        self._bolt_acc = min(self._bolt_acc, 2.0)
        for b in self.bolts:
            b["age"] += dt
        self.bolts = [b for b in self.bolts if b["age"] < b["life"]]
        # streaks spiral inward while it works (taking the goal in), outward when a goal verifies (giving something back)
        want = int(v["flow"] * self.flow_cap / FLOW_LEVELS[0])
        outward = self.mode == "ok"
        while len(self.flow) < want:
            self.flow.append([self.rng.uniform(0, TAU), self.rng.uniform(0.15, 1.0) if not outward else self.rng.uniform(0.1, 0.5), self.rng.uniform(0.12, 0.3)])
        del self.flow[want:]
        for f in self.flow:
            f[0] = (f[0] + (0.6 + 0.8 * (1.1 - f[1])) * dt) % TAU
            f[1] += (f[2] if outward else -f[2]) * dt
            if f[1] < 0.08 or f[1] > 1.0:
                f[1] = 0.1 if outward else 1.0
                f[0] = self.rng.uniform(0, TAU)
        # embers
        self._ember_acc += dt * v["embers"] * self.n_embers / 3.0
        while self._ember_acc >= 1.0 and len(self.embers) < self.n_embers:
            self._ember_acc -= 1.0
            a = self.rng.uniform(0, TAU)
            r = self.rng.uniform(0.55, 0.95)
            self.embers.append([math.cos(a) * r, math.sin(a) * r, self.rng.uniform(-0.04, 0.04), self.rng.uniform(-0.30, -0.10), self.rng.uniform(1.4, 3.2), 0.0])
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

    # ---- values the spec can read -----------------------------------------------------------------------------------
    def core_level(self):
        v = self.v
        base = v["core"] * (1.0 + v["amp"] * math.sin(self.t * TAU * v["hz"]))
        flick = 1.0 - v["jit"] * (0.5 + 0.5 * math.sin(self.t * 47.0) * math.sin(self.t * 13.0))
        return base * flick * (0.25 + 0.75 * ease_out(self.power)) + 0.45 * self.flare

    def frame_vars(self):
        """The motion numbers an expression can use."""
        v = self.v
        return {"t": self.t, "persona": clamp(v["persona"]), "power": self.power, "boot": self.boot, "flare": self.flare,
                "shock": -1.0 if self.shock is None else self.shock, "rot_a": self.rot_a, "rot_b": self.rot_b, "rot_c": self.rot_c,
                "sweep": self.sweep, "core": self.core_level(), "bright": v["bright"], "charge": v["charge"], "quality": self.level}
