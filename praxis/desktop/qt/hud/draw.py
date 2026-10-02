"""Draws compiled spec elements with QPainter. One function per element type; `render()` is the only entry point.

Conventions: pixels for lengths; DEGREES for angles, 0 = straight up, increasing clockwise (so an arc `start 0 span 90` is the top-right quarter);
opacity multiplies down the tree (a group's opacity fades its children); colours are (r, g, b, a) tuples resolved by the palette."""
import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient)

from .expr import Obj
from .motion import BAR_LEVELS, clamp

DRAW = {}


def element(name):
    def deco(fn):
        DRAW[name] = fn
        return fn
    return deco


def fin(x, lo=-1e6, hi=1e6, default=0.0):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    if x != x or x in (math.inf, -math.inf):
        return default
    return lo if x < lo else hi if x > hi else x


def bucket(a, n=4):
    return int(max(0, min(255, a)) * n / 256.0 + 0.5) * 255 // n


class Frame:
    """Everything a draw function needs for this frame."""

    def __init__(self, p, ctx, spec, motion, sources, fonts, caches):
        self.p, self.ctx, self.spec, self.motion, self.sources, self.fonts, self.caches = p, ctx, spec, motion, sources, fonts, caches
        self.op = 1.0
        self.hits = []                      # (item, QRectF in widget pixels): what the mouse can point at (repeat hit_w / hit_h)
        self.palette = spec.palette
        self._fcache = {}

    # ---- colours / pens --------------------------------------------------------------------------------------------
    def rgba(self, c, a=1.0):
        if c is None:
            return None
        if callable(c):
            c = c(self.ctx)
        return (c[0], c[1], c[2], c[3] * a * self.op)

    def qcolor(self, c, a=1.0):
        t = self.rgba(c, a)
        if t is None or t[3] <= 0.002:
            return None
        return QColor(int(max(0, min(255, t[0]))), int(max(0, min(255, t[1]))), int(max(0, min(255, t[2]))), int(max(0, min(255, t[3] * 255))))

    def pen(self, c, width, a=1.0, dash="", cap="flat"):
        qc = self.qcolor(c, a)
        if qc is None:
            return None
        pen = QPen(qc, max(0.1, fin(width, 0.1, 80, 1.0)))
        pen.setCapStyle(Qt.RoundCap if cap == "round" else Qt.FlatCap)
        if dash:
            try:
                pat = [max(0.2, float(x)) / pen.widthF() for x in dash.split()]
                if len(pat) % 2:
                    pat *= 2
                pen.setDashPattern(pat)
            except ValueError:
                pass
        return pen

    def font(self, family, size, weight, spacing):
        key = (family, round(size, 2), weight, round(spacing, 2))
        f = self._fcache.get(key)
        if f is None:
            fam = self.fonts.get(family, self.fonts["mono"])
            f = QFont(fam)
            f.setPointSizeF(max(4.0, size))
            if weight == "bold":
                f.setWeight(QFont.Bold)
            if spacing:
                f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
            self._fcache[key] = f
        return f


def render(fr, node):
    ctx = fr.ctx
    if node.visible is not None:
        vis = node.visible(ctx) if callable(node.visible) else node.visible
        if not vis:
            return
    op = 1.0
    if node.opacity is not None:
        op = node.opacity(ctx) if callable(node.opacity) else node.opacity
    if node.boot is not None:
        k = node.boot(ctx) if callable(node.boot) else node.boot
        op *= fr.motion.reveal(fin(k, -50, 50))
    op = fin(op, 0.0, 4.0)
    if op <= 0.003:
        return
    saved = fr.op
    fr.op = saved * op
    try:
        DRAW[node.type](fr, node, node.values(ctx))
    finally:
        fr.op = saved


def render_all(fr, nodes):
    for n in nodes:
        render(fr, n)


# ---- structure ---------------------------------------------------------------------------------------------------------
@element("group")
def _group(fr, n, v):
    p = fr.p
    p.save()
    try:
        p.translate(fin(v["x"]), fin(v["y"]))
        if v["rot"]:
            p.rotate(fin(v["rot"], -3600, 3600))
        s = fin(v["scale"], 0.01, 100, 1.0)
        if s != 1.0:
            p.scale(s, s)
        render_all(fr, n.kids)
    finally:
        p.restore()


