"""Strumenti del Tester rete."""
import threading
import time

import pygame

from core import netdiag as nd
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, Button, ListView, rrect, text

from .common import Detail

from .active import ActiveScreen
from .history import HistoryScreen
from .ipconf import dhcp_test
from .report import ReportsList
from .targets import TargetsScreen


class Tools(Screen):
    title = "Strumenti di rete"

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main

    def build(self):
        items = [
            {"title": "Storico prese", "subtitle": "Tutti i test fatti, con data, ora, switch e porta",
             "act": lambda: self.mgr.push(HistoryScreen(self.mgr, "net"))},
            {"title": "Report salvati", "subtitle": "Rileggi, QR code, condividi via web",
             "act": lambda: self.mgr.push(ReportsList(self.mgr))},
            {"title": "Server aziendali", "subtitle": "Lista dei server da controllare (solo su questo Pi)",
             "act": lambda: self.mgr.push(TargetsScreen(self.mgr, self.main))},
            {"title": "Ping continuo", "subtitle": "Verso un indirizzo o un nome a scelta", "act": self.ping},
            {"title": "Lampeggia la porta sullo switch", "subtitle": "Per trovare la porta nell'armadio di rete",
             "act": self.blink},
            {"title": "Test del cavo", "subtitle": "Controlla le 4 coppie e la distanza di un guasto",
             "act": self.cable},
            {"title": "Rinnova DHCP", "subtitle": "Rilascia e richiede di nuovo l'indirizzo", "act": self.renew},
            {"title": "Test DHCP dettagliato", "subtitle": "Chi risponde, cosa offre, quanto traffico arriva",
             "act": lambda: dhcp_test(self.mgr)},
            {"title": "Risolvi un nome (DNS)", "subtitle": "Interroga i DNS ricevuti dal DHCP", "act": self.dns},
            {"title": "Scansioni attive", "subtitle": "Dispositivi e porte aperte (da abilitare)",
             "act": lambda: self.mgr.push(ActiveScreen(self.mgr, self.main))},
        ]
        self.widgets = [ListView(self.body, items, 51, on_select=lambda it: it["act"](), )]

    def ping(self):
        ipi = self.main.diag.ipi or {}
        self.mgr.push(Keyboard(self.mgr, "Indirizzo da pingare", lambda h: h.strip() and self.mgr.push(
            PingScreen(self.mgr, h.strip())), initial=ipi.get("gateway") or "", ok_label="Avvia"))

    def blink(self):
        self.mgr.confirm("Lampeggiare la porta?", "Il link viene spento e riacceso ogni 1,5 s per circa 30 s: "
                         "il LED della porta sullo switch lampeggia. La rete del tester si interrompe.",
                         "Avvia", lambda: self.mgr.push(BlinkScreen(self.mgr)))

    def cable(self):
        self.mgr.confirm("Testare il cavo?", "Il link cade per qualche secondo. Funziona meglio con il cavo "
                         "staccato dall'altra parte.", "Avvia", self._cable)

    def _cable(self):
        def done(r):
            if not r["ok"]:
                self.mgr.toast(r["error"], 4)
                return
            rows = []
            for p, v in sorted(r["pairs"].items()):
                val = v["code"] + (f" a {v['len']:.1f} m" if v["len"] is not None else "")
                rows.append((f"Coppia {p}", val))
            bad = [k for k, v in r["pairs"].items() if v["code"] != "OK"]
            hints = [f"Coppie con problemi: {', '.join(sorted(bad))}"] if bad else []
            self.mgr.push(Detail(self.mgr, "Test del cavo", rows, hints))
        self.mgr.run(nd.cable_test, done, "Test del cavo…")

    def renew(self):
        def done(res):
            ok, secs, err = res
            self.mgr.toast(f"Indirizzo ottenuto in {secs:.1f} s" if ok else f"DHCP non riuscito: {err}", 4)
            self.main.diag.rerun.set()
        self.mgr.run(nd.renew_dhcp, done, "Rinnovo DHCP…")

    def dns(self):
        self.mgr.push(Keyboard(self.mgr, "Nome da risolvere", self._dns, ok_label="Cerca"))

    def _dns(self, name):
        name = name.strip()
        servers = (self.main.diag.ipi or {}).get("dns") or []
        if not name:
            return
        if not servers:
            self.mgr.toast("Nessun server DNS: serve prima un indirizzo dal DHCP")
            return

        def job():
            rows = []
            for srv in servers[:3]:
                r = nd.dns_query(srv, name)
                rows.append((srv, f"{r['ms']:.0f} ms · {', '.join(r['ips'])}" if r["ok"] else r["error"]))
            return rows
        self.mgr.run(job, lambda rows: self.mgr.push(Detail(self.mgr, name, rows)), f"Risolvo {name}…")


