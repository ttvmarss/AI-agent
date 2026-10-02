"""A tiny, safe expression language for the HUD spec ("0.4 + 0.1*sin(t*2)", "item.pressure > 0.9", "mode in ('working','waiting')").

Not Python's eval: the source is parsed with `ast`, every node type is checked against a whitelist, and it is compiled to nested closures,
so a spec file can compute and animate things but can never import, open a file, call a method or reach an attribute of a real object.
Evaluation never raises: a bad value becomes 0 (or "" / False) and the first failure of each expression is recorded for the log."""
import ast
import math
import operator

MAX_LEN = 600


class ExprError(ValueError):
    pass


class Obj:
    """A read-only dict with attribute access (`item.pressure`). Missing names read as 0, never as an error."""
    __slots__ = ("_d",)

    def __init__(self, d=None):
        object.__setattr__(self, "_d", d if d is not None else {})

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        return self._d.get(k, 0)

    def __getitem__(self, k):
        return self._d.get(k, 0)

    def __contains__(self, k):
        return k in self._d

    def get(self, k, default=0):
        return self._d.get(k, default)

    def __len__(self):
        return len(self._d)


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def ease(x):
    x = clamp(x)
    return 1.0 - (1.0 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def mixf(a, b, t):
    return a + (b - a) * t


def pulse(t, hz=1.0):
    return 0.5 + 0.5 * math.sin(t * math.tau * hz)


def tri(x):
    x = x % 1.0
    return 1.0 - abs(2.0 * x - 1.0)


def noise(x):
    """Smooth value noise in -1..1 (a few summed sines: cheap, deterministic, no state)."""
    return (math.sin(x * 1.7) * 0.5 + math.sin(x * 2.9 + 1.3) * 0.3 + math.sin(x * 5.3 + 2.1) * 0.2)


def step(edge, x):
    return 1.0 if x >= edge else 0.0


def sat(x):
    return clamp(x, 0.0, 1.0)


def _len(x):
    try:
        return len(x)
    except TypeError:
        return 0


FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "atan2": math.atan2, "sqrt": lambda x: math.sqrt(x) if x > 0 else 0.0,
    "abs": abs, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil, "round": round, "pow": pow, "hypot": math.hypot,
    "rad": math.radians, "deg": math.degrees, "clamp": clamp, "sat": sat, "mix": mixf, "lerp": mixf, "ease": ease, "smooth": ease_in_out,
    "pulse": pulse, "tri": tri, "noise": noise, "step": step, "len": _len, "int": int, "float": float, "fract": lambda x: x - math.floor(x),
    "sign": lambda x: (x > 0) - (x < 0), "exp": lambda x: math.exp(min(x, 50)), "log": lambda x: math.log(x) if x > 0 else 0.0,
}
CONSTS = {"pi": math.pi, "tau": math.tau, "True": True, "False": False, "true": True, "false": False}
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
       ast.Mod: operator.mod, ast.Pow: operator.pow}
CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
       ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


def _fix(v):
    if isinstance(v, float) and (v != v or v in (math.inf, -math.inf)):
        return 0.0
    return v


class Compiled:
    """A compiled expression. Call it with the frame's variables (a dict)."""
    __slots__ = ("src", "fn", "error", "default")

    def __init__(self, src, fn, default=0.0):
        self.src, self.fn, self.error, self.default = src, fn, "", default

    def __call__(self, ctx):
        try:
            return _fix(self.fn(ctx))
        except Exception as e:                                   # a bad value on one frame must never take the window down
            if not self.error:
                self.error = f"{type(e).__name__}: {e}"
            return self.default


