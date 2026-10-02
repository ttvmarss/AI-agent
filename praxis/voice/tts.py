"""Speech synthesis. Every engine returns PCM so the app plays it itself: it then knows when speech ends (no echo) and can
show the real loudness envelope on the core. Order of preference: Piper (neural, local) -> the OS voice."""
import os
import subprocess
import sys
import tempfile
import wave

from ..paths import home


def voice_dir():
    return os.path.join(home(), "voice")


class Voice:
    name = "none"

    def synth(self, text):                 # -> (pcm16 bytes, sample rate)
        raise NotImplementedError


class PiperVoice(Voice):
    def __init__(self, voice="en_GB-alan-medium", root=None, speed=1.0):
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

    def synth(self, text):
        if self._v is None:
            from piper import PiperVoice as PV
            self._v = PV.load(self.path)
        buf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); buf.close()
        try:
            with wave.open(buf.name, "wb") as w:
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


def pick_voice(voice="en_GB-alan-medium", root=None):
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
