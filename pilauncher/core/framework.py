"""Gestione schermate (stack), barra di stato, task in background, dialoghi."""
import json
import os
import queue
import threading
import time
import traceback

import pygame

from . import system as sysm
from .ui import T, Button, icon_bt, icon_chevron, icon_wifi, icon_wifi_off, rrect, text, wrap

STATUS_H = 22
UPDATE_EVERY = 6 * 3600  # controllo automatico degli aggiornamenti
HEADER_H = 40


class Context:
    """Stato condiviso: configurazione, display, touch."""

    def __init__(self, app_dir, data_dir, display, touch, updater=None):
        self.app_dir, self.data_dir = app_dir, data_dir
        self.display, self.touch, self.updater = display, touch, updater
        self.config_path = os.path.join(data_dir, "config.json")
        self.calib_path = os.path.join(data_dir, "calib.json")
        self.config = load_json(self.config_path, {"rot": 90})
        self.cal = load_json(self.calib_path, None)

    def save_config(self):
        save_json(self.config_path, self.config)

    def save_calibration(self, cal):
        self.cal = cal
        save_json(self.calib_path, cal)
        self.touch.set_calibration(cal, self.config["rot"])

    def set_rotation(self, rot):
        self.config["rot"] = rot
        self.save_config()
        self.display.set_rotation(rot)
        self.touch.set_calibration(self.cal, rot)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


