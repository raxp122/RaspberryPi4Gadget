"""Configurazione dell'indirizzo IP di eth0: DHCP, IP fissi salvati, rilevamento della rete."""
import threading

import pygame

from core import netdiag as nd
from core.framework import Screen
from core.keyboard import Keyboard
from core.ui import T, Button, ListView, text, wrap

from .common import Detail, _detail_row, net_cfg


def prof_label(p):
    return f"{p['addr']}/{p['prefix']}"


def prof_sub(p):
    parts = [f"gw {p['gw']}" if p.get("gw") else "senza gateway"]
    if p.get("dns"):
        parts.append("DNS " + ", ".join(p["dns"]))
    if p.get("note"):
        parts.insert(0, p["note"])
    return " · ".join(parts)


def apply_profile(mgr, main, idx):
    """idx None = DHCP. Applica, salva la scelta e rilancia i test."""
    cfg = net_cfg(mgr)
    prof = None if idx is None else cfg["profiles"][idx]

    def done(res):
        ok, msg = res
        if ok:
            cfg["mode"] = "dhcp" if idx is None else idx
            mgr.ctx.save_config()
        mgr.toast(msg, 4)
        main.diag.rerun.set()

    mgr.run(lambda: nd.apply_ip_config(prof), done, "Configurazione rete…")


def dhcp_test(mgr):
    if not nd.carrier():
        mgr.toast("Collega prima il cavo")
        return

    def done(r):
        st, summary, rows, hints = nd.dhcp_probe_report(r)
        mgr.push(Detail(mgr, "Test DHCP", [("Esito", summary)] + rows, hints))
    mgr.run(lambda: nd.dhcp_probe(12), done, "Test DHCP (12 s)…")


class IpScreen(Screen):
    title = "Indirizzo IP"

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main

    def build(self):
        c = self.main.diag.get("ip")
        cfg = net_cfg(self.mgr)
        items = [{"title": h, "static": True, "hint": True} for h in c["hints"]]
        items += [{"title": k, "subtitle": v, "static": True} for k, v in c["rows"]]
        items.append({"section": "CONFIGURAZIONE DI ETH0", "static": True})
        items.append({"title": "Automatico (DHCP)", "subtitle": "L'indirizzo lo assegna la rete",
                      "check": cfg["mode"] == "dhcp", "act": lambda: apply_profile(self.mgr, self.main, None)})
        for i, p in enumerate(cfg["profiles"]):
            items.append({"title": "IP fisso " + prof_label(p), "subtitle": prof_sub(p), "check": cfg["mode"] == i,
                          "act": lambda i=i: self.mgr.push(ProfileEdit(self.mgr, self.main, i))})
        items.append({"title": "+ Aggiungi IP fisso", "subtitle": "Indirizzo, maschera, gateway, DNS",
                      "act": lambda: self.mgr.push(ProfileEdit(self.mgr, self.main, None))})
        items.append({"title": "Test DHCP dettagliato", "subtitle": "Chi risponde, cosa offre, quanto traffico arriva",
                      "act": lambda: dhcp_test(self.mgr)})
        items.append({"title": "Rileva la rete della porta", "subtitle": "Ascolta il traffico per suggerire rete e gateway",
                      "act": lambda: self.mgr.push(ArpScreen(self.mgr, self.main))})
        old = self.widgets[0].offset if self.widgets else 0
        lv = ListView(self.body, items, 46, render=_ip_row, on_select=lambda it: it["act"]())
        lv.offset = min(old, lv.max_offset())
        self.widgets = [lv]

    def update(self, now):
        if int(now) != getattr(self, "_sec", None):  # aggiorna i dati dell'IP mentre i test girano
            self._sec = int(now)
            if self.main.diag.running:
                self.build()
                self.mgr.dirty = True


def _ip_row(s, r, it):
    if it.get("section"):
        text(s, it["section"], (r.x + 14, r.bottom - 12), 11, T["muted"], bold=True, anchor="midleft")
        return
    if it.get("static"):
        _detail_row(s, r, it)
        return
    x = r.x + 14
    if "check" in it:
        pygame.draw.circle(s, T["accent"] if it["check"] else T["line"], (x + 9, r.centery), 9, 0 if it["check"] else 2)
        if it["check"]:
            pygame.draw.circle(s, T["bg"], (x + 9, r.centery), 4)
        x += 28
    text(s, it["title"], (x, r.centery - 9), 14, anchor="midleft", maxw=r.right - x - 14)
    text(s, it["subtitle"], (x, r.centery + 10), 12, T["muted"], anchor="midleft", maxw=r.right - x - 14)


