"""Builds the voice loop from the [voice] config. Heavy imports and one-time model downloads happen here, off the UI thread;
every failure becomes a VoiceUnavailable with a reason a person can act on (the window then shows a typing fallback)."""
import os

from ..voice import models, tts
from ..voice.loop import VoiceLoop
from ..voice.stt import WhisperRecognizer
from .voice_actions import ControllerActions


class VoiceUnavailable(Exception):
    pass


def log_line(text):
    """~/.praxis/voice/voice.log: what the voice actually did, for when something sounds wrong."""
    try:
        import time
        os.makedirs(tts.voice_dir(), exist_ok=True)
        with open(os.path.join(tts.voice_dir(), "voice.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except Exception:
        pass


def choose_voice(name, progress=lambda text, frac=None: None):
    """The neural voice you asked for if it is installed or can be downloaded; else the next best neural voice; else the operating
    system's. Returns (voice, note); the note says what went wrong, so a poor voice is never a mystery."""
    notes = []
    try:
        import piper  # noqa: F401
    except Exception as e:
        notes.append(f"piper-tts is not installed ({type(e).__name__})")
        v = tts.pick_voice(name)
        return v, "; ".join(notes) + " - using the system voice"
    for cand in dict.fromkeys([name, "en_GB-alan-medium"]):
        v = tts.pick_voice(cand)
        if v is not None and v.name.startswith("piper"):
            return v, "; ".join(notes)
        try:
            models.ensure_piper(cand, progress=lambda t, got, total, c=cand: progress(f"Downloading the voice {c}: {100 * got // max(total, 1)}%", got / max(total, 1)))
            v = tts.pick_voice(cand)
            if v is not None and v.name.startswith("piper"):
                return v, "; ".join(notes)
        except Exception as e:
            notes.append(f"could not download {cand}: {type(e).__name__}: {e}")
    v = tts.pick_voice(name)
    return v, "; ".join(notes) + " - using the system voice"


def build_voice(controller, vcfg, progress=lambda text, frac=None: None, on_mute=None, mic=None, speaker=None, recognizer=None,
                voice=None):
    """Any of mic / speaker / recognizer / voice can be injected (tests do); otherwise the real engines are used."""
    if mic is None:
        try:
            import sounddevice  # noqa: F401
        except Exception as e:
            raise VoiceUnavailable("the audio library is missing: pip install sounddevice") from e
        from ..voice.devices import SdMic
        dev = vcfg.get("input_device") or None
        mic = SdMic(int(dev) if str(dev).isdigit() else dev)
    if speaker is None:
        from ..voice.devices import SdSpeaker
        speaker = SdSpeaker()
    if recognizer is None:
        try:
            import faster_whisper  # noqa: F401
        except Exception as e:
            raise VoiceUnavailable("the speech recogniser is missing: pip install faster-whisper") from e
        progress("Loading the speech recogniser (the first run downloads about 150 MB)...", None)
        recognizer = WhisperRecognizer(vcfg.get("stt_model", "base.en"), root=os.path.join(tts.voice_dir(), "whisper"))
        try:
            recognizer.load()
        except Exception as e:
            raise VoiceUnavailable(f"could not load the speech recogniser: {type(e).__name__}: {e}") from e
    note = ""
    if voice is None and vcfg.get("speak", True):
        voice, note = choose_voice(vcfg.get("voice", "jarvis-high"), progress)
    try:
        loop = VoiceLoop(ControllerActions(controller, on_mute), recognizer, mic, speaker, voice,
                         wake_word=vcfg.get("wake_word", "praxis"), speak=bool(voice) and vcfg.get("speak", True),
                         attentive_s=float(vcfg.get("attentive_s", 15.0)), approval_s=float(vcfg.get("approval_s", 60.0)))
        loop.engine, loop.voice_note = (voice.name if voice else "silent"), note
        log_line(f"voice engine: {loop.engine}" + (f"  ({note})" if note else ""))
        loop.start()
    except Exception as e:
        raise VoiceUnavailable(f"could not open the microphone: {type(e).__name__}: {e}") from e
    return loop
