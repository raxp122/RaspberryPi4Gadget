"""Schermata principale del Tester rete."""
import pygame

from core.framework import Screen
from core.ui import T, Button, ListView, text

from .common import ORDER, NAMES, ROW_H, status_icon, icon_net, Detail, targets, net_cfg

from .diag import Diagnosis
from .ipconf import IpScreen
from core import history

from .history import net_entry
from .report import ask_and_save
from .targets import TargetsScreen
from .tools import Tools


class NetTest(Screen):
    title = "Tester rete"

    def __init__(self, mgr):
        super().__init__(mgr)
        self.diag = Diagnosis(self._changed, lambda: targets(net_cfg(mgr)))
        self.diag.on_finished = self._record
        self.last_hist = None
        self.next_tick = 0

    def _changed(self):
        self.mgr.dirty = True

    def enter(self):
        self.build()
        self.diag.start()

    def leave(self):
        if self not in self.mgr.stack:  # uscita dall'app, non apertura di una sottoschermata
            self.diag.close()

    def build(self):
        a, b = self.area, self.body
        old = self.widgets[0].offset if self.widgets else 0
        lv = ListView(b, [{"key": k} for k in ORDER], ROW_H, render=self._row, on_select=self.open_detail)
        lv.offset = min(old, lv.max_offset())
        self.widgets = [
            lv,
            Button((a.right - 258, a.y + 6, 66, 28), "Report", lambda: ask_and_save(self.mgr, self.diag),
                   size=13),
            Button((a.right - 186, a.y + 6, 96, 28), "Strumenti", lambda: self.mgr.push(Tools(self.mgr, self)),
                   size=13),
            Button((a.right - 84, a.y + 6, 76, 28), "Ripeti", self.repeat, size=13),
        ]

    def _row(self, s, r, it):
        c = self.diag.get(it["key"])
        status_icon(c["st"])(s, (r.x + 24, r.centery), 20)
        x, right = r.x + 46, r.right - 30
        if c["rows"] or c["hints"]:
            pygame.draw.lines(s, T["muted"], False, [(r.right - 18, r.centery - 5), (r.right - 13, r.centery),
                                                     (r.right - 18, r.centery + 5)], 2)
        text(s, NAMES[it["key"]], (x, r.centery - 9), 14, anchor="midleft", maxw=right - x)
        col = {"ok": T["ok"], "warn": T["warn"], "fail": T["danger"]}.get(c["st"], T["muted"])
        text(s, c["sum"] or ("In attesa" if c["st"] == "wait" else ""), (x, r.centery + 10), 12, col,
             anchor="midleft", maxw=right - x)

    def _record(self):
        """Ogni test finito va nello storico (data/history-net.jsonl)."""
        self.last_hist = history.add(self.mgr.ctx.data_dir, "net", net_entry(self.diag))

    def update(self, now):
        h = self.last_hist
        if h and not h.get("switch") and not h.get("port") and self.diag.listener.neighbor:
            nb = self.diag.listener.neighbor   # l'annuncio dello switch è arrivato dopo la fine dei controlli
            patch = {k: nb.get(src) for k, src in (("switch", "name"), ("port", "port"), ("port_desc", "port_desc"),
                                                     ("vlan", "vlan"), ("voice_vlan", "voice_vlan"),
                                                     ("mgmt", "mgmt"), ("proto", "proto"))}
            patch["switch"] = patch["switch"] or nb.get("chassis") or ""
            h.update(patch)
            try:
                history.update(self.mgr.ctx.data_dir, "net", h["t"], patch)
            except OSError:
                pass
        # ridisegno 2 volte al secondo mentre qualcosa è in corso (contatori e icona che gira)
        busy = self.diag.running or self.diag.get("switch")["st"] == "run"
        if busy and now >= self.next_tick:
            self.next_tick = now + 0.5
            self.mgr.dirty = True

    def repeat(self):
        self.diag.listener.reset()
        self.diag.rerun.set()

    def open_detail(self, it):
        if it["key"] == "ip":
            self.mgr.push(IpScreen(self.mgr, self))
            return
        if it["key"] == "svc" and not targets(net_cfg(self.mgr)):
            self.mgr.push(TargetsScreen(self.mgr, self))
            return
        c = self.diag.get(it["key"])
        if c["rows"] or c["hints"]:
            self.mgr.push(Detail(self.mgr, NAMES[it["key"]], c["rows"], c["hints"]))


APP = {"name": "Tester rete", "icon": icon_net, "color": (36, 140, 110), "order": 5, "screen": NetTest}
