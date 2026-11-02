"""Hold-to-talk dictation that types into whatever window has focus.

Hold the hotkey (default Right Ctrl), speak, release. The clip goes only to your own
Whisper server (STT_URL) and the text is pasted at the cursor. Hindi comes back from
Whisper in Devanagari; finalize() romanizes it with your own LLM (LLM_URL).
"""
import io
import os
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pyperclip
import pystray
import requests
import sounddevice as sd
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from pynput import keyboard

load_dotenv(Path(__file__).with_name(".env"))
STT_URL = os.environ["STT_URL"]
STT_KEY = os.environ["STT_KEY"]
LLM_URL = os.environ["LLM_URL"]
LLM_MODEL = os.environ.get("LLM_MODEL", "model")
HOTKEY = getattr(keyboard.Key, os.environ.get("HOTKEY", "ctrl_r"))
RATE = 16000
MIN_SECONDS = 0.4  # shorter holds are an ordinary key tap, not dictation

ROMANIZE_PROMPT = (
    "Transliterate the user's text into Roman-script Hinglish, the way people type it in chat. "
    "Keep English words in English spelling. Do not translate, add, or remove anything. "
    "Reply with the text only."
)


def to_wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def transcribe(wav: bytes) -> tuple[str, str]:
    r = requests.post(STT_URL, files={"file": ("clip.wav", wav, "audio/wav")},
                      headers={"Authorization": f"Bearer {STT_KEY}"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j["text"].strip(), j["language"]


def romanize(text: str) -> str:
    """Devanagari -> Roman Hinglish via the OpenAI-compatible LLM at LLM_URL."""
    r = requests.post(LLM_URL, timeout=30, json={
        "model": LLM_MODEL, "temperature": 0, "max_tokens": 1000,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": ROMANIZE_PROMPT}, {"role": "user", "content": text}],
    })
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def finalize(text: str, language: str) -> str:
    """Turn Whisper's raw output into what gets typed. language is Whisper's guess ("en", "hi", ...)."""
    # Check the script, not the language label: Whisper sometimes tags Devanagari output as "ur" or "mr".
    if not any("ऀ" <= c <= "ॿ" for c in text):
        return text
    try:
        return romanize(text)
    except requests.RequestException:
        return text  # LLM down: Devanagari beats losing what was said


def paste(text: str) -> None:
    """Paste via the clipboard (more reliable than synthetic typing), then put the old text back."""
    old = pyperclip.paste()
    pyperclip.copy(text)
    kb = keyboard.Controller()
    with kb.pressed(keyboard.Key.ctrl):
        kb.tap("v")
    time.sleep(0.2)  # let the target app read the clipboard before we restore it
    pyperclip.copy(old)


def dot(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=color)
    return img


IDLE, REC, BUSY = dot("#8a8a8a"), dot("#e0352b"), dot("#e6a817")


class Dictation:
    def __init__(self, icon: pystray.Icon):
        self.icon = icon
        self.stream = None
        self.frames: list[np.ndarray] = []
        self.started = 0.0
        self.lock = threading.Lock()  # keeps pastes in the order they were spoken

    def on_press(self, key):
        if key == HOTKEY:
            if self.stream is None:  # ignore key auto-repeat while held
                self.frames, self.started = [], time.monotonic()
                self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                             callback=lambda d, *_: self.frames.append(d.copy()))
                self.stream.start()
                self.icon.icon = REC
        elif self.stream is not None:  # hotkey used as a modifier (Ctrl+C etc.): not dictation
            self._stop()

    def on_release(self, key):
        if key != HOTKEY or self.stream is None:
            return
        held = time.monotonic() - self.started
        frames = self._stop()
        if held >= MIN_SECONDS and frames:
            threading.Thread(target=self._process, args=(np.concatenate(frames),), daemon=True).start()

    def _stop(self) -> list[np.ndarray]:
        self.stream.stop()
        self.stream.close()
        self.stream = None
        self.icon.icon = IDLE
        return self.frames

    def _process(self, samples: np.ndarray):
        with self.lock:
            self.icon.icon = BUSY
            try:
                text, lang = transcribe(to_wav(samples))
                text = finalize(text, lang)
                if text:
                    paste(text + " ")
            except Exception as e:
                self.icon.notify(f"{type(e).__name__}: {e}", "Dictation failed")
            finally:
                self.icon.icon = IDLE


def main():
    icon = pystray.Icon("dictation", IDLE, f"Dictation (hold {HOTKEY.name})",
                        menu=pystray.Menu(pystray.MenuItem("Quit", lambda i: i.stop())))
    d = Dictation(icon)
    listener = keyboard.Listener(on_press=d.on_press, on_release=d.on_release)
    listener.start()
    icon.run()
    listener.stop()


if __name__ == "__main__":
    main()
