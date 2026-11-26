"""Calibrazione del touch con 5 mirini e fit ai minimi quadrati."""
import pygame

from .framework import Screen
from .ui import T, Button, text

MARGIN = 30


def _solve3(m, v):
    m = [row[:] + [v[i]] for i, row in enumerate(m)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [a - f * b for a, b in zip(m[r], m[i])]
    return [m[i][3] / m[i][i] for i in range(3)]


def fit(raw, targets):
    rows = [(float(x), float(y), 1.0) for x, y in raw]
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    return [_solve3(ata, [sum(r[i] * t[k] for r, t in zip(rows, targets)) for i in range(3)]) for k in (0, 1)]


class CalibScreen(Screen):
    title = None
    fullscreen = True

    def enter(self):
        w, h = self.mgr.size
        self.targets = [(MARGIN, MARGIN), (w - MARGIN, MARGIN), (MARGIN, h - MARGIN), (w - MARGIN, h - MARGIN),
                        (w // 2, h // 2)]
        self.points, self.result = [], None
        self.widgets = []

    def dispatch(self, kind, pos):
        if self.result is not None:
            return super().dispatch(kind, pos)
        if kind == "rawtap":
            self.points.append(pos)
            if len(self.points) == len(self.targets):
                self.finish()

    def finish(self):
        cx, cy = fit(self.points, self.targets)
        ctx = self.mgr.ctx
        ctx.save_calibration({"rot": ctx.config["rot"], "x": cx, "y": cy})
        errs = []
        for (x, y), (tx, ty) in zip(self.points, self.targets):
            mx, my = cx[0] * x + cx[1] * y + cx[2], cy[0] * x + cy[1] * y + cy[2]
            errs.append(((mx - tx) ** 2 + (my - ty) ** 2) ** 0.5)
        self.result = max(errs)
        w, h = self.mgr.size
        self.widgets = [
            Button((w // 2 - 150, h - 70, 140, 44), "Ripeti", self.enter),
            Button((w // 2 + 10, h - 70, 140, 44), "Fatto", self.mgr.pop, "primary"),
        ]

    def draw(self, s):
        w, h = self.mgr.size
        s.fill(T["bg"])
        if self.result is None:
            tx, ty = self.targets[len(self.points)]
            pygame.draw.line(s, T["accent"], (tx - 16, ty), (tx + 16, ty), 2)
            pygame.draw.line(s, T["accent"], (tx, ty - 16), (tx, ty + 16), 2)
            pygame.draw.circle(s, T["accent2"], (tx, ty), 9, 2)
            y = h // 2 + 34 if ty <= h // 2 + 40 and ty >= h // 2 - 40 else h // 2 - 10
            text(s, "Calibrazione touch", (w // 2, y), 18, bold=True, anchor="center")
            text(s, f"Tocca il centro del mirino ({len(self.points) + 1}/{len(self.targets)})", (w // 2, y + 24), 13,
                 T["muted"], anchor="center")
        else:
            col = T["ok"] if self.result < 5 else T["warn"] if self.result < 10 else T["danger"]
            text(s, "Calibrazione salvata", (w // 2, 80), 20, bold=True, anchor="center")
            text(s, f"Errore massimo: {self.result:.1f} px", (w // 2, 115), 15, col, anchor="center")
            hint = "Ottima precisione." if self.result < 5 else "Accettabile, puoi ripetere per migliorarla." \
                if self.result < 10 else "Imprecisa: ripeti toccando con un'unghia o un pennino."
            text(s, hint, (w // 2, 145), 13, T["muted"], anchor="center")
            for wd in self.widgets:
                wd.draw(s)
