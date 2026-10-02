"""Builds the voice loop from the [voice] config. Heavy imports and one-time model downloads happen here, off the UI thread;
every failure becomes a VoiceUnavailable with a reason a person can act on (the window then shows a typing fallback)."""
import os

from ..voice import models, tts
from ..voice.loop import VoiceLoop
from ..voice.stt import WhisperRecognizer
from .voice_actions import ControllerActions


class VoiceUnavailable(Exception):
    pass


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
    if voice is None and vcfg.get("speak", True):
        name = vcfg.get("voice", "en_GB-alan-medium")
        voice = tts.pick_voice(name)
        if voice is None or not voice.name.startswith("piper"):
            try:
                import piper  # noqa: F401
                models.ensure_piper(name, progress=lambda t, got, total: progress(f"{t}: {100 * got // max(total, 1)}%", got / max(total, 1)))
                voice = tts.pick_voice(name)
            except Exception:
                pass                                           # no neural voice: the operating system's voice is used, or silence
    try:
        loop = VoiceLoop(ControllerActions(controller, on_mute), recognizer, mic, speaker, voice,
                         wake_word=vcfg.get("wake_word", "praxis"), speak=bool(voice) and vcfg.get("speak", True),
                         attentive_s=float(vcfg.get("attentive_s", 10.0)), approval_s=float(vcfg.get("approval_s", 60.0)))
        loop.start()
    except Exception as e:
        raise VoiceUnavailable(f"could not open the microphone: {type(e).__name__}: {e}") from e
    return loop
