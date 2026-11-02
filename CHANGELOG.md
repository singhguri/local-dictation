# Changelog

## 0.6.0 (2026-11-02)

- Stops by itself: 6 s of silence after you speak ends the session, 8 s if you never started. Thinking pauses do not cut you off: after a long pause it waits 1.5 times your longest pause so far, up to 15 s. `AUTO_STOP_S` sets the base, `0` turns it off. The shortcut still stops it right away.

## 0.5.0 (2026-11-02)

- Optional `LLM_KEY`, sent as a Bearer key to `LLM_URL`, so hosted OpenAI-compatible APIs such as DeepSeek can romanize Hindi. Without a key nothing changes.
- README warning: a cloud LLM receives the text of everything you say in Hindi.

## 0.4.1 (2026-11-02)

- Removed the start and stop beeps. The tray dot (red while listening) is the only indicator.

## 0.4.0 (2026-11-02)

- The shortcut can be changed from the tray ("Change shortcut...", Esc cancels) and is saved to `HOTKEY` in `.env`. Combos like Win+Space are swallowed so Windows does not act on them, and lone keys like Right Ctrl toggle on a tap. The default is now Win+Space.
- Fix: the shortcut could stop working after first use. Opening the mic ran inside the Windows keyboard hook, and Windows silently removes a hook that is slow to answer. The hook now only flips state and does the work on another thread.
- Start and stop beeps.
- "Didn't hear you" notification with the mic's peak level when a session never reaches the speech level.
- `dictation.log` with events and mic levels, never transcripts.

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
