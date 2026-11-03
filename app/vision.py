"""Visual analysis via Claude vision. Strictly evidence-based: unknown stays null. No heuristics, no fake output."""
import base64
import json
import re

from . import config

SYSTEM = """You analyse frames from Minecraft gameplay videos of the 'Unstable SMP / Unstable Universe' series
to document what is VISIBLE. Rules:
- Report only what the frames show (or what on-screen text/signs/name tags explicitly state). Never guess names, owners,
  factions, or mechanics from prior knowledge. If unknown, use null.
- Estimated dimensions must be flagged 'estimated' and only given if scale cues (player height, block grid) exist.
- Mark 'ambiguous': true when you cannot tell what you are looking at or whether two views are the same place.
- Frames that are not in-game footage (facecam, menus, ads) get no observations.
Return ONLY JSON: {"frames":[{"frame_index":int,"in_game":bool,"observations":[{
 "kind":"building|civilization|weapon|item|enchantment|mechanic|event|landmark",
 "name":str|null,"name_source":"on_screen_text|narration_unavailable|none",
 "civilization":str|null,"dimension":"overworld|nether|end|great_sea|farlands|other|unknown",
 "is_interior":bool,"description":str,"materials":[str],
 "est_dimensions":{"w":num,"d":num,"h":num,"basis":str}|null,
 "mechanic":{"how_it_works":str|null,"activation":str|null,"requirements":[str],"vanilla_redstone":bool|null}|null,
 "item":{"lore":[str],"enchantments":[str],"abilities":str|null}|null,
 "changes_from_previous":str|null,"evidence":str,"confidence":0.0-1.0,"ambiguous":bool}]}]}"""


class VisionUnavailable(RuntimeError):
    pass


def _client():
    import anthropic
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise VisionUnavailable("ANTHROPIC_API_KEY is not set; refusing to produce analysis without a real vision model")
    return anthropic.Anthropic()


def _img(path):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode((config.DATA_DIR / path).read_bytes()).decode()}}


def parse_json(text: str):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model output")
    return json.loads(m.group(0))


def analyze_frames(frames, video_title, hint=None, client=None):
    """frames: list of dict(idx,t,path). Returns list of per-frame results."""
    client = client or _client()
    content = [{"type": "text", "text": f"Video: {video_title}\n" + (f"Context from earlier pass: {hint}\n" if hint else "")}]
    for f in frames:
        content.append({"type": "text", "text": f"frame_index={f['idx']} timestamp={f['t']:.1f}s"})
        content.append(_img(f["path"]))
    r = client.messages.create(model=config.VISION_MODEL, max_tokens=4000, system=SYSTEM,
                               messages=[{"role": "user", "content": content}])
    return parse_json(r.content[0].text).get("frames", [])
