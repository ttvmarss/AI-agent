"""Speech recognition behind one tiny interface. The real engine is faster-whisper running locally on the CPU."""
import array
import threading

# Whisper invents these on silence or noise. They are never a command.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "subtitles by the amara.org community",
                  "thanks", "the end", "so", "oh", "uh", "um", "hmm"}


class Recognizer:
    def transcribe(self, pcm16):          # 16 kHz mono int16 bytes -> text ("" if nothing credible was said)
        raise NotImplementedError


class FakeRecognizer(Recognizer):
    """Scripted, for tests: returns the queued transcripts in order."""
    def __init__(self, texts=()):
        self.texts, self.heard = list(texts), []

    def transcribe(self, pcm16):
        self.heard.append(len(pcm16))
        return self.texts.pop(0) if self.texts else ""


class WhisperRecognizer(Recognizer):
    def __init__(self, model="base.en", root=None, device="cpu", compute_type="int8"):
        self.model_name, self.root, self.device, self.compute = model, root, device, compute_type
        self._m, self._lock = None, threading.Lock()

    def load(self):
        with self._lock:
            if self._m is None:
                from faster_whisper import WhisperModel
                self._m = WhisperModel(self.model_name, device=self.device, compute_type=self.compute, download_root=self.root)
        return self._m

    def transcribe(self, pcm16):
        import numpy as np
        a = array.array("h"); a.frombytes(pcm16[: len(pcm16) // 2 * 2])
        audio = np.frombuffer(a.tobytes(), dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = self.load().transcribe(audio, language="en", beam_size=1, vad_filter=False, condition_on_previous_text=False,
                                         without_timestamps=True, temperature=0.0)
        parts = []
        for s in segs:
            if s.no_speech_prob > 0.6 or s.avg_logprob < -1.1:      # not credible speech
                continue
            parts.append(s.text.strip())
        text = " ".join(parts).strip()
        return "" if text.lower().strip(" .!?,") in HALLUCINATIONS else text
