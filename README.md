# local-dictation

Live dictation for Windows that replaces Win+H voice typing. Tap Right Ctrl to start listening, talk, and the words are typed into whatever window has focus as you speak, about a second behind you. Tap Right Ctrl again to stop.

Audio never goes to Microsoft or any other cloud service. Audio is sent only to a Whisper server you run yourself, and stays in memory instead of being written to disk. Whisper is not a streaming model, so the current phrase is re-transcribed every 0.7 s and a word is typed once two passes agree on it. Typed text never has to be erased. A pause of 0.8 s ends the phrase. Hindi phrases come back in Devanagari and are romanized into Hinglish by an LLM you also host, then typed when the phrase ends.

Tray icon: grey means idle, red means listening.

Punctuation: Whisper adds it on its own and turns spoken "comma" and "question mark" into symbols. You can also say "full stop", "new line" and "new paragraph". New lines are typed as Shift+Enter so chat apps do not send the message.

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

Only a clean tap toggles. Holding Right Ctrl or using it in a shortcut (Right Ctrl+C) does nothing. Change the key with `HOTKEY` in `.env`. If pauses are not detected in a noisy room, raise `SPEECH_RMS` (default 0.015).

## Start on login

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Dictation.lnk")
$s.TargetPath = "$PWD\.venv\Scripts\pythonw.exe"; $s.Arguments = "dictate.py"; $s.WorkingDirectory = "$PWD"; $s.Save()
```

## Limits

- The server has to be reachable. If it isn't, you get a tray notification.
- Text is typed with synthetic keystrokes. Keep the focus in the target window while listening, and avoid typing on the keyboard at the same time.
- Win+H still works. Turn off Settings > Privacy & security > Speech > Online speech recognition so Windows has no cloud speech path.
