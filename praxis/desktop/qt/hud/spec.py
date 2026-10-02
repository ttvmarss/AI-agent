"""Load, validate and compile a HUD spec (JSON). No Qt in here: `praxis hud validate` and the tests use it on any machine.

compile_spec(raw) -> Spec. A spec with errors is never partially used: Spec.ok is False and Spec.issues says exactly where
(`layers[3].children[0].r: unexpected character`) so a bad edit shows a clear message and the previous good design stays on screen."""
import json
import os

from . import schema as S
from .colors import Palette
from .expr import ExprError, compile_expr

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "default.hud.json")


class Node:
    """One compiled element: constants stay constants, expressions are closures; children are compiled too."""
    __slots__ = ("type", "props", "kids", "path", "boot", "visible", "opacity", "id", "cache", "glow", "cache_key", "cache_persona")

    def __init__(self, type_, path):
        self.type, self.path, self.props, self.kids = type_, path, {}, []
        self.boot = self.visible = self.opacity = None
        self.id, self.cache, self.glow, self.cache_key, self.cache_persona = "", False, False, None, False

    def values(self, ctx, only=None):
        out = {}
        for k, f in self.props.items():
            out[k] = f(ctx) if callable(f) else f
        return out


class Template:
    """"{title}  {stats.cost:.2f}" compiled to parts: literal strings and (expression, format) pairs."""
    __slots__ = ("parts", "src")

    def __init__(self, src, parts):
        self.src, self.parts = src, parts

    def __call__(self, ctx):
        out = []
        for lit, e, fmt in self.parts:
            if e is None:
                out.append(lit)
                continue
            v = e(ctx)
            try:
                out.append(format(v, fmt) if fmt else (("%g" % v) if isinstance(v, float) else str(v)))
            except (ValueError, TypeError):
                out.append(str(v))
        return "".join(out)


def compile_template(src):
    parts, i, lit = [], 0, []
    while i < len(src):
        ch = src[i]
        if ch == "{" and src[i:i + 2] == "{{":
            lit.append("{"); i += 2
        elif ch == "}" and src[i:i + 2] == "}}":
            lit.append("}"); i += 2
        elif ch == "{":
            j = src.find("}", i)
            if j < 0:
                raise ExprError("unclosed { in text")
            body = src[i + 1:j]
            fmt = ""
            if "|" in body:                          # {expr|.2f}: a bar before a Python format spec ("|" is not an operator in this language, so it is unambiguous)
                body, fmt = body.rsplit("|", 1)
                fmt = fmt.strip()
            parts.append(("".join(lit), None, "")); lit = []
            parts.append(("", compile_expr(body, default=""), fmt))
            i = j + 1
        else:
            lit.append(ch); i += 1
    if lit:
        parts.append(("".join(lit), None, ""))
    return Template(src, parts)


class Spec:
    def __init__(self):
        self.raw, self.issues = {}, []
        self.name, self.palette, self.vars, self.modes, self.layers = "", None, [], {}, []
        self.states, self.glyphs, self.persona_rate, self.boot, self.glow_box = {}, {}, 1.4, {}, None
        self.min_size, self.stats_order, self.fonts, self.path, self.mtime = (0, 0), [], {}, "", 0.0

    @property
    def errors(self):
        return [i for i in self.issues if i[1] == "error"]

    @property
    def ok(self):
        return not self.errors

    def report(self):
        return "\n".join(f"{sev.upper():7} {path}: {msg}" for path, sev, msg in self.issues) or "ok"

    def runtime_errors(self):
        """Expressions that failed while drawing (first failure of each): (where, message)."""
        out = []
        def walk(nodes):
            for n in nodes:
                for k, f in n.props.items():
                    if hasattr(f, "error") and f.error:
                        out.append((f"{n.path}.{k}", f.error))
                    elif isinstance(f, Template):
                        for _, e, _ in f.parts:
                            if e is not None and e.error:
                                out.append((f"{n.path}.{k}", e.error))
                for f in (n.visible, n.opacity, n.boot, n.cache_key):
                    if f is not None and hasattr(f, "error") and f.error:
                        out.append((n.path, f.error))
                walk(n.kids)
        walk(self.layers)
        for name, e in self.vars:
            if e.error:
                out.append((f"vars.{name}", e.error))
        return out


