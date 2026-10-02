"""Wake word and intents. Pure text in, a small decision out. Everything that could be dangerous is deliberately strict."""
import difflib
import re
from dataclasses import dataclass

FILLER = {"hey", "hi", "ok", "okay", "yo", "oh"}
# Speech recognisers hear a made-up word oddly; these are the common mishearings of "praxis".
ALIASES = {"praxis", "praxus", "prax", "pracsis", "praxes", "brexis", "proxis", "prexis", "praxsis"}


def normalize(text):
    t = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower().replace("’", "'"))
    return re.sub(r"\s+", " ", t).strip()


def _is_wake(tok, wake, aliases):
    if tok == wake or tok in aliases:
        return True
    return len(tok) >= 4 and difflib.SequenceMatcher(None, tok, wake).ratio() >= 0.8


def split_wake(text, wake="praxis", aliases=ALIASES):
    """-> (heard_wake, rest). The wake word must be among the first three words ("hey praxis, ...", "ok praxis ...").
    `rest` is the ORIGINAL text after it (punctuation intact: a file called calc.py stays calc.py). A word split in two by the
    recogniser ("prax is") must JOIN to exactly the wake word or an alias; only a single word may match fuzzily."""
    text = (text or "").replace("\u2019", "'").strip()
    words = [(m.group(0).lower(), m.end()) for m in re.finditer(r"[A-Za-z0-9']+", text)][:4]
    known = {wake} | set(aliases)
    for i in range(min(3, len(words))):
        if not all(w in FILLER for w, _ in words[:i]):
            break
        if i + 1 < len(words) and words[i][0] + words[i + 1][0] in known:
            return True, text[words[i + 1][1]:].lstrip(" ,:;!?.-\u2014")
        if _is_wake(words[i][0], wake, aliases):
            return True, text[words[i][1]:].lstrip(" ,:;!?.-\u2014")
    return False, text


@dataclass
class Intent:
    kind: str          # goal | stop | approve | deny | confirm_risky | status | resume | data | frugal | mute | wake_only | unknown
    arg: str = ""


STOP = re.compile(r"^(stop|abort|halt|cancel|kill it|never ?mind|stop (that|it|everything|now)|cancel (that|it|everything))\b")
DENY = re.compile(r"^(deny|denied|no|nope|negative|reject|decline|don't|do not|dont|absolutely not|no way)\b|\b(do not|don't|dont|not) approve\b")
APPROVE = re.compile(r"^(i )?(approve|approved|prove|proved|prue)\b|^(yes |yeah |ok |okay )?(approve|prove|prue)\b")
YES = re.compile(r"^(yes|yeah|yep|yup|sure|go ahead|do it|okay|ok|proceed|confirmed?)\b")
STATUS = re.compile(r"\b(status|what('s| is) (going on|happening|the status)|how('s| is) it going|are you (done|there|finished|working)|report|progress)\b")
RESUME = re.compile(r"^resume\b")
MUTE = re.compile(r"^(mute|stop listening|go to sleep|be quiet|silence)\b")
DATA = re.compile(r"\b(?P<a>private|project|open)\b( mode| class| data)?$|\b(data|privacy)( class| mode)?( to)? (?P<b>private|project|open)\b")
FRUGAL = re.compile(r"\b(frugal|balanced|quality)( mode)?\b|\buse less claude\b|\bsave (my )?(tokens|usage)\b|\bbest quality\b")


def parse(rest, *, busy=False, approving=False, risky=False):
    """Decide what `rest` (the words after the wake word) means. `approving`: an approval is pending; `risky`: it is Class 4+.
    Approving needs the literal word "approve" for risky actions; a bare "yes" is not enough, silence is a denial."""
    t = normalize(rest)
    if not t:
        return Intent("wake_only")
    if approving:
        if DENY.search(t) or STOP.match(t):
            return Intent("deny")
        if APPROVE.search(t):
            return Intent("approve")
        if YES.match(t):
            return Intent("confirm_risky" if risky else "approve")
        if MUTE.match(t):
            return Intent("mute")                    # the one thing that is always allowed, even mid-approval
        if STATUS.search(t):
            return Intent("status")
        return Intent("unknown")                 # while an approval is pending, nothing else is allowed to become a goal
    if STOP.match(t):
        return Intent("stop")
    if len(t.split()) <= 2 and (APPROVE.match(t) or DENY.match(t) or YES.match(t)):
        return Intent("stray_answer")            # an answer to a question nobody asked: never a goal
    if MUTE.match(t):
        return Intent("mute")
    if RESUME.match(t):
        return Intent("resume")
    m = DATA.search(t)
    if m and len(t.split()) <= 6:
        return Intent("data", m.group("a") or m.group("b"))
    m = FRUGAL.search(t)
    if m and len(t.split()) <= 6:
        word = m.group(1) or ("frugal" if "less claude" in t or "save" in t else "quality")
        return Intent("frugal", word)
    if STATUS.search(t) and len(t.split()) <= 7:
        return Intent("status")
    return Intent("goal", (rest or "").strip())               # the goal keeps its original words and punctuation