@element("repeat")
def _repeat(fr, n, v):
    p, ctx = fr.p, fr.ctx
    src = v["source"]
    if src:
        items = list(fr.sources.get(src, ()))
    else:
        cnt = int(fin(v["count"], 0, 2000))
        items = [Obj({"i": i, "n": cnt, "f": i / cnt if cnt else 0.0}) for i in range(cnt)]
    items = items[:int(fin(v["limit"], 0, 2000, 1000))]
    if v["reverse"]:
        items.reverse()
    total = len(items)
    x, y, dx, dy, rot, drot = (fin(v[k]) for k in ("x", "y", "dx", "dy", "rot", "drot"))
    for i, it in enumerate(items):
        c2 = dict(ctx)
        c2["item"], c2["i"], c2["n"] = it, i, total
        fr.ctx = c2
        p.save()
        try:
            p.translate(x + dx * i, y + dy * i)
            if rot or drot:
                p.rotate(rot + drot * i)
            hw, hh = fin(v["hit_w"], 0, 1e5), fin(v["hit_h"], 0, 1e5)
            if hw > 0 and hh > 0:
                o = p.transform().map(QPointF(0, 0))
                fr.hits.append((it, QRectF(o.x(), o.y(), hw, hh)))
            render_all(fr, n.kids)
        finally:
            p.restore()
            fr.ctx = ctx


# ---- shapes ------------------------------------------------------------------------------------------------------------
def _cut_poly(x, y, w, h, cut):
    c = min(cut, w / 2, h / 2)
    if c <= 0.5:
        return QPolygonF([QPointF(x, y), QPointF(x + w, y), QPointF(x + w, y + h), QPointF(x, y + h)])
    return QPolygonF([QPointF(x + c, y), QPointF(x + w, y), QPointF(x + w, y + h - c), QPointF(x + w - c, y + h), QPointF(x, y + h), QPointF(x, y + c)])


@element("rect")
def _rect(fr, n, v):
    p = fr.p
    poly = _cut_poly(fin(v["x"]), fin(v["y"]), fin(v["w"], 0, 1e5), fin(v["h"], 0, 1e5), fin(v["cut"], 0, 500))
    fill = fr.qcolor(v["fill"], fin(v["fill_alpha"], 0, 4, 1.0))
    p.setBrush(QBrush(fill) if fill else Qt.NoBrush)
    pen = fr.pen(v["stroke"], v["width"], dash=v["dash"])
    p.setPen(pen if pen else Qt.NoPen)
    p.drawPolygon(poly)


@element("panel")
def _panel(fr, n, v):
    p = fr.p
    x, y, w, h = fin(v["x"]), fin(v["y"]), fin(v["w"], 0, 1e5), fin(v["h"], 0, 1e5)
    cut = fin(v["cut"], 0, 500)
    poly = _cut_poly(x, y, w, h, cut)
    fill = fr.qcolor(v["fill"], fin(v["fill_alpha"], 0, 4, 1.0))
    p.setBrush(QBrush(fill) if fill else Qt.NoBrush)
    pen = fr.pen(v["stroke"], v["width"])
    p.setPen(pen if pen else Qt.NoPen)
    p.drawPolygon(poly)
    stroke = v["stroke"]
    if v["ticks"] and pen:                                          # heavier corner brackets over the thin border: the tactical look
        hp = fr.pen(stroke, fin(v["width"], 0.1, 20, 1.2) * 2.0, 1.0)
        p.setPen(hp)
        L = min(26.0, w * 0.2, h * 0.2)
        c = min(cut, w / 2, h / 2)
        p.drawPolyline(QPolygonF([QPointF(x + c + L, y), QPointF(x + c, y), QPointF(x, y + c), QPointF(x, y + c + L)]))
        p.drawPolyline(QPolygonF([QPointF(x + w - L, y + h), QPointF(x + w - c, y + h), QPointF(x + w, y + h - c), QPointF(x + w, y + h - c - L)]))
    title = v["title"]
    if title:
        f = fr.font("mono", fin(v["size"], 4, 40, 8), "bold", 2.0)
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(title) + 14
        tx = x + max(cut, 8) + 12
        bg = fr.qcolor(fr.palette.lookup("void", fr.ctx), 1.0)
        if bg is not None:
            p.setPen(Qt.NoPen); bg.setAlpha(min(255, int(255 * min(1.0, fr.op * 1.5)))); p.setBrush(bg)
            p.drawRect(QRectF(tx - 6, y - 7, tw + 4, 14))
        p.setFont(f)
        col = fr.qcolor(v["title_color"] or v["stroke"])
        if col is not None:
            p.setPen(col)
            p.drawText(QRectF(tx, y - 8, tw + 20, 16), Qt.AlignVCenter | Qt.AlignLeft, title)


@element("line")
def _line(fr, n, v):
    pen = fr.pen(v["color"], v["width"], dash=v["dash"], cap=v["cap"])
    if pen:
        fr.p.setPen(pen)
        fr.p.drawLine(QLineF(fin(v["x1"]), fin(v["y1"]), fin(v["x2"]), fin(v["y2"])))


