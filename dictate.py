"""Live dictation that types into whatever window has focus as you speak.

Press the shortcut (default Win+Space, changeable from the tray) to start listening, again to stop.
It also stops by itself after a silence longer than your usual pauses (AUTO_STOP_S). Audio goes only
to your own Whisper server (STT_URL). Whisper is not a streaming model, so the current
phrase is re-transcribed every INTERIM_S seconds and a word is typed once two passes in a
row agree on it (punctuation included), which means nothing typed ever has to be erased.
A pause ends the phrase. Hindi phrases (Devanagari) are romanized into Hinglish by your
own LLM (LLM_URL) and typed when the phrase ends. On start it updates itself from git.
"""
import io
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import wave
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv  # pure Python, so loading it before the update locks nothing

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def self_update() -> None:
    """Fast-forward to the latest main and restart on the new code.

    Runs before the compiled packages (numpy, sounddevice) load, because Windows will not let
    uv sync replace files a running process has open. Offline, local edits, or git/uv missing:
    start the current version. If uv sync fails, go back to the previous commit.
    """
    def run(*cmd, timeout=20):
        return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        before = run("git", "rev-parse", "HEAD").stdout.strip()
        if run("git", "pull", "--ff-only", "-q").returncode != 0:
            return
        if run("git", "rev-parse", "HEAD").stdout.strip() == before:
            return
        if run("uv", "sync", "--locked", "-q", timeout=300).returncode != 0:  # never rewrites uv.lock
            run("git", "reset", "-q", "--keep", before)
            return
    except (OSError, subprocess.TimeoutExpired):
        return
    # os.execv mangles paths with spaces on Windows, so start a fresh process and exit this one.
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], cwd=HERE)
    sys.exit(0)


if __name__ == "__main__":
    if os.environ.get("AUTO_UPDATE", "1") != "0":
        self_update()
    # One copy only: two would each type every word. The OS frees the mutex when we exit.
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "local-dictation-single-instance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)

import numpy as np  # noqa: E402  (after the update on purpose, see self_update)
import pystray  # noqa: E402
import requests  # noqa: E402
import sounddevice as sd  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pynput import keyboard  # noqa: E402

from hotkey import GlobalHotkey, Hotkey  # noqa: E402

# Events and mic levels only, never what was said.
LOG = logging.getLogger("dictation")
LOG.setLevel(logging.INFO)
_log_file = RotatingFileHandler(HERE / "dictation.log", maxBytes=200_000, backupCount=1, encoding="utf-8")
_log_file.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
LOG.addHandler(_log_file)

STT_URL = os.environ["STT_URL"]
STT_KEY = os.environ["STT_KEY"]
LLM_URL = os.environ["LLM_URL"]
LLM_MODEL = os.environ.get("LLM_MODEL", "model")
LLM_KEY = os.environ.get("LLM_KEY", "")  # only hosted APIs need one
DEFAULT_HOTKEY = "win+space"
SPEECH_RMS = float(os.environ.get("SPEECH_RMS", "0.015"))  # room noise measured ~0.003
RATE = 16000
BLOCK = 1600          # 0.1 s of audio per mic callback
INTERIM_S = 0.7       # re-transcribe the phrase this often while speaking
PAUSE_S = 0.8         # this much silence ends a phrase
MAX_PHRASE_S = 20     # force a phrase end so re-transcription stays cheap
AUTO_STOP_S = float(os.environ.get("AUTO_STOP_S", "6"))  # silence that ends the session, 0 = never

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
    body = {
        "model": LLM_MODEL, "temperature": 0, "max_tokens": 1000,
        "messages": [{"role": "system", "content": ROMANIZE_PROMPT}, {"role": "user", "content": text}],
    }
    headers = {}
    if LLM_KEY:
        headers["Authorization"] = f"Bearer {LLM_KEY}"
    else:  # self-hosted vLLM: turn off thinking; hosted APIs may reject this unknown field
        body["chat_template_kwargs"] = {"enable_thinking": False}
    r = requests.post(LLM_URL, timeout=30, json=body, headers=headers)
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
        self.peak = 0.0  # loudest block this session, reported when no speech was heard
        self.heard = False
        self.idle_s = 0.0  # silence since the last speech block, across phrases
        self.longest_pause_s = 0.0  # longest gap between two bits of speech this session
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
        self.peak = max(self.peak, rms)
        if rms >= SPEECH_RMS:
            if self.heard:
                self.longest_pause_s = max(self.longest_pause_s, self.idle_s)
            self.voiced, self.heard, self.silent_s, self.idle_s = True, True, 0.0, 0.0
        else:
            self.silent_s += dur
            self.idle_s += dur
        if not self.voiced:
            self.audio = self.audio[-3:]  # keep a 0.3 s lead-in, drop the silence before it
            return
        self.since_pass += dur
        if self.silent_s >= PAUSE_S or len(self.audio) * dur >= MAX_PHRASE_S:
            self.finish()
        elif self.since_pass >= INTERIM_S:
            self._interim()

    def done_talking(self) -> bool:
        return AUTO_STOP_S > 0 and self.idle_s + 1e-6 >= self.stop_after_s()  # 0.1 s steps drift below

    def stop_after_s(self) -> float:
        """Seconds of silence after which the session ends by itself.
        Inputs: AUTO_STOP_S (the user's setting), self.heard (spoken yet this session?),
        self.longest_pause_s (longest pause between speech so far)."""
        if not self.heard:
            return max(AUTO_STOP_S, 8.0)  # give people a moment to start
        # Someone who pauses long mid-thought gets more slack, capped so it cannot grow forever.
        return max(AUTO_STOP_S, min(self.longest_pause_s * 1.5, 15.0))

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


