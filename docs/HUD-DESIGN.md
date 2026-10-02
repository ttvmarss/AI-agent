# PRAXIS HUD design reference

The whole screen is a JSON file. PRAXIS reads `~/.praxis/hud.json` if it exists (else the shipped `default.hud.json`, `praxis hud export` copies it there) and reloads it within a second of every save. A mistake never breaks the window: the error goes to the event feed and the last good design stays.

## Top-level keys

| key | meaning |
|---|---|
| `version` | always 1 |
| `name`, `description` | shown in the log when the design loads |
| `palette` | named colours. Forms: `"#rrggbb"`, `"#rrggbbaa"`, `[r,g,b]`, a name, `{"mix":[a,b,t]}`, `{"persona":[jarvis_side, friday_side]}`, `{"of":"name","alpha":0.4}`, or `"=expression"` returning a name |
| `vars` | named expressions evaluated in order every frame: the layout lives here (`R`, `cx`, `cy`, panel sizes) |
| `modes` | for each state, the numbers the machine eases to (spin, core, embers, persona...). Every state names every number |
| `states` | how a plan step / check looks in each state: a palette name, or `{"color","alpha","width"}` |
| `glyphs` | the symbol shown for each step state |
| `persona` | `{"rate": 1.4}`: how fast JARVIS and FRIDAY hand over |
| `boot` | `{"seconds", "delay", "span"}`: the draw-in sequence; an element's `boot: k` fades in as the k-th |
| `glow` | `{x,y,w,h}` expressions: where the bloom buffer sits (elements with `"glow": true`, in one run, share it) |
| `layers` | the elements, back to front |

Every element also takes `id`, `visible` (true/false or an expression), `opacity` (0..1 or expression) and `boot` (index). A top-level element may set `"glow": true` (add its light and bloom it) and `"cache": true` or `"cache": "persona"` (paint once, reuse until the window resizes, or the active mind changes; it must not depend on `t`).

## Expressions

Anywhere a number is expected you may write an expression as a string: `"R * 1.4 + sin(t * 2) * 6"`. Text is a template: `"{title}  {stats.cost}"`, with an optional Python format after a bar: `"{item.pressure * 100|.0f}%"`. Colours that must be computed start with `=`. Operators: `+ - * / // % **`, comparisons, `and or not`, `a if c else b`, `x in (a, b)`. Functions: `abs`, `atan2`, `ceil`, `clamp`, `cos`, `deg`, `ease`, `exp`, `float`, `floor`, `fract`, `hypot`, `int`, `len`, `lerp`, `log`, `max`, `min`, `mix`, `noise`, `pow`, `pulse`, `rad`, `round`, `sat`, `sign`, `sin`, `smooth`, `sqrt`, `step`, `tan`, `tri`. Nothing else is allowed (no imports, no files, no methods); a bad value draws as 0 and is reported once in the event feed.

Angles are degrees, 0 = straight up, clockwise.

### Variables

