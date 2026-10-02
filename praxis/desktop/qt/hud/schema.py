"""What a HUD spec may contain. One table drives validation, compilation and the documentation (`praxis hud docs`).

Prop kinds:  num (a number or an expression string)   bool (true/false or an expression)   text (a template: "{title}  {stats.cost}")
             color (see colors.py)   enum (one of a list)   str (a plain string)   points ([[x,y],...] each a number or expression)
             list (child elements)   source (a named data list)   ints are nums that are rounded."""

NUM, BOOL, TEXT, COLOR, STR, POINTS, LIST, SOURCE = "num", "bool", "text", "color", "str", "points", "list", "source"

COMMON = {
    "id": (STR, ""),
    "visible": (BOOL, True),
    "opacity": (NUM, 1.0),
    "boot": (NUM, None),          # index in the start-up sequence: the element fades in when the HUD draws itself (None = always there)
}

SOURCES = {
    "nodes": "your AIs: item.family item.name item.cost_class item.pressure item.blocked item.cooling_s item.models item.active item.sub item.color item.x item.y item.side",
    "steps": "the plan's real steps: item.label item.state item.glyph item.color item.i",
    "checks": "the goal's real checks: item.ok item.glyph item.color item.i",
    "log": "the latest real events: item.time item.text item.level item.color item.i (newest last)",
    "stats": "the goal readout: item.key item.value",
    "legend": "PLAN / ACT / VERIFY: item.name item.text item.color",
    "ring_plan": "segments of the PLAN ring: item.start item.span item.state item.color item.alpha item.width item.i item.n",
    "ring_act": "segments of the ACT ring (one per real step)",
    "ring_verify": "segments of the VERIFY ring (one per real check)",
    "voice": "the last moments of the real audio level, 0..1, oldest first: item.v item.i item.n",
}

ELEMENTS = {
    "group": dict(x=(NUM, 0), y=(NUM, 0), rot=(NUM, 0), scale=(NUM, 1), children=(LIST, None)),
    "repeat": dict(source=(SOURCE, ""), count=(NUM, None), x=(NUM, 0), y=(NUM, 0), dx=(NUM, 0), dy=(NUM, 0), rot=(NUM, 0), drot=(NUM, 0),
                   limit=(NUM, 1000), reverse=(BOOL, False), hit_w=(NUM, 0), hit_h=(NUM, 0), item=(LIST, None)),
    "rect": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 100), cut=(NUM, 0), fill=(COLOR, None), stroke=(COLOR, None), width=(NUM, 1),
                 dash=(STR, ""), fill_alpha=(NUM, 1)),
    "panel": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 100), cut=(NUM, 14), fill=(COLOR, None), stroke=(COLOR, None), width=(NUM, 1.2),
                  title=(TEXT, ""), title_color=(COLOR, None), size=(NUM, 8), ticks=(BOOL, True), fill_alpha=(NUM, 1)),
    "line": dict(x1=(NUM, 0), y1=(NUM, 0), x2=(NUM, 0), y2=(NUM, 0), color=(COLOR, None), width=(NUM, 1), dash=(STR, ""), cap=(STR, "flat")),
    "poly": dict(points=(POINTS, None), close=(BOOL, False), fill=(COLOR, None), stroke=(COLOR, None), width=(NUM, 1), fill_alpha=(NUM, 1)),
    "circle": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 10), fill=(COLOR, None), stroke=(COLOR, None), width=(NUM, 1), dash=(STR, ""), fill_alpha=(NUM, 1)),
    "arc": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 10), start=(NUM, 0), span=(NUM, 90), color=(COLOR, None), width=(NUM, 1.5), cap=(STR, "flat"),
                dash=(STR, "")),
    "ellipse": dict(x=(NUM, 0), y=(NUM, 0), rx=(NUM, 10), ry=(NUM, 5), rot=(NUM, 0), start=(NUM, 0), span=(NUM, 360), color=(COLOR, None),
                    width=(NUM, 1.2), cap=(STR, "flat"), dash=(STR, "")),
    "ticks": dict(x=(NUM, 0), y=(NUM, 0), r0=(NUM, 90), r1=(NUM, 100), count=(NUM, 72), rot=(NUM, 0), major=(NUM, 6), major_len=(NUM, 6), width=(NUM, 1),
                  major_width=(NUM, 1.6), color=(COLOR, None), major_color=(COLOR, None), labels=(NUM, 0), label_r=(NUM, 110), size=(NUM, 7),
                  label_color=(COLOR, None)),
    "sphere": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), lat=(NUM, 5), lon=(NUM, 8), rot=(NUM, 0), tilt=(NUM, 20), color=(COLOR, None),
                   width=(NUM, 1), back=(NUM, 0.35)),
    "bars": dict(source=(SOURCE, "voice"), x=(NUM, 0), y=(NUM, 0), r0=(NUM, 80), r1=(NUM, 120), w=(NUM, 200), h=(NUM, 40), radial=(BOOL, True),
                 count=(NUM, 96), width=(NUM, 2), color=(COLOR, None), rot=(NUM, 0), floor=(NUM, 0.04)),
    "text": dict(text=(TEXT, ""), x=(NUM, 0), y=(NUM, 0), w=(NUM, 200), h=(NUM, 16), size=(NUM, 9), weight=(STR, "normal"), spacing=(NUM, 0),
                 family=(STR, "mono"), color=(COLOR, None), align=(STR, "left"), glow=(NUM, 0), wrap=(BOOL, False), upper=(BOOL, False),
                 elide=(BOOL, True), shimmer=(BOOL, False)),
    "gradient": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 100), kind=(STR, "linear"), angle=(NUM, 90), cx=(NUM, 0), cy=(NUM, 0), r=(NUM, 100),
                     stops=(POINTS, None)),
    "hexgrid": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 100), size=(NUM, 34), color=(COLOR, None), width=(NUM, 1), lines=(BOOL, True),
                    waves=(BOOL, False), wave_color=(COLOR, None), wave_speed=(NUM, 1.0), cx=(NUM, 0), cy=(NUM, 0)),
    "dotgrid": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 100), spacing=(NUM, 26), r=(NUM, 1.0), color=(COLOR, None), cx=(NUM, 0), cy=(NUM, 0),
                    fade=(NUM, 0)),
    "scan": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 100), band=(NUM, 60), speed=(NUM, 0.2), color=(COLOR, None), lines=(NUM, 0)),
    "core": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 30), color=(COLOR, None), hot=(COLOR, None), level=(NUM, 1)),
    "hex": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 12), rot=(NUM, 0), fill=(COLOR, None), stroke=(COLOR, None), width=(NUM, 1.4), fill_alpha=(NUM, 1),
                sides=(NUM, 6), gauge=(NUM, None), gauge_color=(COLOR, None)),
    "bar": dict(x=(NUM, 0), y=(NUM, 0), w=(NUM, 100), h=(NUM, 5), value=(NUM, 0), color=(COLOR, None), back=(COLOR, None), segments=(NUM, 0), cut=(NUM, 0)),
    "courier": dict(x1=(NUM, 0), y1=(NUM, 0), x2=(NUM, 0), y2=(NUM, 0), bend=(NUM, 0.2), count=(NUM, 36), speed=(NUM, 0.85), color=(COLOR, None),
                    active=(BOOL, True), line=(NUM, 0.25)),
    "embers": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), color=(COLOR, None), size=(NUM, 1)),
    "bolts": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), r0=(NUM, 0.2), r1=(NUM, 1.0), color=(COLOR, None), width=(NUM, 1.6)),
    "streaks": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), color=(COLOR, None), width=(NUM, 1.6)),
    "ripples": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), width=(NUM, 2.2)),
    "shock": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), color=(COLOR, None), width=(NUM, 4)),
    "sweep": dict(x=(NUM, 0), y=(NUM, 0), r=(NUM, 100), r0=(NUM, 0), span=(NUM, 40), color=(COLOR, None)),
}
CHOICES = {"weight": ("normal", "bold"), "family": ("mono", "ui"), "align": ("left", "center", "right"), "cap": ("flat", "round"),
           "kind": ("linear", "radial")}