class ProfileEdit(Screen):
    def __init__(self, mgr, main, idx, preset=None):
        super().__init__(mgr)
        self.main, self.idx = main, idx
        cfg = net_cfg(mgr)
        if idx is not None:
            p = dict(cfg["profiles"][idx])
        else:
            last = cfg["profiles"][-1] if cfg["profiles"] else {}
            p = {"addr": "", "prefix": last.get("prefix", 24), "gw": "", "dns": list(last.get("dns", [])), "note": ""}
            p.update(preset or {})
        self.p = p
        self.title = "Modifica IP fisso" if idx is not None else "Nuovo IP fisso"

    def build(self):
        p, b = self.p, self.body
        items = [
            {"title": "Indirizzo IP", "subtitle": p["addr"] or "tocca per inserirlo", "f": "addr"},
            {"title": "Maschera", "subtitle": f"/{p['prefix']}  ({_mask(p['prefix'])})", "f": "prefix"},
            {"title": "Gateway", "subtitle": p["gw"] or "nessuno", "f": "gw"},
            {"title": "DNS", "subtitle": ", ".join(p["dns"]) or "nessuno", "f": "dns"},
            {"title": "Nota (es. presa o ufficio)", "subtitle": p.get("note") or "facoltativa", "f": "note"},
        ]
        self.widgets = [ListView((b.x, b.y, b.w, b.h - 56), items, 40, render=_field_row,
                                 on_select=lambda it: self.edit(it["f"]))]
        if self.idx is not None:
            bw = (b.w - 36) // 2
            self.widgets += [Button((12, b.bottom - 50, bw, 42), "Elimina", self.delete, "danger"),
                             Button((24 + bw, b.bottom - 50, bw, 42), "Salva e usa", self.save, "primary")]
        else:
            self.widgets.append(Button((12, b.bottom - 50, b.w - 24, 42), "Salva e usa", self.save, "primary"))

    def edit(self, f):
        p = self.p
        titles = {"addr": "Indirizzo IP", "prefix": "Maschera (24 o 255.255.255.0)", "gw": "Gateway",
                  "dns": "DNS (separati da spazio)", "note": "Nota"}
        initial = {"prefix": str(p["prefix"]), "dns": " ".join(p["dns"])}.get(f, p.get(f) or "")
        if f == "gw" and not initial and nd.valid_ip(p["addr"]):
            initial = p["addr"].rsplit(".", 1)[0] + ".1"

        def done(v):
            v = v.strip()
            if f == "prefix":
                n = nd.parse_prefix(v)
                if n is None:
                    self.mgr.toast("Maschera non valida")
                    return
                p["prefix"] = n
            elif f == "dns":
                vals = v.replace(",", " ").split()
                bad = [x for x in vals if not nd.valid_ip(x)]
                if bad:
                    self.mgr.toast(f"DNS non valido: {bad[0]}")
                    return
                p["dns"] = vals
            elif f in ("addr", "gw"):
                if v and not nd.valid_ip(v):
                    self.mgr.toast("Indirizzo non valido")
                    return
                p[f] = v
            else:
                p[f] = v
            self.build()

        self.mgr.push(Keyboard(self.mgr, titles[f], done, initial=initial,
                               layout="abc" if f == "note" else "123"))

    def save(self):
        import ipaddress
        p = self.p
        if not nd.valid_ip(p["addr"]):
            self.mgr.toast("Inserisci l'indirizzo IP")
            return
        if p["gw"]:
            net = ipaddress.IPv4Network(f"{p['addr']}/{p['prefix']}", strict=False)
            if ipaddress.IPv4Address(p["gw"]) not in net:
                self.mgr.toast(f"Il gateway non è nella rete {net}")
                return
        cfg = net_cfg(self.mgr)
        if self.idx is None:
            cfg["profiles"].append(p)
            idx = len(cfg["profiles"]) - 1
        else:
            cfg["profiles"][self.idx] = p
            idx = self.idx
        self.mgr.ctx.save_config()
        self.mgr.pop()
        apply_profile(self.mgr, self.main, idx)

    def delete(self):
        def do():
            cfg = net_cfg(self.mgr)
            was_active = cfg["mode"] == self.idx
            del cfg["profiles"][self.idx]
            if isinstance(cfg["mode"], int) and cfg["mode"] > self.idx:
                cfg["mode"] -= 1
            self.mgr.ctx.save_config()
            self.mgr.pop()
            if was_active:
                apply_profile(self.mgr, self.main, None)
        self.mgr.confirm("Eliminare questo IP fisso?", prof_label(self.p), "Elimina", do, True)


