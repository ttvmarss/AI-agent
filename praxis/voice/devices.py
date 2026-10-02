"""Microphone and speaker. The real ones use sounddevice (PortAudio); test stand-ins feed and capture audio in memory."""
import array
import queue
import threading
import time

from .audio import RATE, to_mono16k


class Mic:
    streams = False                        # True for a real device that must deliver audio continuously (a silent one is unplugged)

    def start(self, on_chunk):             # on_chunk(pcm16 mono 16 kHz bytes), called from the audio thread
        raise NotImplementedError

    def stop(self):
        pass


class SdMic(Mic):
    streams = True
    """The default input device. Asks for 16 kHz mono; if the driver insists on its own rate, converts."""

    def __init__(self, device=None):
        self.device, self.stream, self.error = device, None, ""

    def start(self, on_chunk):
        import sounddevice as sd
        try:
            self.stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=int(RATE * 0.03),
                                            device=self.device, callback=lambda data, frames, t, status: on_chunk(bytes(data)))
        except Exception:
            info = sd.query_devices(self.device, "input")
            rate, ch = int(info["default_samplerate"]), 1
            self.stream = sd.RawInputStream(samplerate=rate, channels=ch, dtype="float32", blocksize=int(rate * 0.03),
                                            device=self.device,
                                            callback=lambda data, frames, t, status: on_chunk(to_mono16k(bytes(data), rate, ch, "float32")))
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None


class Speaker:
    def play(self, pcm, rate, stop):       # blocks until finished or `stop` (a threading.Event) is set
        raise NotImplementedError


class SdSpeaker(Speaker):
    def __init__(self, device=None):
        self.device = device

    def play(self, pcm, rate, stop):
        import sounddevice as sd
        a = array.array("h"); a.frombytes(pcm[: len(pcm) // 2 * 2])
        done = threading.Event()
        pos = [0]
        raw = a.tobytes()

        def cb(outdata, frames, t, status):
            n = frames * 2
            chunk = raw[pos[0]:pos[0] + n]
            outdata[:len(chunk)] = chunk
            if len(chunk) < n:
                outdata[len(chunk):] = b"\x00" * (n - len(chunk))
                raise sd.CallbackStop
            pos[0] += n
        with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", device=self.device, callback=cb,
                                finished_callback=done.set):
            while not done.wait(0.05):
                if stop.is_set():
                    break


# ---- stand-ins for tests and for running headless -------------------------------------------------------------------
class FakeMic(Mic):
    """Feed it audio with push(); it delivers 30 ms chunks to the loop exactly as a real mic would."""

    def __init__(self):
        self.cb, self.q = None, queue.Queue()
        self._t, self._run = None, False

    def start(self, on_chunk):
        self.cb, self._run = on_chunk, True
        self._t = threading.Thread(target=self._pump, daemon=True, name="fake-mic"); self._t.start()

    def push(self, pcm, realtime=False):
        step = int(RATE * 0.03) * 2
        for i in range(0, len(pcm), step):
            self.q.put((pcm[i:i + step].ljust(step, b"\x00"), realtime))

    def silence(self, seconds, realtime=False):
        self.push(b"\x00\x00" * int(RATE * seconds), realtime)

    def _pump(self):
        while self._run:
            try:
                chunk, rt = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            self.cb(chunk)
            if rt:
                time.sleep(0.03)

    def idle(self):
        return self.q.empty()

    def stop(self):
        self._run = False


class FakeSpeaker(Speaker):
    """Records what was 'played'. realtime=True takes as long as the audio would (for echo-guard tests)."""

    def __init__(self, realtime=False):
        self.played, self.realtime = [], realtime
        self.lock = threading.Lock()

    def play(self, pcm, rate, stop):
        with self.lock:
            self.played.append((pcm, rate))
        if self.realtime:
            end = time.time() + len(pcm) / 2 / rate
            while time.time() < end and not stop.is_set():
                time.sleep(0.01)
