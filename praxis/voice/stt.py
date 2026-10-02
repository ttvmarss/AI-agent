"""Speech recognition behind one tiny interface. The real engine is faster-whisper running locally on the CPU."""
import array
import re
import threading

# Whisper invents these on silence or noise. They are never a command.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "subtitles by the amara.org community",
                  "thanks", "the end", "so", "oh", "uh", "um", "hmm"}


# A hint for the decoder: the words this system listens for, so "approve" is not heard as "prove".
VOCAB = "Praxis. Praxis, approve. Praxis, deny. Praxis, stop. Praxis, status. Approve. Deny."


def looping(text):
    """Whisper in noise sometimes falls into a loop and repeats one phrase dozens of times. That is never a command."""
    words = [w for w in re.findall(r"[a-z0-9']+", (text or "").lower())]
    if len(words) < 8:
        return False
    if len(set(words)) / len(words) < 0.3:                       # very few distinct words for the length
        return True
    sentences = [s.strip() for s in re.split(r"[.!?]+", (text or "").lower()) if s.strip()]
    return any(sentences.count(s) >= 3 for s in set(sentences))


class Recognizer:
    def warm(self):
        pass

    def transcribe(self, pcm16):          # 16 kHz mono int16 bytes -> text ("" if nothing credible was said)
        raise NotImplementedError


class FakeRecognizer(Recognizer):
    """Scripted, for tests: returns the queued transcripts in order."""
    def __init__(self, texts=()):
        self.texts, self.heard = list(texts), []

    def transcribe(self, pcm16):
        self.heard.append(len(pcm16))
        return self.texts.pop(0) if self.texts else ""


def add_cuda_dll_dirs(roots=None):
    """On Windows the CUDA libraries that `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` provides live under site-packages/nvidia/*/bin and
    are not on the DLL search path: add them, so the speech recogniser can use the GPU. Returns the folders added."""
    import glob
    import os
    import site
    import sys
    roots = roots if roots is not None else list(dict.fromkeys(sys.path + list(site.getsitepackages() if hasattr(site, "getsitepackages") else []) +
                                                             [site.getusersitepackages()] if hasattr(site, "getusersitepackages") else sys.path))
    added = []
    for r in roots:
        for d in glob.glob(os.path.join(str(r), "nvidia", "*", "bin")):
            if os.path.isdir(d) and d not in added:
                try:
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(d)
                except OSError:
                    pass
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                added.append(d)
    return added


class WhisperRecognizer(Recognizer):
    """faster-whisper. device "auto" tries the GPU first (about 5 to 10 times faster per utterance) and quietly falls back to the CPU if the
    CUDA libraries are missing; model "auto" means small.en on the GPU (more accurate, still quick) and base.en on the CPU."""

    def __init__(self, model="base.en", root=None, device="cpu", compute_type="int8", factory=None, cuda_count=None):
        self.model_name, self.root, self.device, self.compute = model, root, device, compute_type
        self.factory, self._cuda_count = factory, cuda_count
        self.device_used, self.model_used, self.fallback_reason = "", "", ""
        self._m, self._lock = None, threading.Lock()

    def _cuda_devices(self):
        if self._cuda_count is not None:
            return self._cuda_count()
        try:
            add_cuda_dll_dirs()
            import ctranslate2
            return ctranslate2.get_cuda_device_count()
        except Exception:
            return 0

    def _build(self, model, device, compute):
        factory = self.factory
        if factory is None:
            from faster_whisper import WhisperModel as factory
        m = factory(model, device=device, compute_type=compute, download_root=self.root)
        if device == "cuda":                       # a missing CUDA library only shows up on the first real inference: force it now
            import numpy as np
            segs, _ = m.transcribe(np.zeros(16000, dtype=np.float32), language="en", beam_size=1, without_timestamps=True)
            list(segs)
        return m

    def load(self):
        with self._lock:
            if self._m is not None:
                return self._m
            plans = []
            if self.device == "auto":
                if self._cuda_devices() > 0:
                    plans.append(("small.en" if self.model_name == "auto" else self.model_name, "cuda", "float16"))
                plans.append(("base.en" if self.model_name == "auto" else self.model_name, "cpu", self.compute))
            else:
                plans.append(("base.en" if self.model_name == "auto" else self.model_name, self.device, self.compute))
            err = None
            for model, device, compute in plans:
                try:
                    self._m = self._build(model, device, compute)
                    self.device_used, self.model_used = device, model
                    if err is not None:
                        self.fallback_reason = f"GPU not usable ({type(err).__name__}: {str(err)[:120]}): using the CPU"
                    return self._m
                except Exception as e:
                    err = e
                    if device == "cpu" or (plans and (model, device, compute) == plans[-1]):
                        raise
            raise err

    def warm(self):
        """Run one tiny inference so the first real utterance does not pay for lazy initialisation."""
        import numpy as np
        segs, _ = self.load().transcribe(np.zeros(8000, dtype=np.float32), language="en", beam_size=1, without_timestamps=True)
        list(segs)

    def transcribe(self, pcm16):
        import numpy as np
        a = array.array("h"); a.frombytes(pcm16[: len(pcm16) // 2 * 2])
        audio = np.frombuffer(a.tobytes(), dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = self.load().transcribe(audio, language="en", beam_size=1, vad_filter=False, condition_on_previous_text=False,
                                         without_timestamps=True, temperature=0.0,
                                         initial_prompt=VOCAB)
        parts = []
        for s in segs:
            if s.no_speech_prob > 0.6 or s.avg_logprob < -1.1:      # not credible speech
                continue
            parts.append(s.text.strip())
        text = " ".join(parts).strip()
        if looping(text):
            return ""
        return "" if text.lower().strip(" .!?,") in HALLUCINATIONS else text
