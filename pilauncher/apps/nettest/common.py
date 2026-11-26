"""Costanti, disegno e schermate di dettaglio condivise dal Tester rete."""
import time

import pygame

from core.framework import Screen
from core.ui import T, ListView, text, thick_arc, wrap

ROW_H = 43
LISTEN_MAX = 65          # LLDP arriva ogni ~30 s, CDP ogni ~60 s
DHCP_WAIT = 40
INTERNET_URL = "http://connectivitycheck.gstatic.com/generate_204"
HTTPS_URL = "https://www.google.com/generate_204"
DNS_TEST_NAME = "www.google.com"

TRACE_TARGET = "8.8.8.8"
NTP_WARN, NTP_FAIL = 60, 300   # secondi: oltre 5 minuti il login al dominio Windows fallisce

ORDER = ["link", "switch", "ip", "gw", "dns", "inet", "svc"]
NAMES = {"link": "Cavo e link", "switch": "Switch e porta", "ip": "Indirizzo IP", "gw": "Gateway",
         "dns": "DNS", "inet": "Internet", "svc": "Server aziendali"}


# ================================================================ disegno
def status_icon(st):
    def draw(s, c, sz, col=None):
        cx, cy = c
        r = 9
        if st == "ok":
            pygame.draw.circle(s, T["ok"], c, r)
            pygame.draw.lines(s, T["bg"], False, [(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)], 2)
        elif st == "warn":
            pygame.draw.circle(s, T["warn"], c, r)
            pygame.draw.line(s, T["bg"], (cx, cy - 5), (cx, cy + 1), 2)
            pygame.draw.circle(s, T["bg"], (cx, cy + 4), 1)
        elif st == "fail":
            pygame.draw.circle(s, T["danger"], c, r)
            pygame.draw.line(s, T["bg"], (cx - 3, cy - 3), (cx + 3, cy + 3), 2)
            pygame.draw.line(s, T["bg"], (cx + 3, cy - 3), (cx - 3, cy + 3), 2)
        elif st == "run":
            a = (time.time() * 4) % 6.283
            pygame.draw.circle(s, T["line"], c, r, 2)
            thick_arc(s, T["accent"], c, r - 1, a, a + 1.8, 3, 8)
        elif st == "off":
            pygame.draw.line(s, T["muted"], (cx - 5, cy), (cx + 5, cy), 2)
        else:
            pygame.draw.circle(s, T["line"], c, r, 2)
    return draw


def icon_net(s, c, sz, col):
    """Icona dell'app: presa RJ45 stilizzata."""
    cx, cy = c
    w, h = sz * 0.7, sz * 0.56
    body = pygame.Rect(0, 0, w, h)
    body.center = (cx, cy + sz * 0.04)
    pygame.draw.rect(s, col, body, max(2, int(sz * 0.08)), border_radius=3)
    tab = pygame.Rect(0, 0, w * 0.4, h * 0.26)
    tab.midtop = (cx, body.bottom - max(2, int(sz * 0.08)))
    pygame.draw.rect(s, col, tab)
    for i in range(4):
        x = body.x + w * (0.22 + i * 0.187)
        pygame.draw.line(s, col, (x, body.y + h * 0.22), (x, body.y + h * 0.5), max(2, int(sz * 0.05)))


class Detail(Screen):
    def __init__(self, mgr, title, rows, hints=()):
        super().__init__(mgr)
        self.title = title
        self.rows, self.hints = rows, list(hints)

    def build(self):
        items = [{"title": h, "static": True, "title_color": T["warn"], "hint": True} for h in self.hints]
        items += [{"title": k, "subtitle": v, "static": True} for k, v in self.rows]
        self.widgets = [ListView(self.body, items, 46, render=_detail_row)]


def _detail_row(s, r, it):
    x, maxw = r.x + 14, r.w - 28
    if it.get("hint"):
        lines = wrap(it["title"], 12, maxw - 14)[:2]
        pygame.draw.circle(s, T["warn"], (x + 3, r.centery), 3)
        for i, ln in enumerate(lines):
            text(s, ln, (x + 14, r.centery + (i - (len(lines) - 1) / 2) * 16), 12, T["warn"], anchor="midleft")
        return
    text(s, it["title"], (x, r.centery - 9), 12, T["muted"], anchor="midleft", maxw=maxw)
    text(s, it["subtitle"], (x, r.centery + 9), 14, anchor="midleft", maxw=maxw)


def _dur(sec):
    sec = int(sec)
    if sec >= 86400:
        return f"{sec // 86400} g {sec // 3600 % 24} h"
    if sec >= 3600:
        return f"{sec // 3600} h {sec // 60 % 60} min"
    return f"{sec // 60} min {sec % 60} s"


def _ping_rows(p):
    if not p.get("sent"):
        return [("Errore", p.get("error", "?"))]
    rows = [("Risposte", f"{p['recv']}/{p['sent']} ({p['loss']}% persi)")]
    if p["avg"] is not None:
        rows.append(("Tempo min / medio / max", f"{p['min']:.1f} / {p['avg']:.1f} / {p['max']:.1f} ms"))
    return rows


def _http_txt(r):
    if r["code"]:
        return f"codice {r['code']} · {r['ms']:.0f} ms"
    return r["error"]


def targets(cfg):
    return cfg.setdefault("targets", [])


def net_cfg(mgr):
    cfg = mgr.ctx.config.setdefault("nettest", {})
    cfg.setdefault("mode", "dhcp")
    cfg.setdefault("profiles", [])
    return cfg
