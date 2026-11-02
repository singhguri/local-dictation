# local-dictation

Private live dictation for Windows, built to replace Win+H voice typing. Press Win+Space, talk, and your words are typed into whatever window has focus about a second behind you. It stops by itself once you have been quiet for a while, or press Win+Space again to stop sooner. Audio goes only to servers you run yourself, never to Microsoft or any other cloud service.

## Features

**Live typing.** Words appear while you are still talking. Whisper is not a streaming model, so the current phrase is re-transcribed every 0.7 s and a word is typed once two passes in a row agree on it, punctuation included. That way nothing typed ever has to be erased. A pause of 0.8 s ends the phrase, and a phrase is cut at 20 s so re-transcribing stays fast.

**Stops by itself.** You do not have to end a session. After you have spoken, 6 s of silence ends it. Before you say anything it waits 8 s, so you have a moment to start. Normal thinking pauses do not cut you off, and it learns your pace: once you have taken a long pause and kept talking, it waits 1.5 times your longest pause so far, up to 15 s. The last phrase is still typed and the tray dot turns grey. Set `AUTO_STOP_S` in `.env` to wait longer, or `0` to stop only with the shortcut.

**Shortcut you can change.** The default is Win+Space, pressed once to start and once to stop. To change it, right-click the tray dot, choose "Change shortcut...", and press the new keys (Esc cancels). The choice is saved to `HOTKEY` in `.env` and works right away. Two kinds are allowed:

- A combination such as Win+Space or Ctrl+Alt+D. The app swallows that key, so Windows never sees it. Win+Space does not switch keyboard layout, and releasing Win does not open Start.
- A single key such as Right Ctrl, F8, Insert, Scroll Lock or Pause, which toggles on a clean tap. Holding it, or using it in a shortcut like Right Ctrl+C, does nothing. Letters, digits and Space need a modifier, or they would fire while you type.

Holding a key as push-to-talk is not supported, because typed letters would turn into Ctrl or Win shortcuts while it is down.

**Punctuation and voice commands.** Whisper adds punctuation on its own and turns spoken "comma" and "question mark" into symbols. On top of that you can say:

| Say | Typed |
|---|---|
| full stop | `.` (never doubled if Whisper already ended the sentence) |
| new line | a line break |
| new paragraph | two line breaks |

Line breaks are typed as Shift+Enter, so Slack, WhatsApp and similar apps do not send the message. The first letter of a session, and the first letter after `.`, `?`, `!` or a line break, is capitalized.

**English and Hinglish.** English is typed as it comes. When Whisper returns Hindi in Devanagari, the phrase is romanized into Hinglish ("Aaj shaam ko call karte hain") by an LLM you host, then typed when the phrase ends. The check looks at the script, not Whisper's language guess, which sometimes says Urdu or Marathi. If the LLM is down, the Devanagari is typed instead, so nothing you said is lost.

**Privacy.** Audio stays in memory and is never written to disk on the laptop. It is sent only to `STT_URL`, and Hindi text only to `LLM_URL`. The mic is open only while listening, so the Windows mic indicator shows only then.

**Tray icon.** A grey dot means idle and red means listening. Hover it to see the current shortcut. Right-click it to change the shortcut or quit. Errors, such as the server being unreachable, show up as a tray notification and stop listening.

**Tells you when it cannot hear you.** If a session longer than 1.5 s never reaches the speech level, a "Didn't hear you" notification shows your mic's peak level next to `SPEECH_RMS`, so you know whether to lower it.

**Local log.** `dictation.log` in the app folder records starts, stops, shortcut changes, mic levels and errors, never what you said. It is capped at about 400 KB.

**Auto-update.** Each time the app starts, it runs `git pull --ff-only`. If new code arrived, it runs `uv sync --locked` and restarts itself on the new version. This runs before any compiled packages load, so Windows has not locked their files yet. If you are offline, have local edits, or git or uv is missing, the app starts the version you already have. If `uv sync` fails, the app rolls back to the previous commit. Set `AUTO_UPDATE=0` in `.env` to turn it off.

**Single instance.** Launching it while it is already running does nothing, so two copies never type the same words twice.

## Server side

You need two endpoints on a machine you control:

- `STT_URL`: `POST` multipart `file=<wav>` with `Authorization: Bearer <STT_KEY>`, returning `{"text": ..., "language": ...}`. A small FastAPI app around `faster-whisper` (large-v3-turbo) works. Each pass on a short phrase takes about 0.3 s on a GPU.
- `LLM_URL`: any OpenAI-compatible `/v1/chat/completions`, such as vLLM or llama.cpp.

> [!WARNING]
> **A cloud LLM breaks the privacy promise.** If `LLM_URL` points at a hosted API such as DeepSeek or OpenAI, your audio still goes only to your Whisper server, but the text of everything you say in Hindi goes to that provider's cloud. That is the kind of thing this app was built to avoid. It can be a fair trade if you have no server of your own. For private dictation, run the LLM on your own machine.

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
  $s.WorkingDirectory = "$PWD"; $s.Description = "Private dictation"; $s.Save()
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
| `LLM_KEY` | empty | Bearer key for `LLM_URL`. Only hosted APIs such as DeepSeek or OpenAI need one. See the privacy warning above |
| `HOTKEY` | `win+space` | Start/stop shortcut. Easiest to set from the tray. Format: modifiers `ctrl`, `alt`, `shift`, `win` joined with `+` to a key (`ctrl+alt+d`), or one key: `ctrl_r`, `alt_r`, `f1`...`f24`, `insert`, `scroll_lock`, `pause` |
| `SPEECH_RMS` | `0.015` | Mic level that counts as speech. Raise it if pauses are missed in a noisy room |
| `AUTO_STOP_S` | `6` | Seconds of silence after speech that end the session. It can wait longer to match your pauses (see Features). `0` turns auto-stop off |
| `AUTO_UPDATE` | `1` | `0` turns off update-on-start |

## Limits

- The server has to be reachable. If it is not, you get a tray notification.
- Text is typed with synthetic keystrokes. Keep the focus in the target window while listening, and avoid typing on the keyboard at the same time.
- Hindi phrases appear when you pause, not word by word, because a half-romanized sentence would change spelling as more words arrive.
- Win+H still works. Turn off Settings > Privacy & security > Speech > Online speech recognition so Windows has no cloud speech path.

See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## License

MIT. See [LICENSE](LICENSE).