def _num(v, path, issues, allow_none=False, default=0.0):
    if v is None:
        return None if allow_none else default
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return compile_expr(v)
        except ExprError as e:
            issues.append((path, "error", f"{e}  in  {v!r}"))
            return default
    issues.append((path, "error", f"expected a number or an expression, got {type(v).__name__}"))
    return default


def _bool(v, path, issues, default=True):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        try:
            return compile_expr(v, default=False)
        except ExprError as e:
            issues.append((path, "error", f"{e}  in  {v!r}"))
            return default
    issues.append((path, "error", "expected true/false or an expression"))
    return default


def _compile_node(raw, path, palette, issues, depth=0):
    if not isinstance(raw, dict):
        issues.append((path, "error", "an element must be an object"))
        return None
    t = raw.get("type")
    if t not in S.ELEMENTS:
        issues.append((path + ".type", "error", f"unknown element type {t!r} (known: {', '.join(sorted(S.ELEMENTS))})"))
        return None
    if depth > 12:
        issues.append((path, "error", "elements are nested too deeply"))
        return None
    node = Node(t, path)
    node.id = str(raw.get("id", ""))
    node.visible = _bool(raw["visible"], path + ".visible", issues) if "visible" in raw else None
    node.opacity = _num(raw["opacity"], path + ".opacity", issues, default=1.0) if "opacity" in raw else None
    node.boot = _num(raw["boot"], path + ".boot", issues, allow_none=True) if "boot" in raw else None
    node.glow = bool(raw.get("glow", False))
    node.cache = bool(raw.get("cache", False))
    node.cache_persona = raw.get("cache") == "persona"       # "persona": redraw the cached layer as the active mind changes (its colours depend on it)
    if "cache_key" in raw:
        node.cache_key = _num(raw["cache_key"], path + ".cache_key", issues)
    schema = S.ELEMENTS[t]
    for k in raw:
        if k in ("type", "id", "visible", "opacity", "boot", "glow", "cache", "cache_key", "note", "//"):
            continue
        if k not in schema:
            issues.append((f"{path}.{k}", "warning", f"'{k}' is not a property of a {t} (ignored)"))
    for k, (kind, default) in schema.items():
        p = f"{path}.{k}"
        v = raw.get(k, default)
        if kind == S.NUM:
            r = _num(v, p, issues, allow_none=default is None, default=default or 0.0)
        elif kind == S.BOOL:
            r = _bool(v, p, issues, default=bool(default))
        elif kind == S.TEXT:
            try:
                r = compile_template(str(v))
                if all(e is None for _, e, _ in r.parts):
                    r = "".join(lit for lit, _, _ in r.parts)
            except ExprError as e:
                issues.append((p, "error", str(e)))
                r = ""
        elif kind == S.COLOR:
            r = palette.compile(v, p) if v is not None else None
        elif kind == S.STR:
            r = str(v)
            if k in S.CHOICES and r not in S.CHOICES[k]:
                issues.append((p, "error", f"must be one of {', '.join(S.CHOICES[k])}"))
                r = S.CHOICES[k][0]
        elif kind == S.SOURCE:
            r = str(v)
            if r and r not in S.SOURCES:
                issues.append((p, "error", f"unknown data source {r!r} (known: {', '.join(sorted(S.SOURCES))})"))
        elif kind == S.POINTS:
            if v is None:
                r = []
                if t == "poly":
                    issues.append((p, "error", "a poly needs points"))
            elif not isinstance(v, list):
                issues.append((p, "error", "expected a list"))
                r = []
            else:
                r = []
                for j, pt in enumerate(v):
                    if not isinstance(pt, list):
                        issues.append((f"{p}[{j}]", "error", "expected a list"))
                        continue
                    if t == "gradient":                             # [position, colour, alpha?]
                        pos = _num(pt[0], f"{p}[{j}][0]", issues) if pt else 0.0
                        col = palette.compile(pt[1], f"{p}[{j}][1]") if len(pt) > 1 else (0.0, 0.0, 0.0, 1.0)
                        al = _num(pt[2], f"{p}[{j}][2]", issues, default=1.0) if len(pt) > 2 else 1.0
                        r.append((pos, col, al))
                    else:
                        r.append(tuple(_num(c, f"{p}[{j}][{n}]", issues) for n, c in enumerate(pt[:2])))
        elif kind == S.LIST:
            kids_raw = raw.get(k) or []
            if not isinstance(kids_raw, list):
                issues.append((p, "error", "expected a list of elements"))
                kids_raw = []
            for j, kr in enumerate(kids_raw):
                kn = _compile_node(kr, f"{p}[{j}]", palette, issues, depth + 1)
                if kn is not None:
                    node.kids.append(kn)
            continue
        else:
            continue
        node.props[k] = r
    if t == "repeat" and not raw.get("source") and raw.get("count") is None:
        issues.append((path, "error", "a repeat needs a 'source' (a data list) or a 'count'"))
    return node


