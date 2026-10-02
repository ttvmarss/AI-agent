"""First-run provisioning: the speech models (one-time downloads into ~/.praxis/voice). Progress is reported so the core can show it."""
import os
import urllib.request

from .tts import voice_dir

PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{locale}/{name}/{quality}/{voice}.{ext}"


# Voices that are not in the main Piper collection. "jarvis" is a community British voice in the manner of the film assistant
# (jgkawell/jarvis on Hugging Face); the rest come from rhasspy/piper-voices.
CUSTOM = {
    "jarvis-high": "https://huggingface.co/jgkawell/jarvis/resolve/main/en/en_GB/jarvis/high/jarvis-high",
    "jarvis-medium": "https://huggingface.co/jgkawell/jarvis/resolve/main/en/en_GB/jarvis/medium/jarvis-medium",
}


def piper_files(voice):
    """en_GB-alan-medium -> the two URLs to fetch."""
    if voice in CUSTOM:
        return [(voice + ".onnx", CUSTOM[voice] + ".onnx"), (voice + ".onnx.json", CUSTOM[voice] + ".onnx.json")]
    locale, name, quality = voice.split("-")
    lang = locale.split("_")[0]
    fmt = lambda ext: PIPER_URL.format(lang=lang, locale=locale, name=name, quality=quality, voice=voice, ext=ext)
    return [(voice + ".onnx", fmt("onnx")), (voice + ".onnx.json", fmt("onnx.json"))]


def ensure_piper(voice, root=None, progress=None):
    root = root or voice_dir()
    os.makedirs(root, exist_ok=True)
    for fname, url in piper_files(voice):
        dest = os.path.join(root, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            continue
        tmp = dest + ".part"
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                b = r.read(1 << 18)
                if not b:
                    break
                f.write(b); got += len(b)
                if progress:
                    progress(f"Downloading the voice ({fname})", got, total)
        if total and got != total:
            os.unlink(tmp)
            raise OSError(f"download of {fname} was cut short ({got} of {total} bytes)")
        os.replace(tmp, dest)
    return os.path.join(root, voice + ".onnx")
