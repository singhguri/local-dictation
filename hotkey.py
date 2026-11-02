"""Global hotkey on the Windows low-level keyboard hook.

Two kinds of shortcut:
  combo     "win+space", "ctrl+alt+d": fires when the key goes down with exactly those modifiers
            held. The key is swallowed so Windows never sees it (no layout switch on Win+Space).
  lone key  "ctrl_r", "f8": fires on a clean tap (no other key, released within TAP_S).

The hook callback must stay fast: Windows silently removes a low-level hook whose callback
stalls, after which no key ever arrives again. So the matcher only flips state and hands the
real work (opening the mic, saving settings) to a thread.
"""
import threading
import time

TAP_S = 0.5
MASK_VK = 0xE8  # unassigned key; tapping it while Win/Alt is held stops Start or the menu bar opening

MODS = {"win": (0x5B, 0x5C), "ctrl": (0xA2, 0xA3), "alt": (0xA4, 0xA5), "shift": (0xA0, 0xA1)}
MOD_ORDER = ["ctrl", "alt", "shift", "win"]
MOD_VKS = {vk for vks in MODS.values() for vk in vks}
SIDED = {"ctrl_l": 0xA2, "ctrl_r": 0xA3, "alt_l": 0xA4, "alt_r": 0xA5,
         "shift_l": 0xA0, "shift_r": 0xA1, "win_l": 0x5B, "win_r": 0x5C}
FKEYS = {f"f{i}": 0x6F + i for i in range(1, 25)}
NAMED = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "backspace": 0x08, "insert": 0x2D,
         "delete": 0x2E, "home": 0x24, "end": 0x23, "page_up": 0x21, "page_down": 0x22,
         "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "caps_lock": 0x14,
         "scroll_lock": 0x91, "pause": 0x13, **FKEYS, **SIDED}
VK_NAME = {vk: name for name, vk in NAMED.items()}
# Keys allowed without a modifier. A lone letter or Space would fire while you type.
LONE_OK = set(SIDED.values()) | set(FKEYS.values()) | {0x2D, 0x91, 0x13}
SIDED_LABEL = {"ctrl_l": "Left Ctrl", "ctrl_r": "Right Ctrl", "alt_l": "Left Alt", "alt_r": "Right Alt",
               "shift_l": "Left Shift", "shift_r": "Right Shift", "win_l": "Left Win", "win_r": "Right Win"}


