"""Tema, font, icone vettoriali e widget di base."""
import math

import pygame

T = dict(
    bg=(13, 16, 22), bar=(7, 9, 13), surface=(27, 32, 42), surface2=(40, 47, 60),
    line=(44, 52, 66), text=(232, 236, 242), muted=(138, 148, 164),
    accent=(70, 150, 255), accent2=(110, 175, 255), ok=(80, 200, 120),
    warn=(240, 180, 60), danger=(232, 84, 84),
)

FONT_PATHS = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}
_fonts = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        try:
            _fonts[key] = pygame.font.Font(FONT_PATHS[bold], size)
        except (FileNotFoundError, OSError):
            f = pygame.font.Font(None, int(size * 1.35))
            f.set_bold(bold)
            _fonts[key] = f
    return _fonts[key]


def ellipsize(f, s, maxw):
    if maxw is None or f.size(s)[0] <= maxw:
        return s
    while s and f.size(s + "…")[0] > maxw:
        s = s[:-1]
    return s + "…"


def text(surf, s, pos, size=16, color=None, bold=False, anchor="topleft", maxw=None):
    f = font(size, bold)
    img = f.render(ellipsize(f, str(s), maxw), True, color or T["text"])
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def wrap(s, size, maxw, bold=False):
    f = font(size, bold)
    lines = []
    for par in str(s).split("\n"):
        cur = ""
        for word in par.split(" "):
            test = (cur + " " + word).strip()
            if f.size(test)[0] <= maxw:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def rrect(surf, color, rect, r=8, width=0):
    pygame.draw.rect(surf, color, rect, width, border_radius=r)


def lighten(c, k=28):
    return tuple(min(255, v + k) for v in c)


# ---------------------------------------------------------------- icone
def thick_arc(s, col, center, r, a0, a1, w, steps=18):
    cx, cy = center
    outer, inner = [], []
    for k in range(steps + 1):
        a = a0 + (a1 - a0) * k / steps
        outer.append((cx + r * math.cos(a), cy - r * math.sin(a)))
        inner.append((cx + (r - w) * math.cos(a), cy - (r - w) * math.sin(a)))
    pygame.draw.polygon(s, col, outer + inner[::-1])


def icon_gear(s, c, sz, col, hole=None):
    cx, cy = c
    r1, r2, n = sz * 0.46, sz * 0.34, 8
    pts = []
    for i in range(n * 4):
        a = 2 * math.pi * (i + 0.5) / (n * 4)
        r = r1 if i % 4 in (0, 1) else r2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pygame.draw.polygon(s, col, pts)
    pygame.draw.circle(s, col, c, int(r2))
    pygame.draw.circle(s, hole or T["bg"], c, int(sz * 0.15))


def icon_wifi(s, c, sz, col, level=4, dim=None):
    dim = dim or T["line"]
    cx, cy = c
    base = (cx, cy + sz * 0.34)
    w = max(2, sz * 0.11)
    for i in range(3):
        r = sz * (0.30 + 0.21 * i)
        thick_arc(s, col if level >= i + 2 else dim, base, r, math.radians(48), math.radians(132), w)
    pygame.draw.circle(s, col if level >= 1 else dim, (int(base[0]), int(base[1] - w * 0.6)), max(2, int(w * 0.9)))


def icon_wifi_off(s, c, sz, col):
    icon_wifi(s, c, sz, T["line"], level=0)
    cx, cy = c
    pygame.draw.line(s, col, (cx - sz * 0.38, cy - sz * 0.3), (cx + sz * 0.38, cy + sz * 0.38), max(2, int(sz * 0.09)))


def icon_bt(s, c, sz, col):
    cx, cy = c
    h, w = sz * 0.42, sz * 0.21
    pts = [(cx - w, cy - h * 0.5), (cx + w, cy + h * 0.5), (cx, cy + h),
           (cx, cy - h), (cx + w, cy - h * 0.5), (cx - w, cy + h * 0.5)]
    pygame.draw.lines(s, col, False, pts, max(2, int(sz * 0.09)))


def icon_info(s, c, sz, col):
    pygame.draw.circle(s, col, c, int(sz * 0.42), max(2, int(sz * 0.08)))
    cx, cy = c
    pygame.draw.circle(s, col, (cx, int(cy - sz * 0.18)), max(2, int(sz * 0.06)))
    pygame.draw.line(s, col, (cx, cy - sz * 0.04), (cx, cy + sz * 0.24), max(2, int(sz * 0.09)))


def icon_power(s, c, sz, col):
    w = max(2, sz * 0.1)
    thick_arc(s, col, c, sz * 0.4, math.radians(125), math.radians(415), w, 28)
    cx, cy = c
    pygame.draw.line(s, col, (cx, cy - sz * 0.46), (cx, cy - sz * 0.04), int(w))