class PingScreen(Screen):
    def __init__(self, mgr, host):
        super().__init__(mgr)
        self.title = f"Ping {host}"
        self.host = host
        self.rtts = []          # None = perso
        self.stop = threading.Event()
        self.error = ""

    def enter(self):
        self.build()
        threading.Thread(target=self._loop, daemon=True).start()

    def leave(self):
        if self not in self.mgr.stack:
            self.stop.set()

    def _loop(self):
        while not self.stop.is_set():
            t0 = time.time()
            p = nd.ping(self.host, 1, iface=nd.IFACE if nd.carrier() else None)
            if not p.get("sent"):
                self.error = p["error"]
            else:
                self.error = ""
                self.rtts.append(p["avg"] if p["recv"] else None)
                self.rtts = self.rtts[-300:]
            self.mgr.dirty = True
            self.stop.wait(max(0.0, 1 - (time.time() - t0)))

    def draw_content(self, s):
        b = self.body
        ok = [x for x in self.rtts if x is not None]
        sent, lost = len(self.rtts), len(self.rtts) - len(ok)
        last = self.rtts[-1] if self.rtts else None
        x = b.x + 16
        col = T["danger"] if (self.rtts and last is None) else T["text"]
        big = "—" if not self.rtts else ("perso" if last is None else f"{last:.1f} ms")
        text(s, big, (x, b.y + 10), 30, col, bold=True)
        stats = [("Inviati", str(sent)), ("Persi", f"{lost} ({lost * 100 // max(1, sent)}%)"),
                 ("Min", f"{min(ok):.1f}" if ok else "—"), ("Medio", f"{sum(ok) / len(ok):.1f}" if ok else "—"),
                 ("Max", f"{max(ok):.1f}" if ok else "—")]
        for i, (k, v) in enumerate(stats):
            cx = b.x + 16 + i * (b.w - 32) // 5
            text(s, k, (cx, b.y + 56), 11, T["muted"])
            text(s, v, (cx, b.y + 72), 14, bold=True)
        g = pygame.Rect(b.x + 16, b.y + 102, b.w - 32, b.h - 116)
        rrect(s, T["surface"], g, 8)
        data = self.rtts[-(g.w // 6):]
        top = max([v for v in data if v is not None] + [1.0]) * 1.2
        for i, v in enumerate(data):
            bx = g.x + 4 + i * 6
            if v is None:
                pygame.draw.rect(s, T["danger"], (bx, g.y + 4, 4, g.h - 8), border_radius=1)
            else:
                h = max(2, int((g.h - 8) * v / top))
                pygame.draw.rect(s, T["accent"], (bx, g.bottom - 4 - h, 4, h), border_radius=1)
        text(s, f"{top:.0f} ms", (g.right - 6, g.y + 4), 10, T["muted"], anchor="topright")
        if self.error:
            text(s, self.error, g.center, 13, T["warn"], anchor="center", maxw=g.w - 20)


class BlinkScreen(Screen):
    title = "Lampeggio porta"
    back = False

    def __init__(self, mgr):
        super().__init__(mgr)
        self.stop = threading.Event()
        self.step, self.total, self.finished, self.link_on = 0, 10, False, True

    def enter(self):
        self.build()

        def prog(i, n, on):
            self.step, self.total, self.link_on = i, n, on
            self.mgr.dirty = True

        def job():
            nd.blink_port(self.stop, cycles=self.total, period=3.0, progress=prog)
            self.finished = True
            self.mgr.dirty = True

        threading.Thread(target=job, daemon=True).start()

    def build(self):
        b = self.body
        self.widgets = [Button((40, b.bottom - 64, b.w - 80, 48), "Ferma", self.end, "danger")]

    def end(self):
        self.stop.set()
        self.mgr.pop()

    def leave(self):
        self.stop.set()

    def update(self, now):
        if self.finished and self.mgr.top is self:
            self.mgr.pop()
            self.mgr.toast("Lampeggio finito, il link è di nuovo attivo")

    def draw_content(self, s):
        b = self.body
        on = self.link_on
        text(s, "Guarda i LED dello switch:", (b.centerx, b.y + 30), 15, anchor="center")
        text(s, "la porta collegata al tester si spegne e si riaccende.", (b.centerx, b.y + 52), 13, T["muted"],
             anchor="center")
        pygame.draw.circle(s, T["ok"] if on else T["surface2"], (b.centerx, b.y + 108), 22)
        text(s, "link acceso" if on else "link spento", (b.centerx, b.y + 108), 11, T["bg"] if on else T["muted"],
             anchor="center")
        text(s, f"Ciclo {self.step} di {self.total}", (b.centerx, b.y + 150), 14, T["muted"], anchor="center")
