"""Live dictation that types into whatever window has focus as you speak.

Tap the hotkey (default Right Ctrl) to start listening, tap again to stop. Audio goes only
to your own Whisper server (STT_URL). Whisper is not a streaming model, so the current
phrase is re-transcribed every INTERIM_S seconds and a word is typed once two passes in a
row agree on it (punctuation included), which means nothing typed ever has to be erased.
A pause ends the phrase. Hindi phrases (Devanagari) are romanized into Hinglish by your
own LLM (LLM_URL) and typed when the phrase ends.
"""
import io
import os
import queue
import re
import threading
import time
import wave
from pathlib import Path

import numpy as np
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
SPEECH_RMS = float(os.environ.get("SPEECH_RMS", "0.015"))  # room noise measured ~0.003
RATE = 16000
BLOCK = 1600          # 0.1 s of audio per mic callback
INTERIM_S = 0.7       # re-transcribe the phrase this often while speaking
PAUSE_S = 0.8         # this much silence ends a phrase
MAX_PHRASE_S = 20     # force a phrase end so re-transcription stays cheap
TAP_S = 0.5           # a press shorter than this (with no other key) toggles listening

ROMANIZE_PROMPT = (
    "Transliterate the user's text into Roman-script Hinglish, the way people type it in chat. "
    "Keep English words in English spelling. Do not translate, add, or remove anything. "
    "Reply with the text only."
)
# Whisper already turns spoken "comma" and "question mark" into symbols; these it leaves as words.
COMMANDS = [
    (re.compile(r"\s*\bnew paragraph\b[.,]?\s*", re.I), "\n\n"),
    (re.compile(r"\s*\bnew line\b[.,]?\s*", re.I), "\n"),
    (re.compile(r"[.,]?\s*\bfull stop\b[.,]?", re.I), "."),
]
COMMAND_STARTS = {"new", "full"}  # hold these back until the next word shows if it is a command


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


def is_devanagari(text: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in text)


def finalize(text: str) -> str:
    """Romanize Devanagari. Check the script, not Whisper's label: it sometimes says "ur" or "mr"."""
    if not is_devanagari(text):
        return text
    try:
        return romanize(text)
    except requests.RequestException:
        return text  # LLM down: Devanagari beats losing what was said


def agreed(a: list[str], b: list[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


class Live:
    """Turns a stream of 0.1 s mic blocks into typed text. emit(text) does the typing."""

    def __init__(self, emit):
        self.emit = emit
        self.last = ""  # last character typed this session ("" = nothing yet)
        self._new_phrase()

    def _new_phrase(self):
        self.audio: list[np.ndarray] = []
        self.voiced = False
        self.silent_s = self.since_pass = 0.0
        self.prev: list[str] = []
        self.done = 0  # words of this phrase already typed

    def feed(self, block: np.ndarray):
        self.audio.append(block)
        dur = len(block) / RATE
        rms = float(np.sqrt(np.mean((block.astype(np.float32) / 32768) ** 2)))
        if rms >= SPEECH_RMS:
            self.voiced, self.silent_s = True, 0.0
        else:
            self.silent_s += dur
        if not self.voiced:
            self.audio = self.audio[-3:]  # keep a 0.3 s lead-in, drop the silence before it
            return
        self.since_pass += dur
        if self.silent_s >= PAUSE_S or len(self.audio) * dur >= MAX_PHRASE_S:
            self.finish()
        elif self.since_pass >= INTERIM_S:
            self._interim()

    def _pass(self) -> str:
        self.since_pass = 0.0
        return transcribe(to_wav(np.concatenate(self.audio)))[0]

    def _interim(self):
        words = self._pass().split()
        if is_devanagari(" ".join(words)):
            return  # Hindi is typed whole at the phrase end, after romanizing
        n = agreed(self.prev, words)
        if n > self.done and words[n - 1].lower() in COMMAND_STARTS:
            n -= 1
        if n > self.done:
            self._type(words[self.done:n])
            self.done = n
        self.prev = words

    def finish(self):
        """End the phrase: type whatever the final pass has beyond what is already typed."""
        if self.voiced:
            words = finalize(self._pass()).split()
            self._type(words[self.done:])
        self._new_phrase()

    def _type(self, words: list[str]):
        if not words:
            return
        text = " ".join(words)
        for pattern, repl in COMMANDS:
            text = pattern.sub(repl, text)
        if text.startswith(".") and self.last in ".?!":
            text = text[1:]  # Whisper already ended the sentence before the spoken "full stop"
        if not text:
            return
        if self.last in ("", "\n", ".", "?", "!"):
            text = text[0].upper() + text[1:]  # each phrase is transcribed alone, so fix case here
        if self.last and self.last != "\n" and text[0] not in "\n.,?!":
            text = " " + text
        self.emit(text)
        self.last = text[-1]


kb = keyboard.Controller()


def type_text(text: str):
    """Synthetic typing. New lines go in as Shift+Enter so chat apps do not send the message."""
    for i, part in enumerate(text.split("\n")):
        if i:
            with kb.pressed(keyboard.Key.shift):
                kb.tap(keyboard.Key.enter)
        if part:
            kb.type(part)


def dot(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=color)
    return img


IDLE, LISTENING = dot("#8a8a8a"), dot("#e0352b")


class App:
    def __init__(self, icon: pystray.Icon):
        self.icon = icon
        self.stream = None
        self.blocks: queue.Queue = queue.Queue()
        self.pressed_at = None
        self.combo = False

    # Hotkey: a clean tap toggles. Holding it or using it in a shortcut (Ctrl+C) does nothing.
    def on_press(self, key):
        if key == HOTKEY:
            if self.pressed_at is None:
                self.pressed_at, self.combo = time.monotonic(), False
        elif self.pressed_at is not None:
            self.combo = True

    def on_release(self, key):
        if key != HOTKEY or self.pressed_at is None:
            return
        tap = not self.combo and time.monotonic() - self.pressed_at < TAP_S
        self.pressed_at = None
        if tap:
            self.stop() if self.stream else self.start()

    def start(self):
        self.blocks = queue.Queue()
        threading.Thread(target=self._worker, args=(self.blocks,), daemon=True).start()
        q = self.blocks
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK,
                                     callback=lambda d, *_: q.put(d[:, 0].copy()))
        self.stream.start()
        self.icon.icon = LISTENING

    def stop(self):
        self.stream.stop()
        self.stream.close()
        self.stream = None
        self.blocks.put(None)  # the worker finishes the last phrase, then exits
        self.icon.icon = IDLE

    def _worker(self, blocks: queue.Queue):
        # Transcription runs here, never in the audio callback, so the mic never drops blocks.
        live = Live(type_text)
        try:
            while (block := blocks.get()) is not None:
                live.feed(block)
            live.finish()
        except Exception as e:
            self.icon.notify(f"{type(e).__name__}: {e}", "Dictation failed")
            if self.stream:
                self.stop()


def main():
    icon = pystray.Icon("dictation", IDLE, f"Dictation (tap {HOTKEY.name} to start/stop)",
                        menu=pystray.Menu(pystray.MenuItem("Quit", lambda i: i.stop())))
    app = App(icon)
    listener = keyboard.Listener(on_press=app.on_press, on_release=app.on_release)
    listener.start()
    icon.run()
    listener.stop()


if __name__ == "__main__":
    main()