def compile_expr(src, default=0.0):
    """-> Compiled. Raises ExprError for a syntax error or anything outside the whitelist (so the spec validator can report it)."""
    if not isinstance(src, str) or not src.strip():
        raise ExprError("empty expression")
    if len(src) > MAX_LEN:
        raise ExprError("expression too long")
    try:
        tree = ast.parse(src.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error: {e.msg}")
    return Compiled(src, _node(tree.body), default)


def _node(n):
    if isinstance(n, ast.Constant):
        if isinstance(n.value, (int, float, str, bool)) or n.value is None:
            v = n.value
            return lambda c: v
        raise ExprError("unsupported constant")
    if isinstance(n, ast.Name):
        name = n.id
        if name in CONSTS:
            v = CONSTS[name]
            return lambda c: v
        if name in FUNCS:
            raise ExprError(f"'{name}' is a function: call it with ()")
        return lambda c: c.get(name, 0)
    if isinstance(n, ast.UnaryOp):
        f = _node(n.operand)
        if isinstance(n.op, ast.USub):
            return lambda c: -f(c)
        if isinstance(n.op, ast.UAdd):
            return lambda c: +f(c)
        if isinstance(n.op, ast.Not):
            return lambda c: not f(c)
        raise ExprError("unsupported unary operator")
    if isinstance(n, ast.BinOp):
        op = BIN.get(type(n.op))
        if op is None:
            raise ExprError("unsupported operator")
        a, b = _node(n.left), _node(n.right)
        if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            def safe(c):
                d = b(c)
                return op(a(c), d) if d else 0.0
            return safe
        if isinstance(n.op, ast.Pow):
            def powf(c):
                x, y = a(c), b(c)
                if abs(y) > 16:
                    return 0.0
                try:
                    r = x ** y
                except (ZeroDivisionError, OverflowError):
                    return 0.0
                return r if not isinstance(r, complex) else 0.0
            return powf
        return lambda c: op(a(c), b(c))
    if isinstance(n, ast.BoolOp):
        fs = [_node(v) for v in n.values]
        if isinstance(n.op, ast.And):
            def andf(c):
                r = True
                for f in fs:
                    r = f(c)
                    if not r:
                        return r
                return r
            return andf

        def orf(c):
            r = False
            for f in fs:
                r = f(c)
                if r:
                    return r
            return r
        return orf
    if isinstance(n, ast.Compare):
        left = _node(n.left)
        rest = []
        for op, comp in zip(n.ops, n.comparators):
            fn = CMP.get(type(op))
            if fn is None:
                raise ExprError("unsupported comparison")
            rest.append((fn, _node(comp)))

        def cmpf(c):
            a = left(c)
            for fn, g in rest:
                b = g(c)
                if not fn(a, b):
                    return False
                a = b
            return True
        return cmpf
    if isinstance(n, ast.IfExp):
        t, a, b = _node(n.test), _node(n.body), _node(n.orelse)
        return lambda c: a(c) if t(c) else b(c)
    if isinstance(n, (ast.Tuple, ast.List)):
        fs = [_node(e) for e in n.elts]
        return lambda c: tuple(f(c) for f in fs)
    if isinstance(n, ast.Call):
        if not isinstance(n.func, ast.Name) or n.func.id not in FUNCS or n.keywords:
            raise ExprError("only the built-in functions can be called")
        fn = FUNCS[n.func.id]
        args = [_node(a) for a in n.args]
        return lambda c: fn(*[a(c) for a in args])
    if isinstance(n, ast.Attribute):
        if n.attr.startswith("_"):
            raise ExprError("private names are not available")
        base, attr = _node(n.value), n.attr

        def getattr_(c):
            b = base(c)
            if isinstance(b, Obj):
                return b._d.get(attr, 0)
            raise TypeError("only data objects have fields")
        return getattr_
    if isinstance(n, ast.Subscript):
        base, idx = _node(n.value), _node(n.slice)

        def sub(c):
            b, i = base(c), idx(c)
            if isinstance(b, Obj):
                return b._d.get(i, 0)
            if isinstance(b, (list, tuple)):
                return b[int(i)] if -len(b) <= int(i) < len(b) else 0
            raise TypeError("cannot index that")
        return sub
    raise ExprError(f"{type(n).__name__} is not allowed in an expression")