def icon_clock(s, c, sz, col):
    w = max(2, int(sz * 0.08))
    pygame.draw.circle(s, col, c, int(sz * 0.42), w)
    cx, cy = c
    pygame.draw.line(s, col, c, (cx, cy - sz * 0.26), w)
    pygame.draw.line(s, col, c, (cx + sz * 0.18, cy + sz * 0.08), w)


def icon_screen(s, c, sz, col):
    cx, cy = c
    r = pygame.Rect(0, 0, sz * 0.82, sz * 0.58)
    r.center = (cx, cy - sz * 0.05)
    rrect(s, col, r, max(2, int(sz * 0.08)), max(2, int(sz * 0.08)))
    pygame.draw.line(s, col, (cx - sz * 0.18, cy + sz * 0.36), (cx + sz * 0.18, cy + sz * 0.36), max(2, int(sz * 0.08)))


def icon_lock(s, c, sz, col):
    cx, cy = c
    body = pygame.Rect(0, 0, sz * 0.62, sz * 0.46)
    body.midtop = (cx, cy - sz * 0.04)
    rrect(s, col, body, 2)
    thick_arc(s, col, (cx, cy - sz * 0.04), sz * 0.24, 0, math.pi, max(2, sz * 0.08), 12)


def icon_chevron(s, c, sz, col, left=False):
    cx, cy = c
    d = -1 if left else 1
    pts = [(cx - d * sz * 0.15, cy - sz * 0.3), (cx + d * sz * 0.15, cy), (cx - d * sz * 0.15, cy + sz * 0.3)]
    pygame.draw.lines(s, col, False, pts, max(2, int(sz * 0.1)))


def icon_refresh(s, c, sz, col):
    w = max(2, sz * 0.1)
    thick_arc(s, col, c, sz * 0.38, math.radians(30), math.radians(300), w, 20)
    cx, cy = c
    a = math.radians(30)
    tip = (cx + sz * 0.38 * math.cos(a) - w / 2, cy - sz * 0.38 * math.sin(a))
    pygame.draw.polygon(s, col, [(tip[0] - sz * 0.16, tip[1] - sz * 0.02), (tip[0] + sz * 0.14, tip[1] - sz * 0.06),
                                 (tip[0] + sz * 0.02, tip[1] + sz * 0.2)])


def signal_bars(s, rect, level, col=None, dim=None):
    """level 0..4"""
    col, dim = col or T["text"], dim or T["line"]
    bw = rect.w // 4 - 2
    for i in range(4):
        h = int(rect.h * (i + 1) / 4)
        r = pygame.Rect(rect.x + i * (bw + 2), rect.bottom - h, bw, h)
        pygame.draw.rect(s, col if level > i else dim, r, border_radius=1)


def signal_level(pct):
    return 0 if pct <= 0 else 1 if pct < 30 else 2 if pct < 55 else 3 if pct < 75 else 4


# ---------------------------------------------------------------- widget
class Widget:
    def __init__(self, rect):
        self.rect = pygame.Rect(rect)
        self.pressed = False
        self.enabled = True

    def hit(self, pos):
        return self.enabled and self.rect.collidepoint(pos)

    def draw(self, s):
        pass

    def on_down(self, pos):
        self.pressed = True

    def on_move(self, pos):
        if not self.rect.collidepoint(pos):
            self.pressed = False

    def on_up(self, pos):
        self.pressed = False

    def on_tap(self, pos):
        pass


class Button(Widget):
    def __init__(self, rect, label, on_tap=None, kind="normal", icon=None, size=15, radius=8):
        super().__init__(rect)
        self.label, self.cb, self.kind, self.icon, self.size, self.radius = label, on_tap, kind, icon, size, radius

    def colors(self):
        bg = {"primary": T["accent"], "danger": T["danger"], "flat": T["bg"]}.get(self.kind, T["surface2"])
        fg = T["text"]
        if not self.enabled:
            bg, fg = T["surface"], T["muted"]
        elif self.pressed:
            bg = lighten(bg, 40)
        return bg, fg

    def draw(self, s):
        bg, fg = self.colors()
        rrect(s, bg, self.rect, self.radius)
        if self.icon and self.label:
            f = font(self.size, True)
            tw = f.size(self.label)[0]
            x0 = self.rect.centerx - (tw + 26) // 2
            self.icon(s, (x0 + 10, self.rect.centery), 20, fg)
            text(s, self.label, (x0 + 26, self.rect.centery), self.size, fg, True, "midleft")
        elif self.icon:
            self.icon(s, self.rect.center, min(self.rect.h, self.rect.w) - 12, fg)
        else:
            text(s, self.label, self.rect.center, self.size, fg, True, "center", self.rect.w - 8)

    def on_tap(self, pos):
        if self.cb:
            self.cb()