def save_hotkey(spec: str):
    """Write HOTKEY into .env, replacing the old line, so the choice survives restarts."""
    env = HERE / ".env"
    lines = [ln for ln in env.read_text(encoding="utf-8").splitlines() if not ln.startswith("HOTKEY=")]
    env.write_text("\n".join([*lines, f"HOTKEY={spec}"]) + "\n", encoding="utf-8")


class App:
    def __init__(self, icon: pystray.Icon, hotkey: Hotkey):
        self.icon = icon
        self.stream = None
        self.blocks: queue.Queue = queue.Queue()
        self.lock = threading.Lock()  # start/stop come from the hotkey thread and the worker
        self.keys = GlobalHotkey(hotkey, self.toggle, self.captured, self.rejected)
        self.retitle()

    @property
    def hotkey(self) -> Hotkey:
        return self.keys.matcher.hotkey

    def retitle(self):
        self.icon.title = f"Dictation: {self.hotkey} to start/stop"
        self.icon.update_menu()

    def toggle(self):
        with self.lock:
            self.stop() if self.stream else self.start()

    def start(self):
        self.blocks = queue.Queue()
        threading.Thread(target=self._worker, args=(self.blocks,), daemon=True).start()
        q = self.blocks
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK,
                                     callback=lambda d, *_: q.put(d[:, 0].copy()))
        self.stream.start()
        self.icon.icon = LISTENING
        LOG.info("listening")

    def stop(self):
        self.stream.stop()
        self.stream.close()
        self.stream = None
        self.blocks.put(None)  # the worker finishes the last phrase, then exits
        self.icon.icon = IDLE

    def _worker(self, blocks: queue.Queue):
        # Transcription runs here, never in the audio callback, so the mic never drops blocks.
        live, started, n = Live(type_text), time.monotonic(), 0
        try:
            while (block := blocks.get()) is not None:
                live.feed(block)
                n += 1
                if live.done_talking():
                    with self.lock:
                        if self.stream and self.blocks is blocks:  # still this session, not a newer one
                            LOG.info("auto-stop after %.1fs of silence", live.idle_s)
                            self.stop()
            live.finish()
            LOG.info("stopped after %.1fs, peak level %.4f, threshold %.4f, heard speech: %s",
                     n * BLOCK / RATE, live.peak, SPEECH_RMS, live.heard)
            if not live.heard and n * BLOCK / RATE > 1.5:
                self.icon.notify(f"Your mic peaked at {live.peak:.3f}, below the {SPEECH_RMS:.3f} speech level. "
                                 "If you were talking, lower SPEECH_RMS in .env.", "Didn't hear you")
        except Exception as e:
            LOG.exception("failed")
            self.icon.notify(f"{type(e).__name__}: {e}", "Dictation failed")
            with self.lock:
                if self.stream:
                    self.stop()

    def change_shortcut(self):
        with self.lock:
            if self.stream:
                self.stop()
        self.keys.matcher.start_capture()
        self.icon.notify("Press the new shortcut now. Esc cancels.", "Change shortcut")

    def captured(self, hotkey: Hotkey):
        save_hotkey(hotkey.spec)
        self.retitle()
        LOG.info("shortcut set to %s", hotkey.spec)
        self.icon.notify(f"Press {hotkey} to start and stop dictation.", "Shortcut saved")

    def rejected(self, why: str):
        self.icon.notify(why, "Change shortcut")


def main():
    try:
        hotkey = Hotkey(os.environ.get("HOTKEY", DEFAULT_HOTKEY))
        bad = None
    except ValueError as e:
        hotkey, bad = Hotkey(DEFAULT_HOTKEY), e
    icon = pystray.Icon("dictation", IDLE, "Dictation")
    app = App(icon, hotkey)
    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _: f"Shortcut: {app.hotkey}", None, enabled=False),
        pystray.MenuItem("Change shortcut...", lambda: app.change_shortcut()),
        pystray.MenuItem("Quit", lambda i: i.stop()),
    )
    app.keys.start()
    LOG.info("started, shortcut %s", hotkey.spec)

    def ready(i):
        i.visible = True
        if bad:
            i.notify(f"HOTKEY in .env is not valid ({bad}). Using {hotkey}.", "Dictation")
    icon.run(setup=ready)
    app.keys.stop()


if __name__ == "__main__":
    main()
