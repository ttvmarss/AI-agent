"""Colours for the HUD spec. A colour is "#rrggbb", "#rrggbbaa", [r,g,b(,a)], a palette name, {"mix":[a,b,t]}, {"persona":[jarvis_side,friday_side]}
or "=expression" (which must return one of the above as text). Everything resolves to (r, g, b, a) with r,g,b in 0..255 and a in 0..1."""
from .expr import ExprError, compile_expr

BLACK = (0.0, 0.0, 0.0, 1.0)


def parse_hex(s):
    h = s.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        raise ValueError(f"bad colour {s!r}")
    v = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
    return (float(v[0]), float(v[1]), float(v[2]), (v[3] / 255.0) if len(v) == 4 else 1.0)


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


class Palette:
    def __init__(self, raw, issues):
        self.raw = dict(raw or {})
        self.issues = issues
        self._const = {}            # name -> (r,g,b,a) when it does not depend on the persona
        self._fn = {}               # name -> closure(ctx) when it does
        for name in self.raw:
            self._build(name, [])

    def names(self):
        return set(self.raw)

    def _build(self, name, stack):
        if name in self._const or name in self._fn:
            return
        if name in stack:
            self.issues.append((f"palette.{name}", "error", "colours refer to each other in a loop"))
            self._const[name] = BLACK
            return
        v = self.raw[name]
        r = self._compile(v, f"palette.{name}", stack + [name])
        if callable(r):
            self._fn[name] = r
        else:
            self._const[name] = r

    def _compile(self, v, path, stack):
        """-> a constant (r,g,b,a) or a closure(ctx) -> (r,g,b,a)."""
        try:
            if isinstance(v, str):
                if v.startswith("="):
                    e = compile_expr(v[1:], default="")

                    def dyn(ctx):
                        return self.lookup(e(ctx), ctx)
                    return dyn
                if v.startswith("#"):
                    return parse_hex(v)
                if v in self.raw:
                    self._build(v, stack)
                    if v in self._fn:
                        f = self._fn[v]
                        return f
                    return self._const[v]
                raise ValueError(f"unknown colour name {v!r}")
            if isinstance(v, (list, tuple)) and len(v) in (3, 4) and all(isinstance(x, (int, float)) for x in v):
                return (float(v[0]), float(v[1]), float(v[2]), float(v[3]) if len(v) == 4 else 1.0)
            if isinstance(v, dict) and "persona" in v:
                a, b = (self._compile(x, path, stack) for x in v["persona"])
                return lambda ctx: mix(a(ctx) if callable(a) else a, b(ctx) if callable(b) else b, ctx.get("persona", 0.0))
            if isinstance(v, dict) and "mix" in v:
                a, b, t = v["mix"]
                a, b = self._compile(a, path, stack), self._compile(b, path, stack)
                if not callable(a) and not callable(b) and isinstance(t, (int, float)) and not isinstance(t, bool):
                    return mix(a, b, float(t))                                 # all constants: mixed once, not every frame
                te = compile_expr(t if isinstance(t, str) else repr(float(t)))
                return lambda ctx: mix(a(ctx) if callable(a) else a, b(ctx) if callable(b) else b, te(ctx))
            if isinstance(v, dict) and "alpha" in v and "of" in v:
                base = self._compile(v["of"], path, stack)
                if not callable(base) and isinstance(v["alpha"], (int, float)) and not isinstance(v["alpha"], bool):
                    return (base[0], base[1], base[2], base[3] * float(v["alpha"]))
                al = compile_expr(v["alpha"] if isinstance(v["alpha"], str) else repr(float(v["alpha"])))
                return lambda ctx: (lambda c: (c[0], c[1], c[2], c[3] * al(ctx)))(base(ctx) if callable(base) else base)
            raise ValueError(f"cannot read colour {v!r}")
        except (ValueError, ExprError, TypeError, KeyError) as e:
            self.issues.append((path, "error", str(e)))
            return BLACK

    def compile(self, v, path):
        return self._compile(v, path, [])

    def lookup(self, v, ctx):
        """A colour at run time from text ("ok", "#ff0000"), a tuple, or a palette name."""
        try:
            if isinstance(v, str):
                if v in self._const:
                    return self._const[v]
                if v in self._fn:
                    return self._fn[v](ctx)
                if v.startswith("#"):
                    return parse_hex(v)
            elif isinstance(v, (tuple, list)) and len(v) in (3, 4):
                return (float(v[0]), float(v[1]), float(v[2]), float(v[3]) if len(v) == 4 else 1.0)
        except (ValueError, TypeError):
            pass
        return BLACK
