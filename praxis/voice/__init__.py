"""Hands-free voice for PRAXIS: talk to it, it talks back. Optional (pip install faster-whisper piper-tts sounddevice).

The logic (VAD, wake word, intents, narration, the conductor) is pure Python and fully tested; the engines (speech
recognition, speech synthesis, microphone, speaker) sit behind small interfaces so each can be swapped or faked.
Safety rules that hold whatever the engines hear: a wake word is required (except STOP and approval answers, which are
safe to over-trigger); risky approvals need the literal word "approve"; silence means DENY; the app never hears itself.
"""