def _mask(prefix):
    import ipaddress
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)


def _field_row(s, r, it):
    text(s, it["title"], (r.x + 14, r.centery), 13, T["muted"], anchor="midleft")
    text(s, it["subtitle"], (r.right - 14, r.centery), 15, anchor="midright", maxw=r.w // 2 + 20)


class ArpScreen(Screen):
    title = "Rileva la rete"
    SECS = 25

    def __init__(self, mgr, main):
        super().__init__(mgr)
        self.main = main
        self.stop = threading.Event()
        self.t, self.n, self.res, self.err = 0, 0, None, ""

    def enter(self):
        self.build()
        if not nd.carrier():
            self.err = "Collega prima il cavo"
            return

        def prog(t, total, n):
            if (t, n) != (self.t, self.n):
                self.t, self.n = t, n
                self.mgr.dirty = True

        def job():
            try:
                self.res = nd.sniff_arp(self.SECS, stop=self.stop, progress=prog)
            except OSError as e:
                self.err = str(e)
            self.mgr.dirty = True
            self.build()

        threading.Thread(target=job, daemon=True).start()

    def leave(self):
        if self not in self.mgr.stack:
            self.stop.set()

    def build(self):
        b = self.body
        self.widgets = []
        r = self.res
        if r and r["subnet"]:
            self.widgets.append(Button((12, b.bottom - 50, b.w - 24, 42), "Crea IP fisso con questi dati",
                                       self.use, "primary"))

    def use(self):
        r = self.res
        addr = r["missing"][0] if r.get("missing") else r["subnet"] + "."
        preset = {"gw": r["gateway"] or "", "prefix": 24, "addr": addr}
        self.mgr.pop()
        self.mgr.push(ProfileEdit(self.mgr, self.main, None, preset))

    def draw_content(self, s):
        b = self.body
        x = b.x + 16
        if self.err:
            text(s, self.err, b.center, 14, T["warn"], anchor="center")
            return
        r = self.res
        if r is None:
            text(s, f"In ascolto sulla porta… {self.t}/{self.SECS} s", (x, b.y + 16), 15)
            text(s, f"Indirizzi visti: {self.n}", (x, b.y + 42), 13, T["muted"])
            for i, ln in enumerate(wrap("Il tester ascolta le richieste ARP degli altri dispositivi della rete, "
                                        "senza trasmettere nulla. Su una rete poco trafficata può non vedere niente.",
                                        12, b.w - 32)):
                text(s, ln, (x, b.y + 80 + i * 17), 12, T["muted"])
            return
        if not r["subnet"]:
            text(s, "Nessun traffico ARP ricevuto.", (x, b.y + 16), 15)
            text(s, "Prova a ripetere o chiedi l'IP della presa alla rete.", (x, b.y + 42), 13, T["muted"])
            return
        rows = [("Rete probabile", r["subnet"] + ".0/24"), ("Gateway probabile", r["gateway"] or "non individuato"),
                ("Dispositivi visti", str(len(r["ips"])))]
        for i, (k, v) in enumerate(rows):
            text(s, k, (x, b.y + 12 + i * 40), 12, T["muted"])
            text(s, v, (x, b.y + 28 + i * 40), 16, bold=True)
        miss = r.get("missing") or []
        if miss:
            line = "Cercati ma assenti (forse l'IP di questa presa): " + ", ".join(
                f"{ip} ({r['targets'][ip]}×)" for ip in miss[:3])
            for i, ln in enumerate(wrap(line, 12, b.w - 32)[:2]):
                text(s, ln, (x, b.y + 140 + i * 17), 12, T["accent2"])
        seen = sorted(r["ips"], key=lambda ip: tuple(int(p) for p in ip.split(".")))[:12]
        if seen:
            text(s, "Indirizzi già in uso (da evitare):", (b.centerx + 10, b.y + 12), 12, T["muted"])
            for i, ip in enumerate(seen[:10] if miss else seen):
                n = 5 if miss else 6
                text(s, ip, (b.centerx + 10 + (i // n) * 100, b.y + 30 + (i % n) * 18), 12)