@element("poly")
def _poly(fr, n, v):
    pts = []
    for pt in n.props["points"]:
        xs = [(c(fr.ctx) if callable(c) else c) for c in pt]
        pts.append(QPointF(fin(xs[0]), fin(xs[1] if len(xs) > 1 else 0)))
    p = fr.p
    fill = fr.qcolor(v["fill"], fin(v["fill_alpha"], 0, 4, 1.0))
    pen = fr.pen(v["stroke"], v["width"])
    p.setBrush(QBrush(fill) if fill else Qt.NoBrush)
    p.setPen(pen if pen else Qt.NoPen)
    if v["close"] or fill:
        p.drawPolygon(QPolygonF(pts))
    else:
        p.drawPolyline(QPolygonF(pts))


@element("circle")
def _circle(fr, n, v):
    p = fr.p
    r = fin(v["r"], 0, 1e5)
    fill = fr.qcolor(v["fill"], fin(v["fill_alpha"], 0, 4, 1.0))
    pen = fr.pen(v["stroke"], v["width"], dash=v["dash"])
    p.setBrush(QBrush(fill) if fill else Qt.NoBrush)
    p.setPen(pen if pen else Qt.NoPen)
    p.drawEllipse(QPointF(fin(v["x"]), fin(v["y"])), r, r)


def _qt_arc(start, span):
    return int((90.0 - start) * 16), int(-span * 16)


@element("arc")
def _arc(fr, n, v):
    pen = fr.pen(v["color"], v["width"], dash=v["dash"], cap=v["cap"])
    if not pen:
        return
    r, x, y = fin(v["r"], 0, 1e5), fin(v["x"]), fin(v["y"])
    fr.p.setPen(pen); fr.p.setBrush(Qt.NoBrush)
    s, sp = _qt_arc(fin(v["start"], -3600, 3600), fin(v["span"], -360, 360))
    if abs(sp) >= 360 * 16:
        fr.p.drawEllipse(QPointF(x, y), r, r)
    else:
        fr.p.drawArc(QRectF(x - r, y - r, 2 * r, 2 * r), s, sp)


@element("ellipse")
def _ellipse(fr, n, v):
    pen = fr.pen(v["color"], v["width"], dash=v["dash"], cap=v["cap"])
    if not pen:
        return
    p = fr.p
    rx, ry = fin(v["rx"], 0, 1e5), fin(v["ry"], 0, 1e5)
    p.save()
    try:
        p.translate(fin(v["x"]), fin(v["y"]))
        p.rotate(fin(v["rot"], -3600, 3600))
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        sp = fin(v["span"], -360, 360, 360)
        if abs(sp) >= 360:
            p.drawEllipse(QPointF(0, 0), rx, ry)
        else:
            s, span = _qt_arc(fin(v["start"], -3600, 3600), sp)
            p.drawArc(QRectF(-rx, -ry, 2 * rx, 2 * ry), s, span)
    finally:
        p.restore()


@element("ticks")
def _ticks(fr, n, v):
    p = fr.p
    cnt = max(2, int(fin(v["count"], 2, 720, 72)))
    major = max(1, int(fin(v["major"], 1, 720, 6)))
    r0, r1, ml = fin(v["r0"], 0, 1e5), fin(v["r1"], 0, 1e5), fin(v["major_len"], 0, 200)
    x, y, rot = fin(v["x"]), fin(v["y"]), fin(v["rot"], -3600, 3600)
    minor, mj = [], []
    for i in range(cnt):
        a = math.radians(rot + i * 360.0 / cnt - 90.0)
        ca, sa = math.cos(a), math.sin(a)
        if i % major == 0:
            mj.append(QLineF(x + ca * (r0 - ml), y + sa * (r0 - ml), x + ca * r1, y + sa * r1))
        else:
            minor.append(QLineF(x + ca * r0, y + sa * r0, x + ca * r1, y + sa * r1))
    pen = fr.pen(v["color"], v["width"])
    if pen and minor:
        p.setPen(pen); p.drawLines(minor)
    pen = fr.pen(v["major_color"] or v["color"], v["major_width"])
    if pen and mj:
        p.setPen(pen); p.drawLines(mj)
    lab = int(fin(v["labels"], 0, 360))
    if lab > 0:
        col = fr.qcolor(v["label_color"] or v["color"])
        if col is not None:
            p.setFont(fr.font("mono", fin(v["size"], 4, 30, 7), "normal", 1.0)); p.setPen(col)
            lr = fin(v["label_r"], 0, 1e5)
            for k in range(lab):
                deg = k * 360.0 / lab
                a = math.radians(rot + deg - 90.0)
                p.drawText(QRectF(x + math.cos(a) * lr - 18, y + math.sin(a) * lr - 7, 36, 14), Qt.AlignCenter, f"{int(deg):03d}")


