"""Tastiera a schermo (480x320, orizzontale)."""
import pygame

from .framework import Screen
from .ui import T, Button, font, rrect, text

ROWS = {
    "abc": ["qwertyuiop", "asdfghjkl", "zxcvbnm"],
    "123": ["1234567890", "@#$%&*-+()", "!?_/:;'\""],
}


class Key(Button):
    def __init__(self, rect, label, value, cb, kind="normal", size=17):
        super().__init__(rect, label, lambda: cb(value), kind, size=size, radius=6)

    def draw(self, s):
        r = self.rect.inflate(-4, -4)
        bg = T["accent"] if self.kind == "primary" else T["surface2"] if self.kind == "normal" else T["surface"]
        if self.pressed:
            bg = T["accent2"]
        rrect(s, bg, r, 6)
        text(s, self.label, r.center, self.size, T["text"], self.kind != "normal", "center")


class Keyboard(Screen):
    def __init__(self, mgr, title, on_done, initial="", password=False, ok_label="OK", layout="abc"):
        super().__init__(mgr)
        self.title = title
        self.on_done, self.value, self.password, self.ok_label = on_done, initial, password, ok_label
        self.layout, self.shift, self.reveal = layout, False, False

    def build(self):
        b = self.body
        w = self.mgr.size[0]
        self.field = pygame.Rect(8, b.y + 4, w - (110 if self.password else 16), 36)
        ws = []
        if self.password:
            ws.append(Button((w - 98, b.y + 4, 90, 36), "Nascondi" if self.reveal else "Mostra", self.toggle_reveal,
                             size=13))
        y0, kh, kw = b.y + 44, 52, w // 10
        rows = ROWS[self.layout]
        for ri, row in enumerate(rows):
            y = y0 + ri * kh
            if ri == 2:
                ws.append(Key((0, y, kw * 1.5, kh), "⇧" if self.layout == "abc" else "", "shift", self.press,
                              "primary" if self.shift else "mod", 18))
                x = kw * 1.5 + (7 - len(row)) * kw / 2
            else:
                x = (10 - len(row)) * kw / 2
            for ch in row:
                lab = ch.upper() if self.shift else ch
                ws.append(Key((x, y, kw, kh), lab, lab, self.press))
                x += kw
            if ri == 2:
                ws.append(Key((w - kw * 1.5, y, kw * 1.5, kh), "⌫", "bksp", self.press, "mod", 18))
        y = y0 + 3 * kh
        ws += [
            Key((0, y, kw * 2, kh), "123" if self.layout == "abc" else "abc", "layout", self.press, "mod", 15),
            Key((kw * 2, y, kw * 5, kh), "spazio", " ", self.press, "mod", 14),
            Key((kw * 7, y, kw, kh), ".", ".", self.press),
            Key((kw * 8, y, w - kw * 8, kh), self.ok_label, "ok", self.press, "primary", 15),
        ]
        self.widgets = ws

    def toggle_reveal(self):
        self.reveal = not self.reveal
        self.build()

    def press(self, v):
        if v == "shift":
            self.shift = not self.shift
        elif v == "layout":
            self.layout = "123" if self.layout == "abc" else "abc"
            self.shift = False
        elif v == "bksp":
            self.value = self.value[:-1]
        elif v == "ok":
            self.mgr.pop()
            self.on_done(self.value)
            return
        else:
            self.value += v
            self.shift = False
        self.build()

    def draw_content(self, s):
        rrect(s, T["surface"], self.field, 8)
        rrect(s, T["accent"], self.field, 8, 1)
        shown = self.value if (self.reveal or not self.password) else "•" * len(self.value)
        f = font(17)
        maxw = self.field.w - 24
        while shown and f.size(shown)[0] > maxw:
            shown = shown[1:]
        r = text(s, shown, (self.field.x + 10, self.field.centery), 17, anchor="midleft")
        pygame.draw.line(s, T["accent2"], (r.right + 2, self.field.y + 8), (r.right + 2, self.field.bottom - 8), 2)
        if not self.value:
            text(s, "Scrivi…", (self.field.x + 14, self.field.centery), 15, T["muted"], anchor="midleft")