class Screen:
    title = ""        # None = nessuna intestazione
    back = True
    fullscreen = False  # True = niente barra di stato e niente "tocca la barra per tornare alla home"

    def __init__(self, mgr):
        self.mgr = mgr
        self.widgets = []
        self.busy = None
        self.active = None

    @property
    def area(self):
        if self.fullscreen:
            return pygame.Rect(0, 0, *self.mgr.size)
        return pygame.Rect(0, STATUS_H, self.mgr.size[0], self.mgr.size[1] - STATUS_H)

    @property
    def body(self):
        a = self.area
        if self.title is None:
            return a
        return pygame.Rect(a.x, a.y + HEADER_H, a.w, a.h - HEADER_H)

    def back_rect(self):
        a = self.area
        return pygame.Rect(a.x, a.y, 52, HEADER_H)

    # ciclo di vita
    def enter(self):
        self.build()

    def resume(self):
        self.build()

    def leave(self):
        pass

    def build(self):
        pass

    def update(self, now):
        pass

    # disegno
    def draw(self, s):
        a = self.area
        s.fill(T["bg"], a)
        if self.title is not None:
            x = a.x + 14
            if self.back:
                pressed = self.active == "back"
                if pressed:
                    s.fill(T["surface2"], self.back_rect())
                icon_chevron(s, (a.x + 22, a.y + HEADER_H // 2), 22, T["text"], left=True)
                x = a.x + 44
            text(s, self.title, (x, a.y + HEADER_H // 2), 17, bold=True, anchor="midleft", maxw=a.w - x - 90)
            pygame.draw.line(s, T["line"], (a.x, a.y + HEADER_H - 1), (a.right, a.y + HEADER_H - 1))
        self.draw_content(s)
        for w in self.widgets:
            w.draw(s)
        if self.busy:
            dots = "." * (int(time.time() * 3) % 4)
            r = pygame.Rect(0, 0, 250, 28)
            r.midbottom = (a.centerx, a.bottom - 8)
            rrect(s, T["surface2"], r, 14)
            rrect(s, T["accent"], r, 14, 1)
            text(s, self.busy.rstrip(".…") + dots, (r.x + 16, r.centery), 13, anchor="midleft", maxw=r.w - 24)

    def draw_content(self, s):
        pass

    # input
    def dispatch(self, kind, pos):
        if kind == "down":
            self.active = None
            if self.title is not None and self.back and self.back_rect().collidepoint(pos):
                self.active = "back"
                return
            for w in reversed(self.widgets):
                if w.hit(pos):
                    self.active = w
                    w.on_down(pos)
                    return
        elif kind == "move":
            if hasattr(self.active, "on_move"):
                self.active.on_move(pos)
        elif kind == "up":
            if hasattr(self.active, "on_up"):
                self.active.on_up(pos)
        elif kind == "tap":
            act, self.active = self.active, None
            if act == "back":
                if self.back_rect().collidepoint(pos):
                    self.go_back()
            elif act is not None and act.hit(pos):
                act.on_tap(pos)

    def go_back(self):
        self.mgr.pop()


class Confirm(Screen):
    """Dialogo modale di conferma disegnato sopra la schermata precedente."""
    title = None

    def __init__(self, mgr, title, message, yes_label, on_yes, danger=False):
        super().__init__(mgr)
        self.dlg_title, self.message, self.yes_label, self.on_yes, self.danger = title, message, yes_label, on_yes, danger
        self.below = None

    def enter(self):
        self.below = self.mgr.stack[-2] if len(self.mgr.stack) > 1 else None
        self.build()

    def box(self):
        a = self.area
        lines = wrap(self.message, 14, 340)
        h = 60 + len(lines) * 19 + 56
        r = pygame.Rect(0, 0, 380, h)
        r.center = a.center
        return r, lines

    def build(self):
        r, _ = self.box()
        bw = (r.w - 36) // 2
        self.widgets = [
            Button((r.x + 12, r.bottom - 50, bw, 38), "Annulla", self.cancel),
            Button((r.x + 24 + bw, r.bottom - 50, bw, 38), self.yes_label, self.confirm,
                   "danger" if self.danger else "primary"),
        ]

    def cancel(self):
        self.mgr.pop()

    def confirm(self):
        self.mgr.pop()
        self.on_yes()

    def draw(self, s):
        if self.below:
            self.below.draw(s)
        dim = pygame.Surface(self.mgr.size, pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        s.blit(dim, (0, 0))
        r, lines = self.box()
        rrect(s, T["surface"], r, 12)
        rrect(s, T["line"], r, 12, 1)
        text(s, self.dlg_title, (r.x + 18, r.y + 16), 17, bold=True)
        for i, ln in enumerate(lines):
            text(s, ln, (r.x + 18, r.y + 48 + i * 19), 14, T["muted"])
        for w in self.widgets:
            w.draw(s)


class Message(Screen):
    """Schermata a tutto schermo con un messaggio (es. spegnimento)."""
    title = None
    fullscreen = True

    def __init__(self, mgr, title, message=""):
        super().__init__(mgr)
        self.msg_title, self.message = title, message

    def draw(self, s):
        a = self.area
        s.fill(T["bg"])
        text(s, self.msg_title, (a.centerx, a.centery - 20), 22, bold=True, anchor="center")
        for i, ln in enumerate(wrap(self.message, 14, a.w - 60)):
            text(s, ln, (a.centerx, a.centery + 16 + i * 20), 14, T["muted"], anchor="center")

    def dispatch(self, kind, pos):
        pass


class Manager:
    def __init__(self, size, ctx):
        self.size = size
        self.ctx = ctx
        self.stack = []
        self.dirty = True
        self.quit = False
        self.q = queue.Queue()
        self.toast_msg, self.toast_until = None, 0
        self.status = {"wifi": None, "bt": False, "temp": None}
        self.status_press = False
        self.apps = []
        threading.Thread(target=self._status_loop, daemon=True).start()

    # navigazione
    @property
    def top(self):
        return self.stack[-1]

    def push(self, screen):
        if self.stack:
            self.top.leave()
        self.stack.append(screen)
        screen.enter()
        self.dirty = True

    def pop(self):
        if len(self.stack) > 1:
            self.stack.pop().leave()
            self.top.resume()
            self.dirty = True

    def home(self):
        while len(self.stack) > 1:
            self.stack.pop().leave()
        self.top.resume()
        self.dirty = True

    def confirm(self, title, message, yes_label, on_yes, danger=False):
        self.push(Confirm(self, title, message, yes_label, on_yes, danger))

    # task in background
    def run(self, fn, done=None, busy=None):
        scr = self.top
        if busy:
            scr.busy = busy
            self.dirty = True

        def worker():
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                res, err = None, e
            self.q.put((done, res, err, scr, busy))

        threading.Thread(target=worker, daemon=True).start()

    def process(self):
        while True:
            try:
                done, res, err, scr, busy = self.q.get_nowait()
            except queue.Empty:
                break
            if busy and scr.busy == busy:
                scr.busy = None
            if err is not None:
                self.toast(f"Errore: {err}")
            elif done:
                done(res)
            self.dirty = True

    def toast(self, msg, secs=2.8):
        self.toast_msg, self.toast_until = msg, time.time() + secs
        self.dirty = True

    @property
    def animating(self):
        return bool(self.top.busy) or (self.toast_msg and time.time() < self.toast_until + 0.5)

    # input
    def dispatch(self, ev):
        kind, pos = ev
        top = self.top
        if not top.fullscreen:
            if kind == "down":
                self.status_press = pos[1] < STATUS_H
            if self.status_press:
                if kind == "tap":
                    self.status_press = False
                    self.home()
                return
        top.dispatch(kind, pos)
        self.dirty = True

    def update(self, now):
        self.top.update(now)
        if self.toast_msg and now > self.toast_until:
            self.toast_msg = None
            self.dirty = True

    # disegno
    def draw(self, s):
        self.top.draw(s)
        if not self.top.fullscreen:
            self.draw_status(s)
        if self.toast_msg:
            lines = wrap(self.toast_msg, 13, self.size[0] - 80)[:3]
            r = pygame.Rect(0, 0, self.size[0] - 50, 14 + 18 * len(lines))
            r.midtop = (self.size[0] // 2, STATUS_H + 8)
            rrect(s, T["surface2"], r, 10)
            rrect(s, T["line"], r, 10, 1)
            for i, ln in enumerate(lines):
                text(s, ln, (r.x + 14, r.y + 7 + i * 18), 13)

    def draw_status(self, s):
        w = self.size[0]
        s.fill(T["bar"], (0, 0, w, STATUS_H))
        text(s, time.strftime("%H:%M"), (10, STATUS_H // 2), 13, bold=True, anchor="midleft")
        x = w - 10
        wifi = self.status["wifi"]
        if wifi is None:
            icon_wifi_off(s, (x - 9, STATUS_H // 2), 16, T["muted"])
        else:
            icon_wifi(s, (x - 9, STATUS_H // 2 - 1), 16, T["text"], level=max(1, wifi), dim=T["surface2"])
        x -= 26
        if self.status["bt"]:
            icon_bt(s, (x - 5, STATUS_H // 2), 15, T["text"])
            x -= 18
        if self.status["temp"] is not None:
            t = self.status["temp"]
            col = T["danger"] if t >= 75 else T["warn"] if t >= 65 else T["muted"]
            r = text(s, f"{t:.0f}°C", (x, STATUS_H // 2), 12, col, anchor="midright")
            x = r.x - 8
        if self.status.get("power_warn"):
            r = text(s, "⚡", (x, STATUS_H // 2), 13, T["warn"], anchor="midright")
            x = r.x - 8
        if self.status.get("update"):
            text(s, "↑", (x, STATUS_H // 2), 14, T["accent"], bold=True, anchor="midright")

    def _status_loop(self):
        n = 0
        while True:
            try:
                new = dict(self.status)
                new["temp"] = sysm.cpu_temp()
                new["wifi"] = sysm.wifi_quick()
                up = self.ctx.updater
                if up and up.enabled and \
                        time.time() - up.checked_at > (UPDATE_EVERY if up.checked_at else 60):
                    try:
                        up.check()
                    except Exception as e:  # noqa: BLE001
                        print(f"[updater] {e}", flush=True)
                        up.checked_at = time.time() - UPDATE_EVERY + 1800  # riprova tra 30 min
                if up:
                    new["update"] = up.newer_available()
                if n % 3 == 0:
                    new["bt"] = sysm.bt_powered()[0]
                    th = sysm.throttled()
                    new["power_warn"] = bool(th and th["now_undervolt"])
                if new != self.status:
                    self.status = new
                    self.dirty = True
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            n += 1
            time.sleep(5)
