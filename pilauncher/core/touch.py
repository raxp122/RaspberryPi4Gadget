"""Lettura diretta del touch resistivo (evdev) con calibrazione e gesti base.

Eventi generati: ("down", pos), ("move", pos), ("up", pos), ("tap", pos),
("rawtap", (raw_x, raw_y)) - quest'ultimo serve solo alla calibrazione.
"""
import os
import re
import struct

FMT = "llHHi"
SZ = struct.calcsize(FMT)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BTN_TOUCH, ABS_X, ABS_Y = 330, 0, 1
DRAG_THRESHOLD = 16  # pixel prima di considerare il tocco un trascinamento


def find_device(name="ADS7846"):
    """Trova /dev/input/eventN del touch: il numero puo' cambiare collegando periferiche USB."""
    try:
        txt = open("/proc/bus/input/devices").read()
    except OSError:
        return None
    for block in txt.split("\n\n"):
        if name in block:
            m = re.search(r"Handlers=.*?\b(event\d+)", block)
            if m:
                return "/dev/input/" + m.group(1)
    return None


def _med(values):
    values = sorted(values)
    return values[len(values) // 2]


class Touch:
    def __init__(self, dev, size, cal=None, rot=90):
        self.size = size
        self.fd = None
        if dev:
            try:
                self.fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                print(f"[touch] impossibile aprire {dev}: {e}", flush=True)
        self.set_calibration(cal, rot)
        self.rx = self.ry = None
        self.down = False
        self.samples, self.raw = [], []
        self.start = self.last = None
        self.drag = False

    def set_calibration(self, cal, rot):
        w, h = self.size
        if cal:
            self.cx, self.cy = cal["x"], cal["y"]
            # calibrazione fatta con lo schermo ruotato di 180 gradi rispetto ad ora
            self.flip = cal.get("rot", rot) != rot
        else:
            self.cx, self.cy = [w / 4095, 0, 0], [0, h / 4095, 0]
            self.flip = False

    def map(self, x, y):
        a, b, c = self.cx
        d, e, f = self.cy
        px, py = a * x + b * y + c, d * x + e * y + f
        w, h = self.size
        if self.flip:
            px, py = w - 1 - px, h - 1 - py
        return (min(max(int(px), 0), w - 1), min(max(int(py), 0), h - 1))

    def fileno(self):
        return self.fd

    def poll(self):
        evs = []
        if self.fd is None:
            return evs
        while True:
            try:
                data = os.read(self.fd, SZ * 64)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            if not data:
                break
            for i in range(0, len(data) - SZ + 1, SZ):
                _, _, t, c, v = struct.unpack_from(FMT, data, i)
                if t == EV_ABS and c == ABS_X:
                    self.rx = v
                elif t == EV_ABS and c == ABS_Y:
                    self.ry = v
                elif t == EV_KEY and c == BTN_TOUCH:
                    if v == 1:
                        self.down = True
                        self.samples, self.raw = [], []
                        self.start = self.last = None
                        self.drag = False
                    elif self.down:
                        self._release(evs)
                elif t == EV_SYN and self.down and self.rx is not None and self.ry is not None:
                    self._sample(evs)
        return evs

    def _sample(self, evs):
        self.raw.append((self.rx, self.ry))
        self.samples.append(self.map(self.rx, self.ry))
        n = len(self.samples)
        if n == 3:
            self.start = (_med(s[0] for s in self.samples), _med(s[1] for s in self.samples))
            self.last = self.start
            evs.append(("down", self.start))
        elif n > 3:
            last3 = self.samples[-3:]
            sm = (_med(s[0] for s in last3), _med(s[1] for s in last3))
            if not self.drag and abs(sm[0] - self.start[0]) + abs(sm[1] - self.start[1]) > DRAG_THRESHOLD:
                self.drag = True
            if self.drag and sm != self.last:
                self.last = sm
                evs.append(("move", sm))

    def _release(self, evs):
        self.down = False
        if not self.samples:
            return
        pos = (_med(s[0] for s in self.samples), _med(s[1] for s in self.samples))
        if self.start is None:  # tocco molto breve
            evs.append(("down", pos))
        if self.drag:
            evs.append(("up", self.last))
            return
        evs.append(("up", pos))
        evs.append(("tap", pos))
        evs.append(("rawtap", (_med(r[0] for r in self.raw), _med(r[1] for r in self.raw))))
