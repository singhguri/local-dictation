# local-dictation

Hold-to-talk dictation for Windows that replaces Win+H voice typing. Hold Right Ctrl, speak, let go, and the text is pasted into whatever window has focus.

Audio never goes to Microsoft or any other cloud service. Each clip is sent only to a Whisper server you run yourself, and stays in memory instead of being written to disk. Hindi speech comes back from Whisper in Devanagari, and `finalize()` romanizes it into Hinglish with an LLM you also host.

Tray icon: grey means idle, red means recording, amber means transcribing.

## Server side

You need two endpoints on a machine you control:

- `STT_URL`: `POST` multipart `file=<wav>` with `Authorization: Bearer <STT_KEY>`, returning `{"text": ..., "language": ...}`. A small FastAPI app around `faster-whisper` (large-v3-turbo) works.
- `LLM_URL`: any OpenAI-compatible `/v1/chat/completions`, such as vLLM or llama.cpp.

## Run

```
cp .env.example .env    # fill in STT_URL, STT_KEY, LLM_URL
uv sync
uv run pythonw dictate.py
```

Taps shorter than 0.4 s and Right Ctrl used as a shortcut (Right Ctrl+C) are ignored. Change the key with `HOTKEY` in `.env`.

## Start on login

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Dictation.lnk")
$s.TargetPath = "$PWD\.venv\Scripts\pythonw.exe"; $s.Arguments = "dictate.py"; $s.WorkingDirectory = "$PWD"; $s.Save()
```

## Limits

- The server has to be reachable. If it isn't, you get a tray notification.
- Pasting goes through the clipboard. If the clipboard held an image, it is not restored afterwards.
- Win+H still works. Turn off Settings > Privacy & security > Speech > Online speech recognition so Windows has no cloud speech path.
