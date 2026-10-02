"""Holographic finish for the Loom. Pure functions of time (no Qt), so every effect is testable and bounded.

A hologram is light in the air, so it is never perfectly steady: a faint flicker, a bright line that sweeps up through it, a rare
horizontal glitch, a ghost image offset by a pixel or two. It stands on a projector: an emitter ring on a perspective grid with a
beam of light rising from it. All of it is decoration; none of it carries data."""
import math

GLITCH_EVERY = 7.3            # seconds between glitches (one every few seconds is alive; more is a broken display)
GLITCH_LEN = 0.14
SWEEP_PERIOD = 5.5


def _t(t):
    """Time that is always safe to feed a trig function: finite, and wrapped so a session left on for weeks keeps its precision."""
    try:
        t = float(t)
    except (TypeError, ValueError):
        return 0.0
    if t != t or t in (float("inf"), float("-inf")):
        return 0.0
    return t % 100000.0


def _h(x):
    """A small deterministic hash -> [0, 1). Same input, same output, no state."""
    return (math.sin(x * 127.1 + 311.7) * 43758.5453) % 1.0


def flicker(t):
    """Brightness multiplier in [0.88, 1]: a slow shimmer plus a rare short dip."""
    t = _t(t)
    base = 0.965 + 0.035 * math.sin(t * 9.0) * math.sin(t * 2.3 + 1.0)
    cell = math.floor(t * 3.0)
    dip = 0.0
    if _h(cell) > 0.93:                               # about one cell in fourteen
        f = (t * 3.0) - cell
        dip = 0.09 * math.sin(math.pi * f)
    return max(0.88, min(1.0, base - dip))


def glitch(t):
    """(active, y_fraction, dx_pixels): a rare, brief horizontal tear. Inactive almost always."""
    t = _t(t)
    k = math.floor(t / GLITCH_EVERY)
    start = k * GLITCH_EVERY + 1.0 + 4.0 * _h(k + 0.5)
    if start <= t < start + GLITCH_LEN:
        return True, 0.15 + 0.7 * _h(k + 1.7), (-1.0 if _h(k + 2.9) < 0.5 else 1.0) * (3.0 + 5.0 * _h(k + 3.3))
    return False, 0.0, 0.0


def sweep(t):
    """Fraction (0 top .. 1 bottom) of the bright scan line that rises through the projection, and its strength."""
    t = _t(t)
    f = (t % SWEEP_PERIOD) / SWEEP_PERIOD
    return 1.0 - f, math.sin(math.pi * f)


def ghost_offset(t):
    """The faint second image: a pixel or two to the side, drifting."""
    t = _t(t)
    return 1.4 + 0.8 * math.sin(t * 0.7), 0.4 * math.sin(t * 1.3)


def grid_lines(n_rings=6, n_spokes=18, t=0.0):
    """The projector floor as (ring radii fractions, spoke angles): rings expand slowly outward and fade, like a pulse."""
    t = _t(t)
    rings = [((i + (t * 0.18) % 1.0) / n_rings) for i in range(n_rings)]
    spokes = [2 * math.pi * i / n_spokes + t * 0.05 for i in range(n_spokes)]
    return rings, spokes


def ring_alpha(frac):
    """Fade for a floor ring at radius fraction frac in [0, 1]: invisible at the centre and at the rim."""
    f = max(0.0, min(1.0, frac))
    return math.sin(math.pi * f) ** 1.5
