"""Schermata principale: orologio e griglia delle app."""
import importlib
import os
import time
import traceback

import pygame

from .framework import Screen
from .ui import T, Widget, lighten, rrect, text

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def discover_apps(app_dir):
    """Ogni modulo in apps/ che definisce APP = {...} diventa un'icona nella home."""
    apps = []
    folder = os.path.join(app_dir, "apps")
    for name in sorted(os.listdir(folder)):
        mod = name[:-3] if name.endswith(".py") else name if os.path.isdir(os.path.join(folder, name)) else None
        if not mod or mod.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"apps.{mod}")
            if hasattr(m, "APP"):
                apps.append(m.APP)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return sorted(apps, key=lambda a: (a.get("order", 100), a["name"]))


class AppTile(Widget):
    def __init__(self, rect, app, cb):
        super().__init__(rect)
        self.app, self.cb = app, cb

    def draw(self, s):
        col = self.app.get("color", T["accent"])
        if self.pressed:
            col = lighten(col, 40)
        box = pygame.Rect(0, 0, 64, 64)
        box.midtop = (self.rect.centerx, self.rect.y + 4)
        rrect(s, col, box, 16)
        self.app["icon"](s, box.center, 38, T["text"], col) if self.app.get("icon_hole") else \
            self.app["icon"](s, box.center, 38, T["text"])
        text(s, self.app["name"], (self.rect.centerx, box.bottom + 6), 12, anchor="midtop", maxw=self.rect.w)

    def on_tap(self, pos):
        self.cb(self.app)


class Home(Screen):
    title = None
    back = False

    def build(self):
        apps = self.mgr.apps
        a = self.area
        cols, tw, th = 4, 110, 96
        x0 = (a.w - cols * tw) // 2
        y0 = a.y + 116
        self.widgets = [
            AppTile((x0 + (i % cols) * tw, y0 + (i // cols) * th, tw, th), app, self.open)
            for i, app in enumerate(apps)
        ]

    def open(self, app):
        self.mgr.push(app["screen"](self.mgr))

    def draw_content(self, s):
        a = self.area
        now = time.localtime()
        text(s, time.strftime("%H:%M", now), (a.centerx, a.y + 44), 48, bold=True, anchor="center")
        data = f"{GIORNI[now.tm_wday].capitalize()} {now.tm_mday} {MESI[now.tm_mon - 1]}"
        text(s, data, (a.centerx, a.y + 84), 15, T["muted"], anchor="center")
        if not self.mgr.apps:
            text(s, "Nessuna app trovata nella cartella apps/", (a.centerx, a.y + 170), 13, T["muted"], anchor="center")