| name | meaning |
|---|---|
| `W, H` | the window size in pixels |
| `t` | seconds since start (a steady clock for animation) |
| `persona` | 0 = JARVIS (conversation), 1 = FRIDAY (execution); glides, never snaps |
| `mode` | the state: starting idle working waiting ok bad stopping stopped (text) |
| `mode_color` | the palette name for the title of this state (text) |
| `m.<key>` | the eased value of any number in the `modes` table: m.spin m.tick m.charge m.core m.bright m.embers ... |
| `boot` | 0 -> 1 while the HUD draws itself in |
| `power` | 0 -> 1 while the core powers up |
| `core` | core brightness 0..~1.6: the state's level, a slow pulse, and the flare from real events |
| `flare` | decaying kick from each real event |
| `shock` | -1, or 0..1 while the verified shockwave runs |
| `rot_a, rot_b, rot_c` | degrees: slow spin, slower scale spin, a counter-spin (all follow the state's speed) |
| `sweep` | degrees: where the radar wedge is |
| `level` | 0..1 loudness of the REAL audio (yours while listening, its own while speaking) |
| `voice_state` | off listening hearing thinking speaking muted offline (text) |
| `voice_tag / voice_on` | the words for the voice badge, and whether to show it |
| `title, subtitle, goal` | the state's title, a short note, and the words of the goal (text) |
| `has_goal` | a plan, steps or checks exist |
| `plan_state` | none planning ready failed (text) |
| `nsteps, nchecks, done` | counts of real steps, real checks, and steps finished |
| `nnodes` | how many AIs are available |
| `stats.<name>` | the readout: stats.elapsed stats.steps stats.checks stats.brain stats.cost (text) |
| `hover` | the family of the brain the mouse is over (text) |
| `quality` | 0 (full detail) .. 3 (the machine is struggling and detail was dropped) |
| `item, i, n` | inside a repeat: the current data row, its index, and the row count |
| `(your vars)` | everything in the spec's `vars` table, evaluated in order each frame (the shipped design keeps its layout there: R, cx, cy, pw, ...) |

## Data sources (for `repeat`)

| source | rows |
|---|---|
| `nodes` | your AIs: item.family item.name item.cost_class item.pressure item.blocked item.cooling_s item.models item.active item.sub item.color item.x item.y item.side |
| `steps` | the plan's real steps: item.label item.state item.glyph item.color item.i |
| `checks` | the goal's real checks: item.ok item.glyph item.color item.i |
| `log` | the latest real events: item.time item.text item.level item.color item.i (newest last) |
| `stats` | the goal readout: item.key item.value |
| `legend` | PLAN / ACT / VERIFY: item.name item.text item.color |
| `ring_plan` | segments of the PLAN ring: item.start item.span item.state item.color item.alpha item.width item.i item.n |
| `ring_act` | segments of the ACT ring (one per real step) |
| `ring_verify` | segments of the VERIFY ring (one per real check) |
| `voice` | the last moments of the real audio level, 0..1, oldest first: item.v item.i item.n |

A `repeat` draws its `item` children once per row with `item`, `i` and `n` set, translated by `x + dx*i, y + dy*i` (and rotated by `rot + drot*i`), or `count: N` for N plain repetitions. `hit_w`/`hit_h` make a row hoverable (brain rows show their tooltip).

## Elements

### `group`

`x` (num, default 0), `y` (num, default 0), `rot` (num, default 0), `scale` (num, default 1), `children` (list)

### `repeat`

`source` (source), `count` (num), `x` (num, default 0), `y` (num, default 0), `dx` (num, default 0), `dy` (num, default 0), `rot` (num, default 0), `drot` (num, default 0), `limit` (num, default 1000), `reverse` (bool, default False), `hit_w` (num, default 0), `hit_h` (num, default 0), `item` (list)

### `rect`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 100), `cut` (num, default 0), `fill` (color), `stroke` (color), `width` (num, default 1), `dash` (str), `fill_alpha` (num, default 1)

### `panel`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 100), `cut` (num, default 14), `fill` (color), `stroke` (color), `width` (num, default 1.2), `title` (text), `title_color` (color), `size` (num, default 8), `ticks` (bool, default True), `fill_alpha` (num, default 1)

### `line`

`x1` (num, default 0), `y1` (num, default 0), `x2` (num, default 0), `y2` (num, default 0), `color` (color), `width` (num, default 1), `dash` (str), `cap` (str, default 'flat')

### `poly`

`points` (points), `close` (bool, default False), `fill` (color), `stroke` (color), `width` (num, default 1), `fill_alpha` (num, default 1)

### `circle`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 10), `fill` (color), `stroke` (color), `width` (num, default 1), `dash` (str), `fill_alpha` (num, default 1)

### `arc`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 10), `start` (num, default 0), `span` (num, default 90), `color` (color), `width` (num, default 1.5), `cap` (str, default 'flat'), `dash` (str)

### `ellipse`

`x` (num, default 0), `y` (num, default 0), `rx` (num, default 10), `ry` (num, default 5), `rot` (num, default 0), `start` (num, default 0), `span` (num, default 360), `color` (color), `width` (num, default 1.2), `cap` (str, default 'flat'), `dash` (str)

### `ticks`

`x` (num, default 0), `y` (num, default 0), `r0` (num, default 90), `r1` (num, default 100), `count` (num, default 72), `rot` (num, default 0), `major` (num, default 6), `major_len` (num, default 6), `width` (num, default 1), `major_width` (num, default 1.6), `color` (color), `major_color` (color), `labels` (num, default 0), `label_r` (num, default 110), `size` (num, default 7), `label_color` (color)

### `sphere`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `lat` (num, default 5), `lon` (num, default 8), `rot` (num, default 0), `tilt` (num, default 20), `color` (color), `width` (num, default 1), `back` (num, default 0.35)

### `bars`

`source` (source, default 'voice'), `x` (num, default 0), `y` (num, default 0), `r0` (num, default 80), `r1` (num, default 120), `w` (num, default 200), `h` (num, default 40), `radial` (bool, default True), `count` (num, default 96), `width` (num, default 2), `color` (color), `rot` (num, default 0), `floor` (num, default 0.04)

### `text`

`text` (text), `x` (num, default 0), `y` (num, default 0), `w` (num, default 200), `h` (num, default 16), `size` (num, default 9), `weight` (str, default 'normal'), `spacing` (num, default 0), `family` (str, default 'mono'), `color` (color), `align` (str, default 'left'), `glow` (num, default 0), `wrap` (bool, default False), `upper` (bool, default False), `elide` (bool, default True), `shimmer` (bool, default False)

### `gradient`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 100), `kind` (str, default 'linear'), `angle` (num, default 90), `cx` (num, default 0), `cy` (num, default 0), `r` (num, default 100), `stops` (points)

### `hexgrid`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 100), `size` (num, default 34), `color` (color), `width` (num, default 1), `lines` (bool, default True), `waves` (bool, default False), `wave_color` (color), `wave_speed` (num, default 1.0), `cx` (num, default 0), `cy` (num, default 0)

### `dotgrid`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 100), `spacing` (num, default 26), `r` (num, default 1.0), `color` (color), `cx` (num, default 0), `cy` (num, default 0), `fade` (num, default 0)

### `scan`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 100), `band` (num, default 60), `speed` (num, default 0.2), `color` (color), `lines` (num, default 0)

### `core`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 30), `color` (color), `hot` (color), `level` (num, default 1)

### `hex`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 12), `rot` (num, default 0), `fill` (color), `stroke` (color), `width` (num, default 1.4), `fill_alpha` (num, default 1), `sides` (num, default 6), `gauge` (num), `gauge_color` (color)

### `bar`

`x` (num, default 0), `y` (num, default 0), `w` (num, default 100), `h` (num, default 5), `value` (num, default 0), `color` (color), `back` (color), `segments` (num, default 0), `cut` (num, default 0)

### `courier`

`x1` (num, default 0), `y1` (num, default 0), `x2` (num, default 0), `y2` (num, default 0), `bend` (num, default 0.2), `count` (num, default 36), `speed` (num, default 0.85), `color` (color), `active` (bool, default True), `line` (num, default 0.25)

### `embers`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `color` (color), `size` (num, default 1)

### `bolts`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `r0` (num, default 0.2), `r1` (num, default 1.0), `color` (color), `width` (num, default 1.6)

### `streaks`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `color` (color), `width` (num, default 1.6)

### `ripples`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `width` (num, default 2.2)

### `shock`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `color` (color), `width` (num, default 4)

### `sweep`

`x` (num, default 0), `y` (num, default 0), `r` (num, default 100), `r0` (num, default 0), `span` (num, default 40), `color` (color)

