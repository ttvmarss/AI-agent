"""`praxis hud ...`: work with the HUD's JSON design. No Qt needed (it only reads and checks the file)."""
import os
import shutil

from .desktop.qt.hud import schema as S, spec as specmod
from .desktop.qt.hud.expr import FUNCS


def docs():
    out = ["# PRAXIS HUD design reference", "",
           "The whole screen is a JSON file. PRAXIS reads `~/.praxis/hud.json` if it exists (else the shipped `default.hud.json`, "
           "`praxis hud export` copies it there) and reloads it within a second of every save. A mistake never breaks the window: the error goes "
           "to the event feed and the last good design stays.", "",
           "## Top-level keys", "",
           "| key | meaning |", "|---|---|",
           "| `version` | always 1 |", "| `name`, `description` | shown in the log when the design loads |",
           "| `palette` | named colours. Forms: `\"#rrggbb\"`, `\"#rrggbbaa\"`, `[r,g,b]`, a name, `{\"mix\":[a,b,t]}`, `{\"persona\":[jarvis_side, friday_side]}`, "
           "`{\"of\":\"name\",\"alpha\":0.4}`, or `\"=expression\"` returning a name |",
           "| `vars` | named expressions evaluated in order every frame: the layout lives here (`R`, `cx`, `cy`, panel sizes) |",
           "| `modes` | for each state, the numbers the machine eases to (spin, core, embers, persona...). Every state names every number |",
           "| `states` | how a plan step / check looks in each state: a palette name, or `{\"color\",\"alpha\",\"width\"}` |",
           "| `glyphs` | the symbol shown for each step state |",
           "| `persona` | `{\"rate\": 1.4}`: how fast JARVIS and FRIDAY hand over |",
           "| `boot` | `{\"seconds\", \"delay\", \"span\"}`: the draw-in sequence; an element's `boot: k` fades in as the k-th |",
           "| `glow` | `{x,y,w,h}` expressions: where the bloom buffer sits (elements with `\"glow\": true`, in one run, share it) |",
           "| `layers` | the elements, back to front |", "",
           "Every element also takes `id`, `visible` (true/false or an expression), `opacity` (0..1 or expression) and `boot` (index). A top-level element "
           "may set `\"glow\": true` (add its light and bloom it) and `\"cache\": true` or `\"cache\": \"persona\"` (paint once, reuse until the window "
           "resizes, or the active mind changes; it must not depend on `t`).", "",
           "## Expressions", "",
           "Anywhere a number is expected you may write an expression as a string: `\"R * 1.4 + sin(t * 2) * 6\"`. Text is a template: "
           "`\"{title}  {stats.cost}\"`, with an optional Python format after a bar: `\"{item.pressure * 100|.0f}%\"`. Colours that must be computed start "
           "with `=`. Operators: `+ - * / // % **`, comparisons, `and or not`, `a if c else b`, `x in (a, b)`. Functions: "
           + ", ".join(f"`{k}`" for k in sorted(FUNCS)) + ". Nothing else is allowed (no imports, no files, no methods); a bad value draws as 0 and is "
           "reported once in the event feed.", "",
           "Angles are degrees, 0 = straight up, clockwise.", "",
           "### Variables", "", "| name | meaning |", "|---|---|"]
    out += [f"| `{k}` | {v} |" for k, v in S.VARIABLES.items()]
    out += ["", "## Data sources (for `repeat`)", "", "| source | rows |", "|---|---|"]
    out += [f"| `{k}` | {v} |" for k, v in S.SOURCES.items()]
    out += ["", "A `repeat` draws its `item` children once per row with `item`, `i` and `n` set, translated by `x + dx*i, y + dy*i` (and rotated by "
            "`rot + drot*i`), or `count: N` for N plain repetitions. `hit_w`/`hit_h` make a row hoverable (brain rows show their tooltip).", "",
            "## Elements", ""]
    for name, props in S.ELEMENTS.items():
        out.append(f"### `{name}`")
        out.append("")
        out.append(", ".join(f"`{k}` ({kind}" + (f", default {d!r}" if d not in (None, "") else "") + ")" for k, (kind, d) in props.items()))
        out.append("")
    return "\n".join(out) + "\n"


def run(action, target=None, out=print):
    """-> exit code."""
    if action == "path":
        mine = specmod.user_path()
        out(f"shipped design : {specmod.DEFAULT_PATH}")
        out(f"your design    : {mine}  ({'present: it is used' if os.path.isfile(mine) else 'not there: the shipped design is used'})")
        return 0
    if action == "docs":
        out(docs().rstrip("\n"))
        return 0
    if action == "export":
        dest = target or specmod.user_path()
        if os.path.exists(dest):
            out(f"{dest} already exists; not overwritten. Delete it first, or give another path:  praxis hud export <file>")
            return 1
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        shutil.copyfile(specmod.DEFAULT_PATH, dest)
        out(f"copied the shipped design to {dest}\nEdit it while PRAXIS runs: the screen follows within a second.\n`praxis hud validate` checks it.")
        return 0
    if action == "validate":
        path = target or (specmod.user_path() if os.path.isfile(specmod.user_path()) else specmod.DEFAULT_PATH)
        sp = specmod.load(path)
        out(f"{path}")
        out(sp.report())
        out("OK: this design can be used." if sp.ok else f"{len(sp.errors)} error(s): this design cannot be used (PRAXIS keeps the last good one).")
        return 0 if sp.ok else 1
    out(f"unknown hud action {action!r}")
    return 2
