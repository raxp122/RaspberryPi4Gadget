"""Tastiere USB/Bluetooth lette direttamente da evdev, con layout italiano.

Genera eventi ("char", "a") e ("key", "enter" | "bksp" | "esc" | "tab" | "up" | "down" | "left" | "right").
Le tastiere collegate dopo l'avvio vengono trovate da sole (nuova ricerca ogni 3 secondi).
"""
import fcntl
import os
import re
import struct
import time

FMT = "llHHi"
SZ = struct.calcsize(FMT)
EV_KEY = 1
EVIOCGRAB = 0x40044590
EV_REP_BIT = 1 << 20

# codice tasto -> (normale, con shift, con AltGr), layout italiano
_IT = {
    2: ("1", "!"), 3: ("2", '"'), 4: ("3", "£"), 5: ("4", "$"), 6: ("5", "%"), 7: ("6", "&"),
    8: ("7", "/"), 9: ("8", "("), 10: ("9", ")"), 11: ("0", "="), 12: ("'", "?"), 13: ("ì", "^"),
    26: ("è", "é", "["), 27: ("+", "*", "]"), 39: ("ò", "ç", "@"), 40: ("à", "°", "#"), 41: ("\\", "|"),
    43: ("ù", "§"), 51: (",", ";"), 52: (".", ":"), 53: ("-", "_"), 57: (" ", " "), 86: ("<", ">"),
    55: ("*", "*"), 74: ("-", "-"), 78: ("+", "+"), 83: (".", "."), 98: ("/", "/"),
    71: ("7", "7"), 72: ("8", "8"), 73: ("9", "9"), 75: ("4", "4"), 76: ("5", "5"), 77: ("6", "6"),
    79: ("1", "1"), 80: ("2", "2"), 81: ("3", "3"), 82: ("0", "0"),
}
for _code, _ch in zip(list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51)), "qwertyuiopasdfghjklzxcvbnm"):
    _IT[_code] = (_ch, _ch.upper())

_SPECIAL = {1: "esc", 14: "bksp", 15: "tab", 28: "enter", 96: "enter", 103: "up", 108: "down", 105: "left",
            106: "right", 111: "del", 102: "home", 107: "end"}
_SHIFT, _ALTGR, _CAPS = {42, 54}, {100}, 58


def find_keyboards():
    """Percorsi /dev/input/eventN dei dispositivi che si comportano da tastiera."""
    try:
        txt = open("/proc/bus/input/devices").read()
    except OSError:
        return []
    out = []
    for block in txt.split("\n\n"):
        h = re.search(r"Handlers=(.*)", block)
        ev = re.search(r"B: EV=([0-9a-f]+)", block)
        if not h or not ev or "kbd" not in h.group(1).split():
            continue
        if not int(ev.group(1), 16) & EV_REP_BIT:  # i tasti di accensione/GPIO non hanno la ripetizione
            continue
        m = re.search(r"\b(event\d+)", h.group(1))
        if m:
            out.append("/dev/input/" + m.group(1))
    return out


class UsbKeyboards:
    def __init__(self):
        self.fds = {}
        self.shift = self.altgr = self.caps = False
        self.next_scan = 0

    def _scan(self):
        found = set(find_keyboards())
        for path in list(self.fds):
            if path not in found:
                self._close(path)
        for path in found - set(self.fds):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)  # i tasti non finiscono anche sulla console
            except OSError:
                pass
            self.fds[path] = fd
            print(f"[tastiera] collegata {path}", flush=True)

    def _close(self, path):
        try:
            os.close(self.fds.pop(path))
        except (OSError, KeyError):
            pass

    def poll(self):
        now = time.time()
        if now >= self.next_scan:
            self.next_scan = now + 3
            self._scan()
        events = []
        for path, fd in list(self.fds.items()):
            while True:
                try:
                    data = os.read(fd, SZ * 32)
                except BlockingIOError:
                    break
                except OSError:  # tastiera scollegata
                    self._close(path)
                    break
                if not data:
                    break
                for i in range(0, len(data) - SZ + 1, SZ):
                    _, _, typ, code, val = struct.unpack(FMT, data[i:i + SZ])
                    if typ == EV_KEY:
                        ev = self._key(code, val)
                        if ev:
                            events.append(ev)
        return events

    def _key(self, code, val):
        if code in _SHIFT:
            self.shift = val != 0
            return None
        if code in _ALTGR:
            self.altgr = val != 0
            return None
        if val == 0:
            return None
        if code == _CAPS:
            self.caps = not self.caps
            return None
        if code in _SPECIAL:
            return ("key", _SPECIAL[code])
        chars = _IT.get(code)
        if not chars:
            return None
        if self.altgr:
            return ("char", chars[2]) if len(chars) > 2 else None
        ch = chars[1] if self.shift else chars[0]
        if self.caps and ch.isalpha():
            ch = ch.swapcase() if not self.shift else ch.lower()
        return ("char", ch)