@element("sphere")
def _sphere(fr, n, v):
    r = fin(v["r"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    nlat, nlon = int(fin(v["lat"], 0, 24, 5)), int(fin(v["lon"], 1, 48, 8))
    rot, e = math.radians(fin(v["rot"], -3600, 3600)), math.radians(fin(v["tilt"], -89, 89, 20))
    ce, se = math.cos(e), math.sin(e)
    front, back = QPainterPath(), QPainterPath()

    def proj(phi, lam):
        X, Y, Z = math.cos(phi) * math.sin(lam), math.sin(phi), math.cos(phi) * math.cos(lam)
        Y2 = Y * ce - Z * se
        Z2 = Y * se + Z * ce
        return x + X * r, y - Y2 * r, Z2

    def trace(points):
        prev = None
        for px, py, z in points:
            side = front if z > 0 else back
            if prev is not None and (prev[2] > 0) == (z > 0):
                side.lineTo(px, py)
            else:
                side.moveTo(px, py)
            prev = (px, py, z)

    steps = (26, 22, 16, 12)[int(fr.ctx.get("quality", 0) or 0)]
    for i in range(1, nlat + 1):                                                    # latitudes
        phi = math.radians(-90 + 180.0 * i / (nlat + 1))
        trace([proj(phi, rot + 2 * math.pi * k / steps) for k in range(steps + 1)])
    for j in range(nlon):                                                           # meridians
        lam = rot + math.pi * j / nlon
        trace([proj(math.radians(-90 + 360.0 * k / steps), lam) for k in range(steps + 1)])
    trace([proj(0.0, rot + 2 * math.pi * k / steps) for k in range(steps + 1)])      # the equator, again, so it reads as the brightest line
    p = fr.p
    p.setBrush(Qt.NoBrush)
    pen = fr.pen(v["color"], v["width"], fin(v["back"], 0, 1, 0.35))
    if pen:
        p.setPen(pen); p.drawPath(back)
    pen = fr.pen(v["color"], v["width"] * 1.15, 1.0)
    if pen:
        p.setPen(pen); p.drawPath(front)
    pen = fr.pen(v["color"], v["width"], 0.8)                                         # the limb
    if pen:
        p.setPen(pen); p.drawEllipse(QPointF(x, y), r, r)


@element("bars")
def _bars(fr, n, v):
    hist = [it["v"] for it in fr.sources.get(v["source"] or "voice", ())]
    cnt = int(fin(v["count"], 4, 256, 96))
    cnt = min(cnt, BAR_LEVELS[int(fr.ctx.get("quality", 0))] if fr.ctx.get("quality", 0) is not None else cnt)
    if not hist:
        hist = [0.0]
    pen = fr.pen(v["color"], v["width"], cap="round")
    if not pen:
        return
    floor = fin(v["floor"], 0, 1, 0.04)
    lines = []
    x, y = fin(v["x"]), fin(v["y"])
    for k in range(cnt):
        pos = (k / cnt) * (len(hist) - 1)
        i0 = int(pos); i1 = min(len(hist) - 1, i0 + 1)
        val = hist[i0] + (hist[i1] - hist[i0]) * (pos - i0)
        val = floor + (1 - floor) * clamp(val * (0.65 + 0.35 * math.sin(k * 1.7 + fr.ctx.get("t", 0) * 9)) if val > 0.02 else 0.0)
        if v["radial"]:
            a = math.radians(fin(v["rot"]) + k * 360.0 / cnt - 90.0)
            r0, r1 = fin(v["r0"]), fin(v["r0"]) + (fin(v["r1"]) - fin(v["r0"])) * val
            lines.append(QLineF(x + math.cos(a) * r0, y + math.sin(a) * r0, x + math.cos(a) * r1, y + math.sin(a) * r1))
        else:
            w, h = fin(v["w"]), fin(v["h"])
            px = x + w * (k + 0.5) / cnt
            lines.append(QLineF(px, y - h * val / 2, px, y + h * val / 2))
    fr.p.setPen(pen)
    fr.p.drawLines(lines)


@element("text")
def _text(fr, n, v):
    p = fr.p
    text = str(v["text"])
    if not text:
        return
    if v["upper"]:
        text = text.upper()
    f = fr.font(v["family"], fin(v["size"], 4, 80, 9), v["weight"], fin(v["spacing"], 0, 40))
    p.setFont(f)
    x, y, w, h = fin(v["x"]), fin(v["y"]), fin(v["w"], 1, 1e5, 200), fin(v["h"], 1, 1e5, 16)
    al = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[v["align"]]
    flags = al | Qt.AlignVCenter
    if v["wrap"]:
        flags = al | Qt.AlignTop | Qt.TextWordWrap
    elif v["elide"]:
        text = QFontMetricsF(f).elidedText(text, Qt.ElideRight, w)
    rect = QRectF(x, y, w, h)
    glow = fin(v["glow"], 0, 1)
    if glow > 0:
        gc = fr.qcolor(v["color"], 0.16 * glow)
        if gc is not None:
            p.setPen(gc)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(rect.translated(dx, dy), flags, text)
    col = fr.qcolor(v["color"])
    if col is not None:
        p.setPen(col)
        p.drawText(rect, flags, text)


@element("gradient")
def _gradient(fr, n, v):
    stops = v["stops"] or []
    if not stops:
        return
    x, y, w, h = fin(v["x"]), fin(v["y"]), fin(v["w"], 1, 1e5), fin(v["h"], 1, 1e5)
    if v["kind"] == "radial":
        g = QRadialGradient(QPointF(fin(v["cx"], -1e5, 1e5, x + w / 2), fin(v["cy"], -1e5, 1e5, y + h / 2)), fin(v["r"], 1, 1e5, 100))
    else:
        ang = math.radians(fin(v["angle"], -3600, 3600, 90))
        ux, uy = math.cos(ang), math.sin(ang)                                      # direction the gradient runs (screen coords, y down)
        L = abs(ux) * w + abs(uy) * h
        mx, my = x + w / 2, y + h / 2
        g = QLinearGradient(QPointF(mx - ux * L / 2, my - uy * L / 2), QPointF(mx + ux * L / 2, my + uy * L / 2))
    for pos, col, al in stops:
        pos = pos(fr.ctx) if callable(pos) else pos
        al = al(fr.ctx) if callable(al) else al
        qc = fr.qcolor(col, fin(al, 0, 4, 1.0))
        g.setColorAt(clamp(fin(pos, 0, 1)), qc if qc is not None else QColor(0, 0, 0, 0))
    fr.p.setPen(Qt.NoPen); fr.p.setBrush(QBrush(g))
    fr.p.drawRect(QRectF(x, y, w, h))


# ---- grids -------------------------------------------------------------------------------------------------------------
def _hex_cells(w, h, s):
    dx, dy = s * 1.5, s * math.sqrt(3) / 2
    out = []
    for ci in range(int(w / dx) + 2):
        for ri in range(int(h / (2 * dy)) + 2):
            out.append((ci * dx, ri * dy * 2 + (dy if ci % 2 else 0)))
    return out


def _hex_path(cells, s):
    path = QPainterPath()
    for cx, cy in cells:
        for k in range(6):
            a0, a1 = math.radians(60 * k), math.radians(60 * (k + 1))
            if k in (0, 1, 2):                                       # three edges per cell: shared edges are not drawn twice
                path.moveTo(cx + math.cos(a0) * s, cy + math.sin(a0) * s)
                path.lineTo(cx + math.cos(a1) * s, cy + math.sin(a1) * s)
    return path


@element("hexgrid")
def _hexgrid(fr, n, v):
    s = fin(v["size"], 8, 200, 34)
    w, h = fin(v["w"], 1, 1e5), fin(v["h"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    key = ("hex", int(w), int(h), round(s, 1))
    ent = fr.caches.get(key)
    if ent is None:
        cells = _hex_cells(w, h, s)
        ent = fr.caches[key] = (cells, _hex_path(cells, s))
    cells, path = ent
    p = fr.p
    p.save()
    p.translate(x, y)
    try:
        if v["lines"]:
            pen = fr.pen(v["color"], v["width"])
            if pen:
                p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(path)
        if v["waves"]:
            motion = fr.motion
            wc = v["wave_color"] or v["color"]
            cx0, cy0 = fin(v["cx"], -1e5, 1e5, w / 2) - x, fin(v["cy"], -1e5, 1e5, h / 2) - y
            sp = fin(v["wave_speed"], 0.1, 10, 1.0)
            hexp = QPolygonF([QPointF(math.cos(math.radians(60 * k)) * s * 0.80, math.sin(math.radians(60 * k)) * s * 0.80) for k in range(6)])
            for t0 in motion.waves:
                u = (motion.t - t0) / 2.4 * sp
                if not 0 <= u <= 1:
                    continue
                radius = 40 + (max(w, h) * 0.9) * (1 - (1 - u) ** 2)
                strength = (1 - u) ** 1.4
                for cxh, cyh in cells:
                    d = abs(math.hypot(cxh - cx0, cyh - cy0) - radius)
                    if d < 60:
                        qc = fr.qcolor(wc, strength * (1 - d / 60) * 0.22)
                        if qc is not None:
                            p.setBrush(qc); p.setPen(Qt.NoPen)
                            p.save(); p.translate(cxh, cyh); p.drawPolygon(hexp); p.restore()
    finally:
        p.restore()


@element("dotgrid")
def _dotgrid(fr, n, v):
    sp = fin(v["spacing"], 6, 200, 26)
    w, h = fin(v["w"], 1, 1e5), fin(v["h"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    cx0, cy0 = fin(v["cx"], -1e5, 1e5, x + w / 2), fin(v["cy"], -1e5, 1e5, y + h / 2)
    fade = fin(v["fade"], 0, 1e5)
    rows, cols = int(h / sp) + 1, int(w / sp) + 1
    levels = {}
    for ri in range(rows):
        py = y + ri * sp
        for ci in range(cols):
            px = x + ci * sp
            a = 1.0
            if fade > 0:
                a = clamp(1.2 - math.hypot(px - cx0, py - cy0) / fade)
                if a <= 0.02:
                    continue
            levels.setdefault(int(a * 4 + 0.5), []).append(QPointF(px, py))
    for lv, pts in levels.items():
        if lv <= 0:
            continue
        pen = fr.pen(v["color"], max(0.6, fin(v["r"], 0.2, 20, 1.0) * 2), lv / 4.0, cap="round")
        if pen:
            fr.p.setPen(pen); fr.p.drawPoints(QPolygonF(pts))


@element("scan")
def _scan(fr, n, v):
    x, y, w, h = fin(v["x"]), fin(v["y"]), fin(v["w"], 1, 1e5), fin(v["h"], 1, 1e5)
    band = fin(v["band"], 0, 1e4, 60)
    t = fr.ctx.get("t", 0.0)
    pos = y - band + ((t * fin(v["speed"], 0, 10, 0.2)) % 1.0) * (h + band)
    qc = fr.qcolor(v["color"], 0.5) if band >= 2 else None
    if qc is not None:
        g = QLinearGradient(QPointF(0, pos), QPointF(0, pos + band))
        c0 = QColor(qc); c0.setAlpha(0)
        c1 = QColor(qc)
        g.setColorAt(0.0, c0); g.setColorAt(0.85, c1); g.setColorAt(1.0, c0)
        fr.p.setPen(Qt.NoPen); fr.p.setBrush(QBrush(g))
        fr.p.drawRect(QRectF(x, max(y, pos), w, min(band, y + h - max(y, pos))))
    ln = int(fin(v["lines"], 0, 400))
    if ln > 0:
        qc = fr.qcolor(v["color"], 0.12)                            # a one-line tile repeated down the screen: a pattern fill, not 190 strokes
        if qc is not None:
            gap = max(2, ln)
            key = ("scantile", gap, qc.red() // 16, qc.green() // 16, qc.blue() // 16)
            tile = fr.caches.get(key)
            if tile is None:
                tile = QPixmap(1, gap)
                tile.fill(Qt.transparent)
                tp = QPainter(tile); tp.setPen(QColor(qc.red(), qc.green(), qc.blue(), 255)); tp.drawPoint(0, 0); tp.end()
                fr.caches[key] = tile
            fr.p.setOpacity(fr.p.opacity() * qc.alphaF())
            fr.p.drawTiledPixmap(QRectF(x, y, w, h).toRect(), tile)
            fr.p.setOpacity(fr.p.opacity() / max(qc.alphaF(), 1e-6))


# ---- objects ----------------------------------------------------------------------------------------------------------
@element("core")
def _core(fr, n, v):
    r = fin(v["r"], 1, 1e5)
    lvl = fin(v["level"], 0, 4, 1.0)
    x, y = fin(v["x"]), fin(v["y"])
    col, hot = v["color"], v["hot"] or v["color"]
    for scale, a in ((2.6, 0.10), (1.7, 0.22), (1.0, 0.5)):
        g = QRadialGradient(QPointF(x, y), r * scale * (0.7 + 0.3 * lvl))
        c0 = fr.qcolor(col, min(1.0, a * lvl))
        c1 = fr.qcolor(col, 0.0) if c0 is not None else None
        if c0 is None:
            continue
        c1 = QColor(c0); c1.setAlpha(0)
        g.setColorAt(0.0, c0); g.setColorAt(1.0, c1)
        fr.p.setPen(Qt.NoPen); fr.p.setBrush(QBrush(g))
        fr.p.drawEllipse(QPointF(x, y), r * scale * (0.7 + 0.3 * lvl), r * scale * (0.7 + 0.3 * lvl))
    g = QRadialGradient(QPointF(x, y), r * 0.55)
    h0 = fr.qcolor(hot, min(1.0, 0.95 * lvl))
    if h0 is not None:
        h1 = QColor(h0); h1.setAlpha(0)
        g.setColorAt(0.0, QColor(255, 255, 255, h0.alpha())); g.setColorAt(0.35, h0); g.setColorAt(1.0, h1)
        fr.p.setBrush(QBrush(g))
        fr.p.drawEllipse(QPointF(x, y), r * 0.55, r * 0.55)


@element("hex")
def _hexel(fr, n, v):
    p = fr.p
    r = fin(v["r"], 1, 1e5)
    sides = max(3, int(fin(v["sides"], 3, 12, 6)))
    x, y, rot = fin(v["x"]), fin(v["y"]), math.radians(fin(v["rot"], -3600, 3600))
    poly = QPolygonF([QPointF(x + math.cos(rot + k * math.tau / sides - math.pi / 2) * r, y + math.sin(rot + k * math.tau / sides - math.pi / 2) * r)
                      for k in range(sides)])
    fill = fr.qcolor(v["fill"], fin(v["fill_alpha"], 0, 4, 1.0))
    pen = fr.pen(v["stroke"], v["width"])
    p.setBrush(QBrush(fill) if fill else Qt.NoBrush)
    p.setPen(pen if pen else Qt.NoPen)
    p.drawPolygon(poly)
    if v["gauge"] is not None:
        gv = clamp(fin(v["gauge"], 0, 1))
        gp = fr.pen(v["gauge_color"] or v["stroke"], 2.4, cap="round")
        if gp and gv > 0.004:
            p.setPen(gp); p.setBrush(Qt.NoBrush)
            gr = r + 5
            p.drawArc(QRectF(x - gr, y - gr, 2 * gr, 2 * gr), 90 * 16, int(-360 * gv * 16))


@element("bar")
def _bar(fr, n, v):
    p = fr.p
    x, y, w, h = fin(v["x"]), fin(v["y"]), fin(v["w"], 0, 1e5), fin(v["h"], 0, 1e5)
    val = clamp(fin(v["value"], 0, 1))
    seg = int(fin(v["segments"], 0, 100))
    back = fr.qcolor(v["back"])
    fill = fr.qcolor(v["color"])
    p.setPen(Qt.NoPen)
    if seg <= 1:
        if back is not None:
            p.setBrush(back); p.drawRect(QRectF(x, y, w, h))
        if fill is not None and val > 0:
            p.setBrush(fill); p.drawRect(QRectF(x, y, w * val, h))
    else:
        gap = 2.0
        sw = (w - gap * (seg - 1)) / seg
        for k in range(seg):
            on = (k + 0.5) / seg <= val
            c = fill if on else back
            if c is not None:
                p.setBrush(c); p.drawRect(QRectF(x + k * (sw + gap), y, sw, h))


@element("courier")
def _courier(fr, n, v):
    if not v["active"]:
        return
    x1, y1, x2, y2 = (fin(v[k]) for k in ("x1", "y1", "x2", "y2"))
    dist = math.hypot(x2 - x1, y2 - y1) or 1.0
    bend = fin(v["bend"], -2, 2, 0.2)
    mx, my = (x1 + x2) / 2 - (y2 - y1) * bend, (y1 + y2) / 2 + (x2 - x1) * bend
    p = fr.p
    pen = fr.pen(v["color"], 1.2, fin(v["line"], 0, 1, 0.25))
    if pen:
        path = QPainterPath(QPointF(x1, y1)); path.quadTo(QPointF(mx, my), QPointF(x2, y2))
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(path)
    cnt = int(fin(v["count"], 1, 200, 36))
    t = fr.ctx.get("t", 0.0) * fin(v["speed"], 0.05, 5, 0.85)
    groups = {}
    for i in range(cnt):                                                    # sparks batched by (brightness, size): a few pens instead of one ellipse each
        u = (t + i / cnt) % 1.0
        a_ = (1 - u) ** 2; b_ = 2 * (1 - u) * u; c_ = u * u
        px, py = a_ * x1 + b_ * mx + c_ * x2, a_ * y1 + b_ * my + c_ * y2
        groups.setdefault((int(3 * math.sin(math.pi * u) ** 0.6 + 0.5), 2.2 + 3.2 * (1.0 - abs(2 * u - 1.0)) // 1.2 * 1.2), []).append(QPointF(px, py))
    for (lv, sz), pts in groups.items():
        if lv <= 0:
            continue
        pen = fr.pen(v["color"], sz, lv / 3.0, cap="round")
        if pen:
            p.setPen(pen); p.drawPoints(QPolygonF(pts))


# ---- effects driven by the real events --------------------------------------------------------------------------------------
@element("embers")
def _embers(fr, n, v):
    m, r = fr.motion, fin(v["r"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    buckets = {}
    bright = m.v["bright"]
    for ex, ey, vx, vy, life, age in m.embers:
        f = math.sin(math.pi * min(1.0, age / life)) ** 0.8
        a = bucket(215 * f * bright, 4)
        if a > 0:
            buckets.setdefault((a, 2.0 if f < 0.55 else 3.0), []).append(QPointF(x + ex * r, y + ey * r))
    sz = fin(v["size"], 0.2, 8, 1.0)
    for (a, wd), pts in buckets.items():
        pen = fr.pen(v["color"], wd * sz, a / 255.0, cap="round")
        if pen:
            fr.p.setPen(pen); fr.p.drawPoints(QPolygonF(pts))


@element("bolts")
def _bolts(fr, n, v):
    m, r = fr.motion, fin(v["r"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    r0, r1 = fin(v["r0"], 0, 4, 0.2), fin(v["r1"], 0, 4, 1.0)
    for b in m.bolts:
        a = clamp(1.0 - b["age"] / b["life"])
        ca, sa = math.cos(b["a"]), math.sin(b["a"])
        pts = []
        for u, off in b["pts"]:
            rad = (r0 + (r1 - r0) * u) * r
            o = off * r
            pts.append(QPointF(x + ca * rad - sa * o, y + sa * rad + ca * o))
        poly = QPolygonF(pts)
        pen = fr.pen(v["color"], fin(v["width"], 0.2, 20, 1.6) * 2.2, 0.45 * a)
        if pen:
            fr.p.setPen(pen); fr.p.setBrush(Qt.NoBrush); fr.p.drawPolyline(poly)
        pen = fr.pen((255, 255, 255, 1.0), fin(v["width"], 0.2, 20, 1.6) * 0.7, 0.9 * a)
        if pen:
            fr.p.setPen(pen); fr.p.drawPolyline(poly)


@element("streaks")
def _streaks(fr, n, v):
    m, r = fr.motion, fin(v["r"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    lv = {}
    for ang, rad, sp in m.flow:
        a = bucket(200 * math.sin(math.pi * clamp(rad)) ** 0.7, 3)
        if a <= 0:
            continue
        pts = [QPointF(x + math.cos(ang - k * 0.05) * rad * r, y + math.sin(ang - k * 0.05) * rad * r) for k in range(4)]
        lv.setdefault(a, []).append(pts)
    for a, items in lv.items():
        pen = fr.pen(v["color"], fin(v["width"], 0.2, 12, 1.6), a / 255.0, cap="round")
        if pen:
            fr.p.setPen(pen); fr.p.setBrush(Qt.NoBrush)
            for pts in items:
                fr.p.drawPolyline(QPolygonF(pts))


@element("ripples")
def _ripples(fr, n, v):
    m, r = fr.motion, fin(v["r"], 1, 1e5)
    x, y = fin(v["x"]), fin(v["y"])
    fr.p.setBrush(Qt.NoBrush)
    for t0, key in m.ripples:
        u = (m.t - t0) / 1.6
        if not 0 <= u <= 1:
            continue
        col = fr.palette.lookup(key, fr.ctx)
        pen = fr.pen(col, fin(v["width"], 0.2, 12, 2.2) * (1 - u) + 0.6, 0.75 * (1 - u) ** 1.6)
        if pen:
            rr = r * (1.0 + 1.0 * (1 - (1 - u) ** 2))
            fr.p.setPen(pen); fr.p.drawEllipse(QPointF(x, y), rr, rr)


@element("shock")
def _shock(fr, n, v):
    sh = fr.motion.shock
    if sh is None:
        return
    r = fin(v["r"], 1, 1e5)
    u = 1.0 - (1.0 - clamp(sh)) ** 3
    pen = fr.pen(v["color"], fin(v["width"], 0.5, 20, 4) * (1 - sh) + 1.0, 0.9 * (1 - sh) ** 1.4)
    if pen:
        fr.p.setPen(pen); fr.p.setBrush(Qt.NoBrush)
        rr = r * (0.9 + 1.25 * u)
        fr.p.drawEllipse(QPointF(fin(v["x"]), fin(v["y"])), rr, rr)


@element("sweep")
def _sweep(fr, n, v):
    """A radar wedge. The wedge is painted once into a pixmap and only rotated each frame (a conical gradient per frame was the dearest thing on screen)."""
    m = fr.motion
    r = int(fin(v["r"], 4, 4000, 100))
    x, y = fin(v["x"]), fin(v["y"])
    span = fin(v["span"], 2, 180, 40)
    r0 = int(fin(v["r0"], 0, 4000))
    qc = fr.qcolor(v["color"], 1.0)
    if qc is None:
        return
    key = ("sweep", r, r0, int(span), qc.red() // 8, qc.green() // 8, qc.blue() // 8)
    pm = fr.caches.get(key)
    if pm is None:
        side = 2 * r + 2
        pm = QPixmap(side, side)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        g = QConicalGradient(QPointF(r + 1, r + 1), 90.0)               # the leading edge points up; it fades behind (anticlockwise)
        c0 = QColor(qc.red(), qc.green(), qc.blue(), 0)
        g.setColorAt(0.0, QColor(qc.red(), qc.green(), qc.blue(), 255)); g.setColorAt(span / 360.0, c0); g.setColorAt(1.0, c0)
        path = QPainterPath(); path.addEllipse(QPointF(r + 1, r + 1), r, r)
        if r0 > 0:
            hole = QPainterPath(); hole.addEllipse(QPointF(r + 1, r + 1), r0, r0)
            path = path.subtracted(hole)
        q.setPen(Qt.NoPen); q.setBrush(QBrush(g)); q.drawPath(path)
        q.end()
        fr.caches[key] = pm
    p = fr.p
    p.save()
    try:
        p.translate(x, y)
        p.rotate(m.sweep)
        p.setOpacity(p.opacity() * min(1.0, fr.op * 0.13 * min(1.0, m.v["sweep"] + 0.25) * 1.0))
        p.drawPixmap(-r - 1, -r - 1, pm)
    finally:
        p.restore()