def compile_spec(raw, path=""):
    sp = Spec()
    sp.raw, sp.path = raw, path
    iss = sp.issues
    if not isinstance(raw, dict):
        iss.append(("(file)", "error", "the spec must be a JSON object"))
        return sp
    for k in raw:
        if k not in S.TOP_LEVEL:
            iss.append((k, "warning", "unknown top-level key (ignored)"))
    ver = raw.get("version", 1)
    if ver != 1:
        iss.append(("version", "error", f"this PRAXIS reads HUD spec version 1, the file says {ver!r}"))
    sp.name = str(raw.get("name", "unnamed"))
    sp.palette = Palette(raw.get("palette"), iss)
    for need in ("void", "text", "muted", "dim", "accent", "ok", "warn", "bad"):
        if need not in sp.palette.names():
            iss.append((f"palette.{need}", "error", "the palette must define this colour"))
    sp.fonts = dict(raw.get("fonts") or {})
    # vars: evaluated in order every frame, so later ones can use earlier ones (layout lives here)
    for name, src in (raw.get("vars") or {}).items():
        try:
            sp.vars.append((name, compile_expr(src if isinstance(src, str) else repr(float(src)))))
        except (ExprError, TypeError, ValueError) as e:
            iss.append((f"vars.{name}", "error", f"{e}  in  {src!r}"))
    # modes: how the state moves the machine. Every mode must name every number so states glide between each other.
    modes = raw.get("modes") or {}
    for m in S.REQUIRED_MODES:
        if m not in modes:
            iss.append((f"modes.{m}", "error", "every state needs an entry"))
            continue
        for k in S.MODE_KEYS_REQUIRED:
            if not isinstance(modes[m].get(k), (int, float)) or isinstance(modes[m].get(k), bool):
                iss.append((f"modes.{m}.{k}", "error", "required number"))
    sp.modes = {m: dict(v) for m, v in modes.items() if isinstance(v, dict)}
    sp.states = dict(raw.get("states") or {})
    for st in S.STATES:
        if st not in sp.states:
            iss.append((f"states.{st}", "warning", "no colour for this step state (it will show as 'dim')"))
    sp.glyphs = dict(raw.get("glyphs") or {})
    sp.persona_rate = float((raw.get("persona") or {}).get("rate", 1.4))
    sp.boot = dict(raw.get("boot") or {})
    gl = raw.get("glow") or {}
    sp.glow_box = {k: (_num(gl[k], f"glow.{k}", iss) if k in gl else None) for k in ("x", "y", "w", "h")} if gl.get("box", True) and "x" in gl else None
    sp.min_size = tuple(raw.get("min_size") or (560, 300))
    sp.stats_order = list(raw.get("stats_order") or ["elapsed", "steps", "checks", "brain", "cost"])
    layers = raw.get("layers")
    if not isinstance(layers, list) or not layers:
        iss.append(("layers", "error", "the spec needs a non-empty 'layers' list"))
    else:
        for i, lr in enumerate(layers):
            n = _compile_node(lr, f"layers[{i}]", sp.palette, iss)
            if n is not None:
                sp.layers.append(n)
    return sp


def load(path):
    """-> Spec. A missing, unreadable or malformed file yields a Spec with errors (never an exception)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        sp = compile_spec(raw, path)
        sp.mtime = os.path.getmtime(path)
        return sp
    except FileNotFoundError:
        sp = Spec(); sp.path = path
        sp.issues.append((path, "error", "file not found"))
        return sp
    except (OSError, UnicodeDecodeError) as e:
        sp = Spec(); sp.path = path
        sp.issues.append((path, "error", f"cannot read: {e}"))
        return sp
    except json.JSONDecodeError as e:
        sp = Spec(); sp.path = path
        sp.issues.append((path, "error", f"not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})"))
        return sp


def user_path():
    from ....paths import home
    return os.environ.get("PRAXIS_HUD") or os.path.join(home(), "hud.json")
