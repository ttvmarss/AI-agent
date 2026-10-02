"""Speech synthesis. Every engine returns PCM so the app plays it itself: it then knows when speech ends (no echo) and can
show the real loudness envelope on the core. Order of preference: Piper (neural, local) -> the OS voice."""
import os
import re
import subprocess
import sys
import tempfile
import wave

from ..paths import home


def voice_dir():
    return os.path.join(home(), "voice")


_EXT = r"txt|py|md|json|js|ts|tsx|csv|html|css|toml|yaml|yml|log|exe|bat|ps1|sh|cfg|ini|xml|pdf|docx|xlsx|png|jpg|zip"


def speakable(text):
    """Make written text pleasant to say: "hello.txt" -> "hello dot txt", no markup, no stray symbols, no paths read letter by letter."""
    t = str(text or "")
    t = re.sub(r"[`*_#>]+", " ", t)
    t = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){3,}", "that file path", t)
    t = re.sub(rf"(\w)\.({_EXT})\b", r"\1 dot \2", t, flags=re.I)
    t = t.replace("&", " and ").replace("->", " to ").replace("=>", " to ").replace("%", " percent")
    t = re.sub(r"\s*[/\\|]\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def split_sentences(text, min_len=24, max_len=220):
    """Sentences for pipelined synthesis: the first is spoken while the rest are still being made. Tiny pieces are merged so
    the voice does not sound clipped; a very long sentence is cut at a comma."""
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    out = []
    for s in parts:
        while len(s) > max_len:
            cut = s.rfind(",", 0, max_len)
            cut = cut if cut > 40 else s.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            out.append(s[:cut + 1].strip()); s = s[cut + 1:].strip()
        if s:
            if out and len(out[-1]) < min_len:
                out[-1] += " " + s
            else:
                out.append(s)
    return out or [text.strip()]


class Voice:
    name = "none"

    def synth(self, text):                 # -> (pcm16 bytes, sample rate)
        raise NotImplementedError


class PiperVoice(Voice):
    def __init__(self, voice="jarvis-high", root=None, speed=1.0):
        self.name = f"piper:{voice}"
        self.path = os.path.join(root or voice_dir(), voice + ".onnx")
        self.speed, self._v = speed, None

    def available(self):
        if not os.path.exists(self.path):
            return False
        try:
            import piper  # noqa: F401
            return True
        except ImportError:
            return False

    def _config(self):
        """Pace: speed 1.0 is the voice's own. Older piper-tts has no SynthesisConfig; then the default pace is used."""
        if abs(self.speed - 1.0) < 1e-6:
            return None
        try:
            from piper import SynthesisConfig
            return SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, self.speed)))
        except Exception:
            return None

    def synth(self, text):
        if self._v is None:
            from piper import PiperVoice as PV
            self._v = PV.load(self.path)
        buf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); buf.close()
        try:
            with wave.open(buf.name, "wb") as w:
                cfg = self._config()
                if cfg is not None:
                    self._v.synthesize_wav(text, w, syn_config=cfg)
                else:
                    self._v.synthesize_wav(text, w)
            with wave.open(buf.name, "rb") as r:
                return r.readframes(r.getnframes()), r.getframerate()
        finally:
            os.unlink(buf.name)


class OsVoice(Voice):
    """The operating system's own voice, rendered to a WAV so it plays through the same path. Windows: SAPI via PowerShell
    (nothing to install); macOS: say; Linux: espeak-ng."""

    def __init__(self):
        self.name = "os:" + sys.platform

    def available(self):
        import shutil
        if sys.platform.startswith("win"):
            return bool(shutil.which("powershell"))
        if sys.platform == "darwin":
            return bool(shutil.which("say"))
        return bool(shutil.which("espeak-ng") or shutil.which("espeak"))

    def synth(self, text):
        import shutil
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); wav.close()
        try:
            if sys.platform.startswith("win"):
                script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                          f"$s.SetOutputToWaveFile('{wav.name}'); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], input=text, text=True,
                               check=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            elif sys.platform == "darwin":
                subprocess.run(["say", "-o", wav.name, "--data-format=LEI16@22050", text], check=True, timeout=60)
            else:
                exe = shutil.which("espeak-ng") or shutil.which("espeak")
                subprocess.run([exe, "-w", wav.name, text], check=True, timeout=60)
            with wave.open(wav.name, "rb") as r:
                if r.getsampwidth() != 2:
                    raise RuntimeError("the OS voice did not produce 16-bit audio")
                pcm, rate, ch = r.readframes(r.getnframes()), r.getframerate(), r.getnchannels()
            if ch > 1:
                from .audio import to_mono16k
                pcm, rate = to_mono16k(pcm, rate, ch), rate
            return pcm, rate
        finally:
            os.unlink(wav.name)


def pick_voice(voice="jarvis-high", root=None):
    """The best voice that is actually installed, or None (then PRAXIS stays silent and says so on screen)."""
    p = PiperVoice(voice, root)
    if p.available():
        return p
    o = OsVoice()
    return o if o.available() else None


class FakeVoice(Voice):
    """Silent stand-in for tests: records what it was asked to say and returns a short burst of audio."""
    name = "fake"

    def __init__(self, ms_per_word=60):
        self.said, self.ms = [], ms_per_word

    def synth(self, text):
        self.said.append(text)
        import array
        n = int(22050 * self.ms * max(1, len(text.split())) / 1000)
        return array.array("h", [3000 if (i // 40) % 2 else -3000 for i in range(n)]).tobytes(), 22050