def key_vk(name: str) -> int:
    if name in NAMED:
        return NAMED[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    raise ValueError(f"unknown key {name!r}")


def vk_name(vk: int) -> str:
    if vk in VK_NAME:
        return VK_NAME[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    raise ValueError(f"key code {vk:#x} has no name")


class Hotkey:
    def __init__(self, spec: str):
        *mods, key = spec.lower().replace(" ", "").split("+")
        if unknown := set(mods) - MODS.keys():
            raise ValueError(f"unknown modifier {', '.join(unknown)}")
        self.mods = frozenset(mods)
        self.vk = key_vk(key)
        if not self.mods and self.vk not in LONE_OK:
            raise ValueError(f"{key!r} needs a modifier, or it would fire while you type")
        self.spec = "+".join([m for m in MOD_ORDER if m in self.mods] + [key])

    def __str__(self):
        *mods, key = self.spec.split("+")
        label = SIDED_LABEL.get(key) or (key.upper() if len(key) == 1 or key in FKEYS else key.replace("_", " ").title())
        return "+".join([m.title() for m in mods] + [label])


class Matcher:
    """Pure state machine: feed it physical key events, it says whether to swallow each one."""

    def __init__(self, hotkey: Hotkey, on_toggle, on_captured, on_rejected, mask):
        self.hotkey = hotkey
        self.on_toggle, self.on_captured, self.on_rejected, self.mask = on_toggle, on_captured, on_rejected, mask
        self.down: set[int] = set()
        self.swallowed: set[int] = set()  # keys whose repeats and key-up we also hide
        self.tap_at = None
        self.tap_spoiled = False
        self.capturing = False
        self.cap_mods: set[int] = set()

    def held_mods(self) -> frozenset:
        return frozenset(m for m, vks in MODS.items() if self.down & set(vks))

    def event(self, vk: int, is_down: bool) -> bool:
        repeat = is_down and vk in self.down
        mods_before = self.held_mods()
        (self.down.add if is_down else self.down.discard)(vk)
        if vk in self.swallowed:
            if not is_down:
                self.swallowed.discard(vk)
            return True
        if self.capturing:
            return self._capture(vk, is_down, repeat, mods_before)
        return self._match(vk, is_down, repeat, mods_before)

    def _swallow(self, vk: int, mods: frozenset) -> bool:
        self.swallowed.add(vk)
        if mods & {"win", "alt"}:
            self.mask()
        return True

    def _match(self, vk, is_down, repeat, mods) -> bool:
        hk = self.hotkey
        if hk.mods:  # combo
            if vk == hk.vk and is_down and not repeat and mods == hk.mods:
                self.on_toggle()
                return self._swallow(vk, mods)
            return False
        if vk == hk.vk:  # lone key: a clean tap
            if is_down and not repeat:
                self.tap_at, self.tap_spoiled = time.monotonic(), False
            elif not is_down and self.tap_at is not None:
                if not self.tap_spoiled and time.monotonic() - self.tap_at < TAP_S:
                    self.on_toggle()
                self.tap_at = None
        elif is_down and self.tap_at is not None:
            self.tap_spoiled = True  # used as part of a shortcut, e.g. Right Ctrl+C
        return False

    def _capture(self, vk, is_down, repeat, mods) -> bool:
        if is_down:
            if repeat:
                return False
            if vk in MOD_VKS:
                self.cap_mods.add(vk)
                return False
            if vk == 0x1B and not mods:  # Esc cancels
                self.capturing = False
                self.on_rejected("Shortcut unchanged.")
                return self._swallow(vk, mods)
            try:
                spec = Hotkey("+".join([m for m in MOD_ORDER if m in mods] + [vk_name(vk)])).spec
            except ValueError as e:
                self.on_rejected(f"{e}. Try another, or Esc to cancel.")
                return self._swallow(vk, mods)
            self._finish(spec)
            return self._swallow(vk, mods)
        if not self.down and len(self.cap_mods) == 1:  # a lone modifier, pressed and released
            self._finish(vk_name(self.cap_mods.pop()))
        elif not self.down:
            self.cap_mods.clear()
        return False

    def start_capture(self):
        self.cap_mods.clear()
        self.capturing = True

    def _finish(self, spec: str):
        self.capturing = False
        self.cap_mods.clear()
        self.hotkey = Hotkey(spec)
        self.on_captured(self.hotkey)


def background(fn):
    """Wrap a callback so it runs on its own thread, keeping the hook callback fast."""
    return lambda *a: threading.Thread(target=fn, args=a, daemon=True).start()


class GlobalHotkey:
    """Matcher wired to the real hook (pynput's win32_event_filter)."""

    def __init__(self, hotkey: Hotkey, on_toggle, on_captured, on_rejected):
        from pynput import keyboard
        ctl = keyboard.Controller()
        mask_key = keyboard.KeyCode.from_vk(MASK_VK)
        self.matcher = Matcher(hotkey, background(on_toggle), background(on_captured),
                               background(on_rejected), mask=lambda: ctl.tap(mask_key))
        self.listener = keyboard.Listener(win32_event_filter=self._filter)

    def _filter(self, msg, data):
        if data.flags & 0x10:  # LLKHF_INJECTED: our own typing and the mask key
            return True
        if self.matcher.event(data.vkCode, msg in (0x100, 0x104)):  # WM_KEYDOWN, WM_SYSKEYDOWN
            self.listener.suppress_event()
        return True

    def start(self):
        self.listener.start()

    def stop(self):
        self.listener.stop()