class Toggle(Widget):
    def __init__(self, rect, value, on_change=None):
        super().__init__(rect)
        self.value, self.cb = value, on_change

    def hit(self, pos):  # area di tocco piu' generosa del disegno
        return self.enabled and self.rect.inflate(16, 16).collidepoint(pos)

    def draw(self, s):
        on = bool(self.value)
        track = T["accent"] if on else T["line"]
        if not self.enabled:
            track = T["surface"]
        rrect(s, track, self.rect, self.rect.h // 2)
        r = self.rect.h // 2 - 3
        x = self.rect.right - r - 3 if on else self.rect.x + r + 3
        pygame.draw.circle(s, T["text"] if self.enabled else T["muted"], (x, self.rect.centery), r)

    def on_tap(self, pos):
        self.value = not self.value
        if self.cb:
            self.cb(self.value)


def render_row(s, r, it):
    """Riga standard di una lista: dict con title, subtitle, icon, icon_color, right, chevron, draw_right."""
    x = r.x + 14
    if it.get("icon"):
        it["icon"](s, (r.x + 26, r.centery), 24, it.get("icon_color", T["text"]))
        x = r.x + 50
    right = r.right - 12
    if it.get("chevron"):
        icon_chevron(s, (right - 6, r.centery), 18, T["muted"])
        right -= 22
    if it.get("draw_right"):
        right -= it["draw_right"](s, pygame.Rect(r.x, r.y, right - r.x, r.h)) + 8
    if it.get("right"):
        rr = text(s, it["right"], (right, r.centery), 13, it.get("right_color", T["muted"]), anchor="midright",
                  maxw=max(40, (right - x) // 2))
        right = rr.x - 8
    maxw = right - x
    if it.get("subtitle"):
        text(s, it.get("title", ""), (x, r.centery - 9), 15, it.get("title_color"), anchor="midleft", maxw=maxw)
        text(s, it["subtitle"], (x, r.centery + 10), 12, it.get("subtitle_color", T["muted"]), anchor="midleft",
             maxw=maxw)
    else:
        text(s, it.get("title", ""), (x, r.centery), 15, it.get("title_color"), anchor="midleft", maxw=maxw)


class ListView(Widget):
    def __init__(self, rect, items, row_h=46, render=render_row, on_select=None, empty_text=""):
        super().__init__(rect)
        self.items, self.row_h, self.render, self.cb, self.empty = items, row_h, render, on_select, empty_text
        self.offset = 0
        self.drag_from = None
        self.pressed_idx = None

    def max_offset(self):
        return max(0, len(self.items) * self.row_h - self.rect.h)

    def scroll_to(self, idx):
        self.offset = min(self.max_offset(), max(0, idx * self.row_h - self.rect.h // 2 + self.row_h // 2))

    def index_at(self, pos):
        if not self.rect.collidepoint(pos):
            return None
        i = int((pos[1] - self.rect.y + self.offset) // self.row_h)
        return i if 0 <= i < len(self.items) else None

    def draw(self, s):
        clip = s.get_clip()
        s.set_clip(self.rect)
        if not self.items and self.empty:
            text(s, self.empty, self.rect.center, 14, T["muted"], anchor="center")
        first = int(self.offset // self.row_h)
        last = min(len(self.items), first + self.rect.h // self.row_h + 2)
        for i in range(first, last):
            r = pygame.Rect(self.rect.x, self.rect.y + i * self.row_h - int(self.offset), self.rect.w, self.row_h)
            item = self.items[i]
            if i == self.pressed_idx and self.cb and not (isinstance(item, dict) and item.get("static")):
                s.fill(T["surface2"], r)
            self.render(s, r, item)
            pygame.draw.line(s, T["line"], (r.x + 14, r.bottom - 1), (r.right - 14, r.bottom - 1))
        mo = self.max_offset()
        if mo > 0:
            h = max(20, self.rect.h * self.rect.h // (len(self.items) * self.row_h))
            y = self.rect.y + int((self.rect.h - h) * self.offset / mo)
            rrect(s, T["muted"], (self.rect.right - 4, y, 3, h), 2)
        s.set_clip(clip)

    def on_down(self, pos):
        self.drag_from = (pos[1], self.offset)
        self.pressed_idx = self.index_at(pos)

    def on_move(self, pos):
        if self.drag_from:
            self.pressed_idx = None
            self.offset = min(self.max_offset(), max(0, self.drag_from[1] - (pos[1] - self.drag_from[0])))

    def on_up(self, pos):
        self.drag_from = None
        self.pressed_idx = None

    def on_tap(self, pos):
        i = self.index_at(pos)
        if i is not None and self.cb:
            item = self.items[i]
            if not (isinstance(item, dict) and item.get("static")):
                self.cb(item)
