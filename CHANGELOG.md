# Changelog

## 0.3.0 (2026-11-02)

- Auto-update: on start the app pulls the latest `main`, runs `uv sync --locked` and restarts itself. Offline or with local edits it starts the current version, and a failed sync rolls back to the previous commit. `AUTO_UPDATE=0` turns it off.
- Single instance: a second launch exits right away, so words are never typed twice.
- Start Menu shortcut, so after quitting you can launch it again by typing "Dictation" in Start.

## 0.2.0 (2026-11-02)

- Live typing: words are typed while you speak, about a second behind, using two-pass agreement so nothing typed is ever erased. A 0.8 s pause ends a phrase.
- Right Ctrl now toggles with a tap instead of hold-to-talk, because typing while Ctrl is held would fire shortcuts.
- Voice commands "full stop", "new line" and "new paragraph". Line breaks are typed as Shift+Enter.
- Capitalization at the start of a session and after sentence ends, and no doubled full stops.
- `SPEECH_RMS` setting for noisy rooms.
- Removed the clipboard dependency, since text is typed directly.

## 0.1.0 (2026-11-02)

- Hold Right Ctrl to record, release to paste the transcript into the focused window.
- Transcription on a self-hosted Whisper server. Audio stays in memory.
- Hindi in Devanagari is romanized into Hinglish by a self-hosted LLM.
- Tray icon with status colours and error notifications.
- Start on login.
