"""The always-on voice loop: microphone -> voice-activity detection -> speech recognition -> conductor, and conductor ->
speech synthesis -> speaker. Half duplex: while PRAXIS speaks (and a moment after) the microphone is deaf, so it never hears
itself and never acts on its own words."""
import queue
import threading
import time

from . import audio
from .conductor import Conductor

TAIL_S = 0.55          # stay deaf this long after speech ends (room echo)


class VoiceLoop:
    def __init__(self, actions, recognizer, mic, speaker, voice, wake_word="praxis", speak=True, attentive_s=10.0,
                 approval_s=60.0, segmenter=None, log=None):
        self.recognizer, self.mic, self.speaker, self.voice, self.speak_on = recognizer, mic, speaker, voice, speak
        self.log = log or (lambda *_: None)
        self.seg = segmenter or audio.Segmenter()
        self.conductor = Conductor(actions, self.say, wake_word=wake_word, attentive_s=attentive_s, approval_s=approval_s, log=self.log)
        self.muted, self.speaking, self.thinking, self.deaf_until = False, False, False, 0.0
        self.level, self.speak_level, self._env, self._env_t0 = 0.0, 0.0, [], 0.0
        self.transcripts = []                 # (time, text, what it did): the log you read when something is odd
        self.last_error = ""
        self._inq, self._sttq, self._ttsq = queue.Queue(), queue.Queue(maxsize=3), []
        self._ttscv = threading.Condition()
        self._stop_speaking, self._closing = threading.Event(), False
        self._threads = []

    # ---- lifecycle ------------------------------------------------------------------------------------------------------
    def start(self):
        for name, fn in (("voice-listen", self._listen), ("voice-stt", self._stt), ("voice-tts", self._tts), ("voice-tick", self._ticker)):
            t = threading.Thread(target=fn, daemon=True, name=name); t.start(); self._threads.append(t)
        self.mic.start(self._inq.put)

    def close(self):
        self._closing = True
        self._stop_speaking.set()
        self.mic.stop()
        with self._ttscv:
            self._ttscv.notify_all()

    def set_muted(self, muted):
        self.muted = bool(muted)
        self.seg.reset()

    # ---- state for the screen ---------------------------------------------------------------------------------------------
    @property
    def state(self):
        if self.muted:
            return "muted"
        if self.speaking:
            return "speaking"
        if self.thinking:
            return "thinking"
        return "hearing" if self.seg.in_speech else "listening"

    def snapshot(self):
        if self.speaking and self._env:
            i = int((time.monotonic() - self._env_t0) * 30)
            self.speak_level = self._env[i] if i < len(self._env) else 0.0
        else:
            self.speak_level = 0.0
        return {"state": self.state, "level": 0.0 if self.muted else self.level, "speak_level": self.speak_level,
                "attentive": self.conductor.clock() < self.conductor.attentive_until}

    # ---- speaking -----------------------------------------------------------------------------------------------------------
    def say(self, text, urgent=False):
        if not self.speak_on or not text:
            return
        with self._ttscv:
            if urgent:
                self._ttsq.clear()                               # a final report outranks queued commentary
            self._ttsq.append(text)
            self._ttscv.notify()

    def shut_up(self):
        self._stop_speaking.set()

    def _tts(self):
        while not self._closing:
            with self._ttscv:
                while not self._ttsq and not self._closing:
                    self._ttscv.wait(0.2)
                if self._closing:
                    return
                text = self._ttsq.pop(0)
            try:
                pcm, rate = self.voice.synth(text)
            except Exception as e:
                self.last_error = f"speech synthesis failed: {type(e).__name__}: {e}"
                self.log("tts-error", self.last_error)
                continue
            self._stop_speaking.clear()
            self._env, self._env_t0 = audio.envelope(pcm, rate), time.monotonic()
            self.speaking = True
            self.seg.reset()
            try:
                self.speaker.play(pcm, rate, self._stop_speaking)
            except Exception as e:
                self.last_error = f"playback failed: {type(e).__name__}: {e}"
                self.log("play-error", self.last_error)
            finally:
                self.speaking, self._env = False, []
                self.deaf_until = time.monotonic() + TAIL_S
                self.seg.reset()

    def _ticker(self):
        while not self._closing:
            try:
                self.conductor.tick()
            except Exception as e:
                self.last_error = f"voice tick failed: {type(e).__name__}: {e}"
            time.sleep(0.25)

    # ---- listening ----------------------------------------------------------------------------------------------------------
    def _listen(self):
        while not self._closing:
            try:
                chunk = self._inq.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.muted or self.speaking or time.monotonic() < self.deaf_until:
                self.level = 0.0
                continue                                           # deaf: drop it
            for utt in self.seg.feed(chunk):
                try:
                    self._sttq.put_nowait(utt)
                except queue.Full:
                    try:
                        self._sttq.get_nowait(); self._sttq.put_nowait(utt)   # keep the newest
                    except queue.Empty:
                        pass
            self.level = self.seg.level

    def _stt(self):
        while not self._closing:
            try:
                pcm = self._sttq.get(timeout=0.1)
            except queue.Empty:
                continue
            self.thinking = True
            try:
                text = self.recognizer.transcribe(pcm)
            except Exception as e:
                self.last_error = f"speech recognition failed: {type(e).__name__}: {e}"
                self.log("stt-error", self.last_error)
                self.thinking = False
                continue
            try:
                what = self.conductor.hear(text) if text else "ignored: nothing credible"
            except Exception as e:                                  # a bug here must never kill listening
                what = f"error: {type(e).__name__}: {e}"
                self.last_error = what
            finally:
                self.thinking = False
            self.transcripts = (self.transcripts + [(time.time(), text, what)])[-50:]
            self.log("transcript", text, what)
