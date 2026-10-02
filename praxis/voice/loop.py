"""The always-on voice loop: microphone -> voice-activity detection -> speech recognition -> conductor, and conductor ->
speech synthesis -> speaker. Half duplex: while PRAXIS speaks (and a moment after) the microphone is deaf, so it never hears
itself and never acts on its own words."""
import queue
import threading
import time

from . import audio, tts
from .chat import Chat
from .conductor import Conductor

MAX_SPOKEN = 420          # characters of one spoken sentence
MAX_QUEUED = 5           # sentences waiting to be spoken
TAIL_S = 0.55          # stay deaf this long after speech ends (room echo)


class VoiceLoop:
    def __init__(self, actions, recognizer, mic, speaker, voice, wake_word="praxis", speak=True, attentive_s=15.0,
                 approval_s=60.0, segmenter=None, log=None, chat=True, wake_required=True):
        self.recognizer, self.mic, self.speaker, self.voice, self.speak_on = recognizer, mic, speaker, voice, speak
        self.log = log or (lambda *_: None)
        self.seg = segmenter or audio.Segmenter()
        brain = Chat(actions.chat) if chat and getattr(actions, "chat", None) else None
        self.conductor = Conductor(actions, self.say, wake_word=wake_word, attentive_s=attentive_s, approval_s=approval_s, log=self.log, chat=brain,
                                   wake_required=wake_required)
        self.muted, self.speaking, self.thinking, self.deaf_until = False, False, False, 0.0
        self.level, self.speak_level, self._env, self._env_t0 = 0.0, 0.0, [], 0.0
        self.transcripts = []                 # (time, text, what it did): the log you read when something is odd
        self.last_error, self.unspoken = "", ""
        self.last_chunk, self.mic_ok, self._mic_retry = time.monotonic(), True, 0.0
        self._inq, self._sttq, self._ttsq = queue.Queue(), queue.Queue(maxsize=3), []
        self._ttscv = threading.Condition()
        self._stop_speaking, self._closing = threading.Event(), False
        self._threads = []
        self._executor = None
        self.engine, self.voice_note = "", ""

    # ---- lifecycle ------------------------------------------------------------------------------------------------------
    def start(self):
        for name, fn in (("voice-listen", self._listen), ("voice-stt", self._stt), ("voice-tts", self._tts), ("voice-tick", self._ticker)):
            t = threading.Thread(target=fn, daemon=True, name=name); t.start(); self._threads.append(t)
        self.mic.start(self._on_chunk)

    def close(self):
        self._closing = True
        self._stop_speaking.set()
        self.mic.stop()
        with self._ttscv:
            self._ttscv.notify_all()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _on_chunk(self, chunk):
        self.last_chunk = time.monotonic()
        self._inq.put(chunk)

    def _watch_mic(self):
        """A real microphone delivers audio constantly. If it goes quiet (headset unplugged, driver reset) say so and keep
        trying to bring it back, rather than sitting on 'listening' while deaf."""
        if not self.mic.streams or self.muted:
            return
        now = time.monotonic()
        if now - self.last_chunk < 3.0:
            if not self.mic_ok:
                self.mic_ok, self.last_error = True, ""
            return
        if self.mic_ok:
            self.mic_ok = False
            self.last_error = "the microphone stopped delivering audio"
            self.log("mic-lost", self.last_error)
        if now >= self._mic_retry:
            self._mic_retry = now + 5.0
            try:
                self.mic.stop(); self.mic.start(self._on_chunk)
            except Exception as e:
                self.last_error = f"the microphone is unavailable: {type(e).__name__}: {e}"

    def set_muted(self, muted):
        self.muted = bool(muted)
        self.seg.reset()

    # ---- state for the screen ---------------------------------------------------------------------------------------------
    @property
    def state(self):
        if self.muted:
            return "muted"
        if not self.mic_ok:
            return "offline"
        if self.speaking:
            return "speaking"
        if self.thinking or self.conductor.chatting:
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
        if not self.speak_on or not isinstance(text, str) or not text.strip():
            return
        text = text.strip()
        if len(text) > MAX_SPOKEN:                               # nobody wants a four-minute monologue; cut at a word
            text = text[:MAX_SPOKEN].rsplit(" ", 1)[0] + "..."
        with self._ttscv:
            if urgent:
                self._ttsq.clear()                               # a final report outranks queued commentary
            self._ttsq.append(text)
            del self._ttsq[:-MAX_QUEUED]                         # a backlog is stale news: keep only the newest few
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
            self._speak(text)

    def _speak(self, text):
        """Say one utterance sentence by sentence: the next sentence is being synthesised while the current one plays, so speech
        starts after the first sentence is made, not the whole answer."""
        sentences = tts.split_sentences(tts.speakable(text))
        if not sentences or not sentences[0]:
            return
        pool = self._pool()
        nxt = pool.submit(self.voice.synth, sentences[0])
        try:
            for i in range(len(sentences)):
                try:
                    pcm, rate = nxt.result(timeout=60)
                except Exception as e:
                    self.last_error = f"speech synthesis failed: {type(e).__name__}: {e}"
                    self.unspoken = text                  # the screen shows what it could not say aloud
                    self.log("tts-error", self.last_error)
                    return
                nxt = pool.submit(self.voice.synth, sentences[i + 1]) if i + 1 < len(sentences) else None
                if self._stop_speaking.is_set() and i:
                    return
                self._stop_speaking.clear()
                self._env, self._env_t0 = audio.envelope(pcm, rate), time.monotonic()
                self.speaking = True
                self.seg.reset()
                try:
                    self.speaker.play(pcm, rate, self._stop_speaking)
                except Exception as e:
                    self.last_error = f"playback failed: {type(e).__name__}: {e}"
                    self.unspoken = text
                    self.log("play-error", self.last_error)
                    return
                finally:
                    self.speaking, self._env = False, []
                    self.deaf_until = time.monotonic() + TAIL_S
                    self.seg.reset()
                if self._closing:
                    return
        finally:
            if nxt is not None:
                nxt.cancel()

    def _pool(self):
        if self._executor is None:
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-synth")
        return self._executor

    def _ticker(self):
        while not self._closing:
            try:
                self.conductor.tick()
            except Exception as e:
                self.last_error = f"voice tick failed: {type(e).__name__}: {e}"
            try:
                self._watch_mic()
            except Exception as e:
                self.last_error = f"microphone watchdog failed: {type(e).__name__}: {e}"
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
