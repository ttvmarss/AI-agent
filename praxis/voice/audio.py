"""Audio plumbing in pure Python: 16 kHz mono 16-bit PCM, level, resampling, WAV files and an energy voice-activity detector."""
import array
import math
import wave

RATE = 16000


def rms(pcm):
    """Root-mean-square level of 16-bit PCM, 0.0 (silence) to 1.0 (full scale)."""
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a)) / 32768.0


def to_mono16k(raw, rate, channels=1, sample_format="int16"):
    """Convert captured audio (int16 or float32, any rate, any channel count) to 16 kHz mono int16 bytes."""
    if sample_format == "float32":
        f = array.array("f")
        f.frombytes(raw[: len(raw) // 4 * 4])
        a = array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in f))
    else:
        a = array.array("h")
        a.frombytes(raw[: len(raw) // 2 * 2])
    if channels > 1:
        n = len(a) // channels
        a = array.array("h", (sum(a[i * channels:(i + 1) * channels]) // channels for i in range(n)))
    if rate != RATE and len(a):
        a = resample(a, rate, RATE)
    return a.tobytes()


def resample(a, src, dst):
    """Linear-interpolation resampler (speech needs nothing fancier). `a` is an array('h')."""
    if src == dst or not len(a):
        return a
    n = max(1, int(len(a) * dst / src))
    step = (len(a) - 1) / max(n - 1, 1) if n > 1 else 0
    out = array.array("h")
    for i in range(n):
        pos = i * step
        j = int(pos)
        frac = pos - j
        k = min(j + 1, len(a) - 1)
        out.append(int(a[j] + (a[k] - a[j]) * frac))
    return out


def read_wav(path):
    """-> (pcm16 mono 16 kHz bytes). Accepts any common PCM WAV."""
    with wave.open(path, "rb") as w:
        raw, rate, ch, width = w.readframes(w.getnframes()), w.getframerate(), w.getnchannels(), w.getsampwidth()
    if width != 2:
        raise ValueError(f"{path}: only 16-bit WAV is supported")
    return to_mono16k(raw, rate, ch)


def write_wav(path, pcm, rate=RATE):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(pcm)


def envelope(pcm, rate, fps=30):
    """Loudness over time (one value per 1/fps s, normalised 0..1): what the core's voice ring shows while PRAXIS speaks."""
    hop = max(1, int(rate / fps)) * 2
    vals = [rms(pcm[i:i + hop]) for i in range(0, len(pcm), hop)]
    top = max(vals, default=0.0) or 1.0
    return [min(1.0, v / top) for v in vals]


class Segmenter:
    """Cuts a continuous stream into utterances. An adaptive noise floor means a fan or a quiet room both work; a short
    pre-roll keeps the first syllable; a hangover keeps the last; clicks and coughs shorter than min_speech_ms are dropped."""

    def __init__(self, rate=RATE, frame_ms=30, min_speech_ms=280, hangover_ms=600, max_ms=14000, preroll_ms=300,
                 margin=3.2, floor_min=0.006):
        self.rate, self.fb = rate, int(rate * frame_ms / 1000) * 2
        self.min_frames = max(1, min_speech_ms // frame_ms)
        self.hang_frames = max(1, hangover_ms // frame_ms)
        self.max_frames = max(1, max_ms // frame_ms)
        self.pre_frames = max(0, preroll_ms // frame_ms)
        self.margin, self.floor_min = margin, floor_min
        self.reset()

    def reset(self):
        self.buf, self.pre, self.speech, self.silent, self.voiced = b"", [], [], 0, 0
        self.lvl_sum, self.lvl_sq = 0.0, 0.0
        self.floor, self.in_speech, self.level, self._run = 0.01, False, 0.0, 0

    @property
    def threshold(self):
        return max(self.floor * self.margin, self.floor_min)

    def feed(self, pcm):
        """Feed any amount of 16 kHz mono int16; returns the list of utterances (bytes) completed by this chunk."""
        self.buf += pcm
        out = []
        while len(self.buf) >= self.fb:
            frame, self.buf = self.buf[:self.fb], self.buf[self.fb:]
            u = self._frame(frame)
            if u:
                out.append(u)
        return out

    def _frame(self, frame):
        lvl = rms(frame)
        self.level = lvl
        loud = lvl > self.threshold
        if not self.in_speech:
            if not loud:                                   # only silence teaches the noise floor (fast down, slow up)
                self.floor = self.floor * 0.97 + lvl * 0.03 if lvl > self.floor else self.floor * 0.8 + lvl * 0.2
                self._run = 0
                self.pre.append(frame); self.pre = self.pre[-self.pre_frames:] if self.pre_frames else []
                return None
            self._run += 1
            self.pre.append(frame)
            if self._run < 2:                              # one loud frame is a click, not speech
                return None
            self.in_speech, self.speech, self.silent, self.voiced = True, list(self.pre), 0, self._run
            self.lvl_sum, self.lvl_sq = lvl * self._run, lvl * lvl * self._run
            self.pre = []
            return None
        self.speech.append(frame)
        self.lvl_sum += lvl; self.lvl_sq += lvl * lvl
        if loud:
            self.silent, self.voiced = 0, self.voiced + 1
        else:
            self.silent += 1
        if self.silent >= self.hang_frames:
            return self._end()
        if len(self.speech) >= self.max_frames:
            n = max(len(self.speech), 1)
            mean = self.lvl_sum / n
            var = max(0.0, self.lvl_sq / n - mean * mean)
            if mean > 0 and math.sqrt(var) / mean < 0.2:        # no pause AND no syllables: a fan, a machine, steady music
                self.floor = max(self.floor, mean)              # learn it as the new background level and drop it
                self._end()
                return None
            return self._end()                                  # real, uninterrupted speech: cut at the maximum as before
        return None

    def _end(self):
        voiced, speech = self.voiced, b"".join(self.speech)
        self.in_speech, self.speech, self.silent, self.voiced, self._run, self.pre = False, [], 0, 0, 0, []
        return speech if voiced >= self.min_frames else None
