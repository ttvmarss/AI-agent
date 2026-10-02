"""`praxis voice`: checks every link of the voice chain on THIS machine and says which one is the problem: audio devices, the voice
(and how fast it is made), the microphone level, what the recogniser hears, and how fast a model answers a chat question."""
import os
import time

from ..voice import audio, tts
from .voice_setup import choose_voice, log_line


def run(stack, vcfg, out=print):
    ok = True
    out("PRAXIS voice check\n")
    try:
        import sounddevice as sd
    except Exception as e:
        out(f"[FAIL] audio library: {type(e).__name__}: {e}\n       fix: py -3 -m pip install --user sounddevice")
        return 1
    try:
        din, dout = sd.default.device
        devs = sd.query_devices()
        out(f"[ok]   input : {devs[din]['name'] if din is not None and din >= 0 else 'NONE'}")
        out(f"[ok]   output: {devs[dout]['name'] if dout is not None and dout >= 0 else 'NONE'}")
    except Exception as e:
        out(f"[FAIL] cannot read audio devices: {e}"); ok = False

    out("\nvoice")
    name = vcfg.get("voice", "jarvis-high")
    voice, note = choose_voice(name, lambda t, f=None: out("       " + t))
    if voice is None:
        out("[FAIL] no voice at all (install piper-tts, or use a system with a built-in voice)"); ok = False
    else:
        t0 = time.time(); pcm, rate = voice.synth(tts.speakable("Good evening. All systems are online, and I can hear you."))
        dt = time.time() - t0
        out(f"[ok]   engine: {voice.name}   made {len(pcm) / 2 / rate:.1f} s of speech in {dt:.2f} s" + (f"\n[warn] {note}" if note else ""))
        if not voice.name.startswith("piper"):
            out("[warn] this is the plain system voice, which is why it sounds robotic. Fix the problem above to get the neural voice.")
        try:
            from ..voice.devices import SdSpeaker
            import threading
            out("       speaking now: you should hear a sentence...")
            SdSpeaker().play(pcm, rate, threading.Event())
            out("[ok]   playback finished")
        except Exception as e:
            out(f"[FAIL] playback: {type(e).__name__}: {e}"); ok = False

    out("\nmicrophone")
    try:
        import array
        import queue
        from ..voice.devices import SdMic
        q = queue.Queue(); mic = SdMic(); mic.start(q.put)
        out("       say: \"Praxis, what time is it?\"  (recording 4 seconds)")
        buf, end = b"", time.time() + 4
        while time.time() < end:
            try:
                buf += q.get(timeout=0.2)
            except queue.Empty:
                pass
        mic.stop()
        a = array.array("h"); a.frombytes(buf[: len(buf) // 2 * 2])
        peak = max((abs(x) for x in a), default=0) / 32768.0
        out(f"[{'ok' if peak > 0.05 else 'FAIL'}]   heard a peak level of {peak:.2f}" + ("" if peak > 0.05 else "   (too quiet: check the microphone, its privacy permission and its volume)"))
        if peak <= 0.05:
            ok = False
        else:
            from ..voice.stt import WhisperRecognizer
            rec = WhisperRecognizer(vcfg.get("stt_model", "base.en"), root=os.path.join(tts.voice_dir(), "whisper"))
            t0 = time.time(); heard = rec.transcribe(buf)
            out(f"[ok]   recogniser heard: {heard!r}   ({time.time() - t0:.1f} s)")
    except Exception as e:
        out(f"[FAIL] microphone: {type(e).__name__}: {e}"); ok = False

    out("\nconversation")
    try:
        t0 = time.time()
        reply = stack.router.call("chat", [{"role": "system", "content": "Answer in one short spoken sentence."},
                                           {"role": "user", "content": "Say hello and tell me you are ready."}], "project")
        out(f"[ok]   {stack.router.last_provider} answered in {time.time() - t0:.1f} s: {reply.strip()[:100]!r}")
        if time.time() - t0 > 6:
            out("[warn] that is slow for a conversation. Fastest options: a free Groq key (praxis keys set groq) or a small local model in Ollama.")
    except Exception as e:
        out(f"[FAIL] no model could answer: {e}"); ok = False
    log_line("voice check " + ("passed" if ok else "found problems"))
    out("\n" + ("Everything works." if ok else "Something above needs fixing; the first [FAIL] is the one to fix."))
    return 0 if ok else 1
