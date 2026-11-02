# local-dictation

Private live dictation for Windows, built to replace Win+H voice typing. Tap Right Ctrl, talk, and your words are typed into whatever window has focus about a second behind you. Tap Right Ctrl again to stop. Audio goes only to servers you run yourself, never to Microsoft or any other cloud service.

## Features

**Live typing.** Words appear while you are still talking. Whisper is not a streaming model, so the current phrase is re-transcribed every 0.7 s and a word is typed once two passes in a row agree on it, punctuation included. That way nothing typed ever has to be erased. A pause of 0.8 s ends the phrase, and a phrase is cut at 20 s so re-transcribing stays fast.

**Tap to toggle.** A clean tap of Right Ctrl starts or stops listening. Holding Right Ctrl or using it in a shortcut (Right Ctrl+C) does nothing. Holding cannot work as push-to-talk, because typed letters would turn into Ctrl shortcuts while it is down.

**Punctuation and voice commands.** Whisper adds punctuation on its own and turns spoken "comma" and "question mark" into symbols. On top of that you can say:

| Say | Typed |
|---|---|
| full stop | `.` (never doubled if Whisper already ended the sentence) |
| new line | a line break |
| new paragraph | two line breaks |

Line breaks are typed as Shift+Enter, so Slack, WhatsApp and similar apps do not send the message. The first letter of a session, and the first letter after `.`, `?`, `!` or a line break, is capitalized.

**English and Hinglish.** English is typed as it comes. When Whisper returns Hindi in Devanagari, the phrase is romanized into Hinglish ("Aaj shaam ko call karte hain") by an LLM you host, then typed when the phrase ends. The check looks at the script, not Whisper's language guess, which sometimes says Urdu or Marathi. If the LLM is down, the Devanagari is typed instead, so nothing you said is lost.

**Privacy.** Audio stays in memory and is never written to disk on the laptop. It is sent only to `STT_URL`, and Hindi text only to `LLM_URL`. The mic is open only while listening, so the Windows mic indicator shows only then.

**Tray icon.** A grey dot means idle and red means listening. Right-click it to quit. Errors, such as the server being unreachable, show up as a tray notification and stop listening.

**Auto-update.** Each time the app starts, it runs `git pull --ff-only`. If new code arrived, it runs `uv sync --locked` and restarts itself on the new version. This runs before any compiled packages load, so Windows has not locked their files yet. If you are offline, have local edits, or git or uv is missing, the app starts the version you already have. If `uv sync` fails, the app rolls back to the previous commit. Set `AUTO_UPDATE=0` in `.env` to turn it off.

**Single instance.** Launching it while it is already running does nothing, so two copies never type the same words twice.

## Server side

You need two endpoints on a machine you control:

- `STT_URL`: `POST` multipart `file=<wav>` with `Authorization: Bearer <STT_KEY>`, returning `{"text": ..., "language": ...}`. A small FastAPI app around `faster-whisper` (large-v3-turbo) works. Each pass on a short phrase takes about 0.3 s on a GPU.
- `LLM_URL`: any OpenAI-compatible `/v1/chat/completions`, such as vLLM or llama.cpp.

## Install

```
git clone https://github.com/singhguri/local-dictation.git
cd local-dictation
cp .env.example .env    # fill in STT_URL, STT_KEY, LLM_URL
uv sync
```

Then create the two shortcuts. The Start Menu one lets you launch it by pressing Win and typing "Dictation". The Startup one starts it at login, and that start is also when it updates itself.

```powershell
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in "Programs", "Programs\Startup") {
  $s = $sh.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\$dir\Dictation.lnk")
  $s.TargetPath = "$PWD\.venv\Scripts\pythonw.exe"; $s.Arguments = "dictate.py"
  $s.WorkingDirectory = "$PWD"; $s.Description = "Tap Right Ctrl to dictate"; $s.Save()
}
```

## Launch

- At login it starts on its own.
- After quitting, press Win, type "Dictation" and press Enter.
- From a terminal in the folder: `uv run pythonw dictate.py`

## Settings (`.env`)

| Key | Default | What it does |
|---|---|---|
| `STT_URL` | required | Whisper endpoint |
| `STT_KEY` | required | Bearer key for `STT_URL` |
| `LLM_URL` | required | Chat endpoint used to romanize Hindi |
| `LLM_MODEL` | `model` | Model name sent to `LLM_URL` |
| `HOTKEY` | `ctrl_r` | Any pynput key name: `alt_r`, `f8`, `scroll_lock`, ... |
| `SPEECH_RMS` | `0.015` | Mic level that counts as speech. Raise it if pauses are missed in a noisy room |
| `AUTO_UPDATE` | `1` | `0` turns off update-on-start |

## Limits

- The server has to be reachable. If it is not, you get a tray notification.
- Text is typed with synthetic keystrokes. Keep the focus in the target window while listening, and avoid typing on the keyboard at the same time.
- Hindi phrases appear when you pause, not word by word, because a half-romanized sentence would change spelling as more words arrive.
- Win+H still works. Turn off Settings > Privacy & security > Speech > Online speech recognition so Windows has no cloud speech path.

See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.