TOP_LEVEL = {"version", "name", "description", "palette", "fonts", "vars", "modes", "states", "glyphs", "persona", "layers", "glow",
             "boot", "min_size", "stats_order"}
REQUIRED_MODES = ("idle", "starting", "working", "waiting", "ok", "bad", "stopping", "stopped")
MODE_KEYS_REQUIRED = ("persona", "spin", "tick", "charge", "core", "hz", "amp", "jit", "bright", "embers", "sweep", "bolts", "flow")
STATES = ("idle", "pending", "running", "waiting", "ran", "verified", "denied", "failed", "rolled back")

VARIABLES = {
    "W, H": "the window size in pixels",
    "t": "seconds since start (a steady clock for animation)",
    "persona": "0 = JARVIS (conversation), 1 = FRIDAY (execution); glides, never snaps",
    "mode": "the state: starting idle working waiting ok bad stopping stopped (text)",
    "mode_color": "the palette name for the title of this state (text)",
    "m.<key>": "the eased value of any number in the `modes` table: m.spin m.tick m.charge m.core m.bright m.embers ...",
    "boot": "0 -> 1 while the HUD draws itself in",
    "power": "0 -> 1 while the core powers up",
    "core": "core brightness 0..~1.6: the state's level, a slow pulse, and the flare from real events",
    "flare": "decaying kick from each real event",
    "shock": "-1, or 0..1 while the verified shockwave runs",
    "rot_a, rot_b, rot_c": "degrees: slow spin, slower scale spin, a counter-spin (all follow the state's speed)",
    "sweep": "degrees: where the radar wedge is",
    "level": "0..1 loudness of the REAL audio (yours while listening, its own while speaking)",
    "voice_state": "off listening hearing thinking speaking muted offline (text)",
    "voice_tag / voice_on": "the words for the voice badge, and whether to show it",
    "title, subtitle, goal": "the state's title, a short note, and the words of the goal (text)",
    "has_goal": "a plan, steps or checks exist",
    "plan_state": "none planning ready failed (text)",
    "nsteps, nchecks, done": "counts of real steps, real checks, and steps finished",
    "nnodes": "how many AIs are available",
    "stats.<name>": "the readout: stats.elapsed stats.steps stats.checks stats.brain stats.cost (text)",
    "hover": "the family of the brain the mouse is over (text)",
    "quality": "0 (full detail) .. 3 (the machine is struggling and detail was dropped)",
    "item, i, n": "inside a repeat: the current data row, its index, and the row count",
    "(your vars)": "everything in the spec's `vars` table, evaluated in order each frame (the shipped design keeps its layout there: R, cx, cy, pw, ...)",
}
